from __future__ import annotations

import logging
import os
import socket
import struct
import threading
import time
import zlib
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from queue import Empty, Queue
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

import lz4.frame
import requests
import zstandard as zstd
from numpy import ndarray

from .models import (
    AllSettings,
    BaseApiModel,
    CalculatorySettings,
    CameraSettings,
    GpioLevels,
    MachineInfo,
    MachineSettings,
    MultiShotResponse,
    MultiShotSettings,
    Preset,
    PresetCreatePayload,
    PresetCreateVersionPayload,
    PresetDeletePayload,
    PresetEditPayload,
    PresetInfo,
    PresetLoadPayload,
    ProductionModePayload,
    SingleShotResponse,
    SingleShotSettings,
    StreamingModePayload,
    VideoResponse,
    VideoSettings,
)

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage
    from zstandard import ZstdDecompressor

# Optional dependencies will be populated in the try-except block
np: ModuleType | None
cv2: ModuleType | None
Image: ModuleType | None

try:
    import cv2
    import numpy as np
    from PIL import Image
except ImportError:
    np, cv2, Image = None, None, None
    logging.getLogger("dropticalAPIClient").warning(
        "Optional libraries 'Pillow', 'opencv-python', or 'numpy' not found. Image processing features will be unavailable. Install them using: pip install Pillow opencv-python numpy"
    )


logger = logging.getLogger("dropticalAPIClient")

# =============================================================================
# Exception Definitions
# =============================================================================


class DeviceError(Exception):
    """Base exception for all errors related to the dropticalAPIClient."""

    pass


class DeviceConnectionError(DeviceError):
    """Raised when a connection to the device cannot be established."""

    pass


class DeviceCommandError(DeviceError):
    """Raised when the device API returns a functional error."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details

    def __str__(self) -> str:
        if self.details:
            return f"{super().__str__()} | Details: {self.details}"
        return super().__str__()


class StreamDisconnectedError(DeviceError):
    """Raised when an active TCP stream is unexpectedly closed by the server."""

    pass


class ProtocolError(DeviceError):
    """Raised on TCP stream protocol violations, e.g., wrong magic bytes."""

    pass


# =============================================================================
# Protocol and API Definitions
# =============================================================================

TCP_STREAM_PORT = 51222
HTTP_API_PORT = 80


class FrameType(Enum):
    """Defines the type of data following the main protocol header."""

    FRAME_DATA = 1


class CompressionAlgorithm(Enum):
    """Enum for TCP stream compression types."""

    NONE = 0
    LZ4 = 1
    ZLIB = 2
    ZSTD = 3


class ColorMode(Enum):
    """Enum for image color modes in the TCP stream."""

    GRAYSCALE = 1
    RGB = 3


class BitDepth(Enum):
    """Enum for image bit depth."""

    BPP_8 = 8
    BPP_10 = 10
    BPP_12 = 12
    BPP_16 = 16


class APICommand(str, Enum):
    """Enumeration of all known API commands for type safety and code completion."""

    SINGLE_SHOT_SETTINGS_READ = "single-shot-settings-read"
    MULTI_SHOT_SETTINGS_READ = "multi-shot-settings-read"
    VIDEO_SETTINGS_READ = "video-settings-read"
    CALCULATORY_SETTINGS_READ = "calculatory-settings-read"
    CAMERA_SETTINGS_READ = "camera-settings-read"
    MACHINE_SETTINGS_READ = "machine-settings-read"
    ALL_SETTINGS_READ = "settings-read"
    MACHINE_INFO_READ = "machine-info-read"
    PRESET_INFO_READ = "preset-info-read"
    GPIO_LEVELS_READ = "gpio-levels-read"
    CALCULATORY_SETTINGS_WRITE = "calculatory-settings-write"
    CAMERA_SETTINGS_WRITE = "camera-settings-write"
    MACHINE_SETTINGS_WRITE = "machine-settings-write"
    SINGLE_SHOT = "single-shot"
    MULTI_SHOT = "multi-shot"
    VIDEO = "video"
    RESET_ERRORS = "reset-errors"
    REBOOT = "reboot"
    SHUTDOWN = "shutdown"
    POWER_ON_CAMERA = "power-on-camera"
    POWER_OFF_CAMERA = "power-off-camera"
    PRODUCTION_MODE_WRITE = "production-mode-write"
    STREAMING_MODE_WRITE = "streaming-mode-write"
    PRESET_LOAD = "preset-load"
    FACTORY_RESET = "factory-reset"
    CLEAR_DATA = "clear-data"
    PRESET_LIST = "preset-list"
    PRESET_CREATE = "preset-create"
    PRESET_CREATE_VERSION = "preset-create-version"
    PRESET_EDIT = "preset-edit"
    PRESET_DELETE = "preset-delete"


PROTOCOL_MAGIC_BYTES = b"CSP"

PROTOCOL_HEADER_FORMAT = "!3sBBB"
PROTOCOL_HEADER_SIZE = struct.calcsize(PROTOCOL_HEADER_FORMAT)

FRAME_HEADER_FORMAT = "!QQIIHHBBBI"
FRAME_HEADER_SIZE = struct.calcsize(FRAME_HEADER_FORMAT)

# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class ProtocolHeader:
    """Represents the main protocol header."""

    identifier: bytes
    major_api_version: int
    minor_api_version: int
    frame_type: FrameType


@dataclass
class FrameHeader:
    """Represents the header for a data frame."""

    id1: int
    ts: int
    id2: int
    id3: int
    width: int
    height: int
    color_mode: ColorMode
    bit_depth: BitDepth
    compression: CompressionAlgorithm
    payload_len: int


@dataclass
class Frame:
    """Represents a single data frame received from the TCP stream."""

    id1: int
    id2: int
    id3: int
    server_timestamp: datetime
    reception_timestamp: datetime
    width: int
    height: int
    compression: CompressionAlgorithm
    color_mode: ColorMode
    bit_depth: BitDepth
    raw_data: bytes

    @property
    def latency_ms(self) -> float:
        """Calculates the end-to-end network latency in milliseconds."""
        return (self.reception_timestamp - self.server_timestamp).total_seconds() * 1000

    def to_pil_image(self) -> PILImage:
        """Converts the frame's raw data to a Pillow Image object."""
        if Image is None:
            raise ImportError("Pillow library is required for this operation.")
        if self.bit_depth != BitDepth.BPP_8:
            logger.warning(f"to_pil_image conversion for {self.bit_depth.value}-bit data may be lossy.")

        mode = "L" if self.color_mode == ColorMode.GRAYSCALE else "RGB"
        return cast(PILImage, Image.frombytes(mode, (self.width, self.height), self.raw_data))

    def to_numpy_array(self, bgr: bool = True) -> ndarray:
        """Converts the frame's raw data to a NumPy array, ready for OpenCV."""
        if np is None or cv2 is None:
            raise ImportError("NumPy and opencv-python are required.")

        dtype_map = {8: np.uint8, 16: np.uint16}
        dtype = dtype_map.get(self.bit_depth.value)
        if dtype is None:
            raise NotImplementedError(f"NumPy conversion for {self.bit_depth.value}-bit depth not supported.")

        channels = 1 if self.color_mode == ColorMode.GRAYSCALE else 3
        shape = (self.height, self.width) if channels == 1 else (self.height, self.width, channels)

        img_array = np.frombuffer(self.raw_data, dtype=dtype).reshape(shape).copy()

        if self.color_mode == ColorMode.RGB and bgr:
            return cast(ndarray, cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR))
        return cast(ndarray, img_array)

    def save(self, path_template: str) -> None:
        """Saves the frame to a file using the Pillow library."""
        img = self.to_pil_image()
        directory = os.path.dirname(path_template)
        if directory:
            os.makedirs(directory, exist_ok=True)
        filename = path_template.format(id1=self.id1, id2=self.id2, id3=self.id3, width=self.width, height=self.height, timestamp=self.server_timestamp.strftime("%Y%m%d_%H%M%S_%f"))
        img.save(filename)


# =============================================================================
# Main API Client
# =============================================================================


class dropticalAPIClient:
    """
    A Python client for interacting with the device's HTTP control API
    and its TCP data stream.
    """

    def __init__(self) -> None:
        self._ip_address: str | None = None
        self._api_url: str | None = None
        self._is_streaming: bool = False
        self._listener_thread: threading.Thread | None = None
        self._stop_event: threading.Event = threading.Event()

    def connect(self, ip_address: str, api_port: int = HTTP_API_PORT) -> None:
        """
        Configures the API client to connect to a specific device.

        Args:
            ip_address: The IP address of the device.
            api_port: The port for the HTTP API endpoint.
        """
        self._ip_address = ip_address
        self._api_url = f"http://{ip_address}:{api_port}/api/control"
        logger.info(f"API configured for device at {self._ip_address}")

    def send_command(
        self,
        command: str | APICommand,
        payload: dict[str, Any] | BaseApiModel | None = None,
        settings: dict[str, Any] | BaseApiModel | None = None,
        save_to_database: bool | None = None,
    ) -> Any:
        """
        Sends a command to the device's API endpoint.

        This method handles request building, Pydantic model serialization,
        and error handling.
        """
        if not self._api_url:
            raise DeviceConnectionError("Device not connected. Call connect() first.")

        command_str = command.value if isinstance(command, Enum) else command

        try:
            APICommand(command_str)
        except ValueError:
            raise DeviceCommandError("Unknown or unimplemented command", details={"unknown_command": command_str}) from ValueError

        request_body: dict[str, Any] = {"command": command_str}

        if payload is not None:
            request_body["payload"] = payload.to_dict(exclude_none=True) if isinstance(payload, BaseApiModel) else payload
        if settings is not None:
            request_body["settings"] = settings.to_dict(exclude_none=True) if isinstance(settings, BaseApiModel) else settings
        if save_to_database is not None:
            request_body["saveToDatabase"] = save_to_database

        try:
            response = requests.post(self._api_url, json=request_body, timeout=10)
            response.raise_for_status()
            json_response = response.json()

            if isinstance(json_response, dict) and json_response.get("error"):
                raise DeviceCommandError(json_response["error"], json_response.get("details"))

            return json_response
        except requests.exceptions.HTTPError as e:
            error_msg = f"API returned HTTP {e.response.status_code}"
            details = None
            try:
                error_data = e.response.json()
                error_msg = error_data.get("error", error_msg)
                details = error_data.get("details")
            except requests.exceptions.JSONDecodeError:
                error_msg = f"{error_msg}: {e.response.text}"
            raise DeviceCommandError(error_msg, details) from e
        except requests.exceptions.RequestException as e:
            raise DeviceConnectionError(f"API communication failed: {e}") from e

    # --- Read-Only Endpoints ---

    def get_single_shot_settings(self) -> SingleShotSettings:
        """Reads and returns the current single shot settings from the device."""
        response = self.send_command(APICommand.SINGLE_SHOT_SETTINGS_READ)
        return SingleShotSettings.model_validate(response)

    def get_multi_shot_settings(self) -> MultiShotSettings:
        """Reads and returns the current multi shot settings from the device."""
        response = self.send_command(APICommand.MULTI_SHOT_SETTINGS_READ)
        return MultiShotSettings.model_validate(response)

    def get_video_settings(self) -> VideoSettings:
        """Reads and returns the current video settings from the device."""
        response = self.send_command(APICommand.VIDEO_SETTINGS_READ)
        return VideoSettings.model_validate(response)

    def get_all_settings(self) -> AllSettings:
        """Reads and returns all current settings from the device."""
        response = self.send_command(APICommand.ALL_SETTINGS_READ)
        return AllSettings.model_validate(response)

    def get_machine_info(self) -> MachineInfo:
        """Reads and returns machine information from the device."""
        response = self.send_command(APICommand.MACHINE_INFO_READ)
        return MachineInfo.model_validate(response)

    def get_preset_info(self) -> PresetInfo:
        """Reads and returns preset information from the device."""
        response = self.send_command(APICommand.PRESET_INFO_READ)
        return PresetInfo.model_validate(response)

    def get_gpio_levels(self) -> GpioLevels:
        """Reads and returns current GPIO levels from the device."""
        response = self.send_command(APICommand.GPIO_LEVELS_READ)
        return GpioLevels.model_validate(response)

    # --- Read/Write Properties ---

    @property
    def calculatory_settings(self) -> CalculatorySettings:
        """Reads the current calculatory settings from the device."""
        response = self.send_command(APICommand.CALCULATORY_SETTINGS_READ)
        return CalculatorySettings.model_validate(response)

    @calculatory_settings.setter
    def calculatory_settings(self, settings: CalculatorySettings) -> None:
        """Sets new calculatory settings on the device."""
        self.send_command(APICommand.CALCULATORY_SETTINGS_WRITE, payload=settings)

    @property
    def camera_settings(self) -> CameraSettings:
        """Reads the current camera settings from the device."""
        response = self.send_command(APICommand.CAMERA_SETTINGS_READ)
        return CameraSettings.model_validate(response)

    @camera_settings.setter
    def camera_settings(self, settings: CameraSettings) -> None:
        """Sets new camera settings on the device."""
        self.send_command(APICommand.CAMERA_SETTINGS_WRITE, payload=settings)

    @property
    def machine_settings(self) -> MachineSettings:
        """Reads the current machine settings from the device."""
        response = self.send_command(APICommand.MACHINE_SETTINGS_READ)
        return MachineSettings.model_validate(response)

    @machine_settings.setter
    def machine_settings(self, settings: MachineSettings) -> None:
        """Sets new machine settings on the device."""
        self.send_command(APICommand.MACHINE_SETTINGS_WRITE, payload=settings)

    # --- Action Endpoints ---

    def trigger_single_shot(self, settings: SingleShotSettings, save_to_database: bool = False) -> SingleShotResponse:
        """Triggers a single shot capture with the specified settings."""
        response = self.send_command(APICommand.SINGLE_SHOT, settings=settings, save_to_database=save_to_database)
        return SingleShotResponse.model_validate(response)

    def trigger_multi_shot(self, settings: MultiShotSettings, save_to_database: bool = False) -> MultiShotResponse:
        """Triggers a multi-shot capture with the specified settings."""
        response = self.send_command(APICommand.MULTI_SHOT, settings=settings, save_to_database=save_to_database)
        return MultiShotResponse.model_validate(response)

    def trigger_video(self, settings: VideoSettings, save_to_database: bool = False) -> VideoResponse:
        """Triggers a video capture with the specified settings."""
        response = self.send_command(APICommand.VIDEO, settings=settings, save_to_database=save_to_database)
        return VideoResponse.model_validate(response)

    # --- Simple and State-Changing Commands ---

    def reset_errors(self) -> None:
        """Clears all pending device errors."""
        self.send_command(APICommand.RESET_ERRORS)

    def reboot(self) -> None:
        """Reboots the device."""
        self.send_command(APICommand.REBOOT)

    def shutdown(self) -> None:
        """Shuts down the device."""
        self.send_command(APICommand.SHUTDOWN)

    def power_on_camera(self) -> None:
        """Powers on the device's camera module."""
        self.send_command(APICommand.POWER_ON_CAMERA)

    def power_off_camera(self) -> None:
        """Powers off the device's camera module."""
        self.send_command(APICommand.POWER_OFF_CAMERA)

    def set_production_mode(self, enabled: bool) -> None:
        """Sets the device's production mode status."""
        self.send_command(APICommand.PRODUCTION_MODE_WRITE, payload=ProductionModePayload(active=enabled))

    def set_streaming_mode(self, enabled: bool) -> None:
        """Enables or disables the TCP streaming server on the device."""
        self.send_command(APICommand.STREAMING_MODE_WRITE, payload=StreamingModePayload(active=enabled))

    def load_preset(self, gid: int, version: int) -> None:
        """Loads a specific preset by its group and version ID."""
        self.send_command(APICommand.PRESET_LOAD, payload=PresetLoadPayload(gid=gid, version=version))

    # --- Destructive and Preset Management Commands ---

    def factory_reset(self) -> None:
        """Resets the device to its factory default settings."""
        logger.warning("Executing factory reset. All data and settings will be lost.")
        self.send_command(APICommand.FACTORY_RESET)

    def clear_data(self) -> None:
        """Deletes all measurement data stored on the device."""
        logger.warning("Executing clear data. All measurement data will be lost.")
        self.send_command(APICommand.CLEAR_DATA)

    def list_presets(self, include_deleted: bool = False, sort_by: str = "name", direction: str = "asc") -> list[Preset]:
        """Retrieves a list of presets from the device."""
        payload = {"includeDeleted": include_deleted, "sortBy": sort_by, "direction": direction}
        response_list = self.send_command(APICommand.PRESET_LIST, payload=payload)
        return [Preset.model_validate(p) for p in response_list]

    def create_preset(self, name: str, comment: str | None = None) -> Preset:
        """Creates a new preset from the current device settings."""
        payload = PresetCreatePayload(name=name, comment=comment)
        response = self.send_command(APICommand.PRESET_CREATE, payload=payload)
        return Preset.model_validate(response)

    def create_preset_version(self, gid: int, comment: str | None = None) -> Preset:
        """Creates a new version of an existing preset."""
        payload = PresetCreateVersionPayload(gid=gid, comment=comment)
        response = self.send_command(APICommand.PRESET_CREATE_VERSION, payload=payload)
        return Preset.model_validate(response)

    def edit_preset(self, preset_id: int, name: str, comment: str | None = None) -> Preset:
        """Edits the name and comment of a specific preset."""
        payload = PresetEditPayload(id=preset_id, name=name, comment=comment)
        response = self.send_command(APICommand.PRESET_EDIT, payload=payload)
        return Preset.model_validate(response)

    def delete_preset(self, preset_id: int) -> Any:
        """Deletes a specific preset."""
        payload = PresetDeletePayload(id=preset_id)
        return self.send_command(APICommand.PRESET_DELETE, payload=payload)

    # --- TCP Streaming Subsystem ---

    @contextmanager
    def streaming_session(self, buffer_size: int = 60) -> Generator[Generator[Frame, None, None], None, None]:
        """A context manager for a robust streaming session."""
        try:
            yield self.stream(buffer_size=buffer_size)
        finally:
            if self._is_streaming:
                self.stop_stream()

    def stream(self, buffer_size: int = 60) -> Generator[Frame, None, None]:
        """Starts the TCP stream and yields Frame objects as they arrive."""
        if self._is_streaming:
            raise RuntimeError("A stream is already active. Use one stream at a time.")
        frame_queue: Queue[Frame] = Queue(maxsize=buffer_size)

        def _queue_callback(frame: Frame) -> None:
            if frame_queue.full():
                logger.warning("Frame queue is full, dropping oldest frame to keep stream live.")
                try:
                    frame_queue.get_nowait()
                except Empty:
                    pass
            frame_queue.put(frame)

        self._start_listener_thread(frame_callback=_queue_callback)
        logger.info("Streaming started. Iterating over frames...")
        while self._is_streaming or not frame_queue.empty():
            try:
                yield frame_queue.get(timeout=0.1)
            except Empty:
                if not self._is_streaming and frame_queue.empty():
                    break
                continue

    def get_frames(self, count: int) -> list[Frame]:
        """Captures a specific number of frames from the stream."""
        if count <= 0:
            return []
        frames: list[Frame] = []
        try:
            with self.streaming_session() as frame_stream:
                for frame in frame_stream:
                    frames.append(frame)
                    if len(frames) >= count:
                        break
        except DeviceError as e:
            logger.error(f"Failed to get frames due to a device error: {e}")
        return frames

    def stop_stream(self) -> None:
        """Stops the data stream and the listener thread."""
        if not self._is_streaming:
            return
        logger.info("Stopping stream...")
        self._stop_event.set()
        try:
            self.set_streaming_mode(False)
        except DeviceError as e:
            logger.warning(f"Could not tell device to stop streaming mode, but stopping client-side: {e}")
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=2)
        self._is_streaming = False
        logger.info("Stream stopped.")

    def _start_listener_thread(self, frame_callback: Callable[[Frame], None], tcp_port: int = TCP_STREAM_PORT) -> None:
        """Starts the background thread for TCP listening."""
        self.set_streaming_mode(True)
        self._is_streaming = True
        self._stop_event.clear()
        self._listener_thread = threading.Thread(target=self._listen_for_frames, args=(tcp_port, frame_callback), daemon=True)
        self._listener_thread.start()
        logger.info("Stream listener thread started.")

    def _listen_for_frames(self, port: int, callback: Callable[[Frame], None]) -> None:
        """The core logic of the listener thread for TCP streaming."""
        time.sleep(0.2)
        zstd_decompressor = zstd.ZstdDecompressor()

        if self._ip_address is None:
            logger.error("Cannot start listener: IP address not set.")
            return

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                # Enable TCP Keep-Alive to prevent the connection from being dropped
                # by network devices or the OS when the app is in the background.
                client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                # Note: More specific keep-alive timers (idle time, interval, count)
                # can be set, but the implementation is OS-specific (e.g., using
                # socket.ioctl on Windows or other SOL_TCP options on Linux).
                client_socket.connect((self._ip_address, port))
                logger.info(f"TCP listener connected to stream on port {port}.")

                while not self._stop_event.is_set():
                    proto_header_data = self._read_exact(client_socket, PROTOCOL_HEADER_SIZE)
                    if not proto_header_data:
                        if not self._stop_event.is_set():
                            raise StreamDisconnectedError("Stream closed by server (protocol header).")
                        break

                    identifier, major, minor, ftype_val = struct.unpack(PROTOCOL_HEADER_FORMAT, proto_header_data)

                    if identifier != PROTOCOL_MAGIC_BYTES:
                        # Decode bytes for safe f-string formatting
                        raise ProtocolError(f"Invalid protocol magic bytes. Expected {PROTOCOL_MAGIC_BYTES!r}, got {identifier.decode()!r}.")

                    try:
                        frame_type = FrameType(ftype_val)
                    except ValueError:
                        logger.warning(f"Received unknown frame_type '{ftype_val}'. Skipping this packet.")
                        continue

                    if frame_type == FrameType.FRAME_DATA:
                        frame_header_data = self._read_exact(client_socket, FRAME_HEADER_SIZE)
                        if not frame_header_data:
                            raise StreamDisconnectedError("Stream closed by server (frame header).")

                        id1, ts, id2, id3, w, h, c_mode, b_depth, comp, p_len = struct.unpack(FRAME_HEADER_FORMAT, frame_header_data)

                        payload = self._read_exact(client_socket, p_len)
                        if not payload:
                            raise StreamDisconnectedError("Stream closed by server (payload).")

                        reception_ts = datetime.now(timezone.utc)
                        raw_data = self._decompress_payload(payload, CompressionAlgorithm(comp), zstd_decompressor)

                        callback(
                            Frame(
                                id1=id1,
                                id2=id2,
                                id3=id3,
                                server_timestamp=datetime.fromtimestamp(ts / 1_000_000, tz=timezone.utc),
                                reception_timestamp=reception_ts,
                                width=w,
                                height=h,
                                compression=CompressionAlgorithm(comp),
                                color_mode=ColorMode(c_mode),
                                bit_depth=BitDepth(b_depth),
                                raw_data=raw_data,
                            )
                        )
                    else:
                        logger.info(f"Received packet with frame_type '{frame_type.name}'. No handler implemented yet.")

        except (OSError, ConnectionRefusedError) as e:
            logger.error(f"TCP connection failed: {e}")
        except (StreamDisconnectedError, ProtocolError) as e:
            logger.warning(str(e))
        except Exception as e:
            if not self._stop_event.is_set():
                logger.error(f"Unexpected error in listener thread: {e}", exc_info=True)
        finally:
            self._is_streaming = False
            self._stop_event.set()
            logger.info("TCP listener thread finished.")

    def _read_exact(self, sock: socket.socket, num_bytes: int) -> bytes | None:
        """Reads an exact number of bytes from a socket."""
        if num_bytes == 0:
            return b""
        sock.settimeout(2.0)
        chunks = bytearray(num_bytes)
        view = memoryview(chunks)
        bytes_recd = 0
        while bytes_recd < num_bytes and not self._stop_event.is_set():
            try:
                n = sock.recv_into(view[bytes_recd:], num_bytes - bytes_recd)
                if n == 0:
                    return None
                bytes_recd += n
            except TimeoutError:
                continue
        return bytes(chunks) if bytes_recd == num_bytes else None

    def _decompress_payload(self, payload: bytes, compression: CompressionAlgorithm, zstd_ctx: ZstdDecompressor) -> bytes:
        """Decompresses a payload based on the compression type."""
        if compression == CompressionAlgorithm.NONE:
            return payload
        if compression == CompressionAlgorithm.LZ4:
            return cast(bytes, lz4.frame.decompress(payload))
        if compression == CompressionAlgorithm.ZLIB:
            return zlib.decompress(payload)
        if compression == CompressionAlgorithm.ZSTD:
            return cast(bytes, zstd_ctx.decompress(payload))
        raise ValueError(f"Unknown compression type: {compression}")


# =============================================================================
# Convenience Wrapper Class
# =============================================================================


class dropticalAPIClientCapture:
    """
    A wrapper that makes the dropticalAPIClient stream behave like cv2.VideoCapture.
    """

    def __init__(self, ip_address: str, api_port: int = HTTP_API_PORT) -> None:
        self.api = dropticalAPIClient()
        self.api.connect(ip_address, api_port=api_port)
        self._frame_stream_generator: Generator[Frame, None, None] | None = None
        self.thread: threading.Thread | None = None
        self.frame_queue: Queue[Frame] = Queue(maxsize=5)
        self.is_running = False
        self._start()

    def _start(self) -> None:
        """Initializes and starts the background reader thread."""
        if self.is_running:
            return
        self.is_running = True
        self._frame_stream_generator = self.api.stream(buffer_size=10)
        self.thread = threading.Thread(target=self._reader_thread, daemon=True)
        self.thread.start()

    def _reader_thread(self) -> None:
        """The thread that consumes the API stream and fills the internal queue."""
        try:
            if self._frame_stream_generator is None:
                return
            for frame in self._frame_stream_generator:
                if not self.is_running:
                    break
                if self.frame_queue.full():
                    try:
                        self.frame_queue.get_nowait()
                    except Empty:
                        pass
                self.frame_queue.put(frame)
        except DeviceError as e:
            logger.error(f"DeviceCapture stream failed: {e}")
        finally:
            self.is_running = False

    def read(self) -> tuple[bool, ndarray | None]:
        """
        Reads the next frame from the stream. Mimics cv2.VideoCapture.read().
        """
        if not self.isOpened():
            return False, None
        try:
            frame_obj = self.frame_queue.get(timeout=2.0)
            return True, frame_obj.to_numpy_array(bgr=True)
        except Empty:
            return self.is_running, None

    def release(self) -> None:
        """Stops the stream and releases all resources."""
        if self.is_running:
            self.is_running = False
            self.api.stop_stream()
            if self.thread:
                self.thread.join(timeout=2)
            self.thread = None

    def isOpened(self) -> bool:
        """Checks if the stream is currently running or has frames in the buffer."""
        return self.is_running or not self.frame_queue.empty()

    def __enter__(self) -> dropticalAPIClientCapture:
        """Context manager entry point."""
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any | None) -> None:
        """Context manager exit point, ensures resources are released."""
        self.release()
