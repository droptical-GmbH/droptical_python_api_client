import argparse
import logging
import queue
import socket
import struct
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, cast

from flask import Flask, Response, jsonify, request

try:
    import zlib

    import cv2
    import lz4.frame
    import numpy as np
    import zstandard as zstd

    from droptical_api_client.client import (
        FRAME_HEADER_FORMAT,
        HTTP_API_PORT,
        PROTOCOL_HEADER_FORMAT,
        PROTOCOL_MAGIC_BYTES,
        TCP_STREAM_PORT,
        BitDepth,
        ColorMode,
        CompressionAlgorithm,
        FrameType,
    )
    from droptical_api_client.models import (
        AllSettings,
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
        SingleShotResponse,
        SingleShotSettings,
        VideoResponse,
        VideoSettings,
    )

except ImportError as e:
    print(f"Error: A required library is missing or the script was not run as a module. {e}", file=sys.stderr)
    print("Please run from the root directory using: python -m tests.mock_server", file=sys.stderr)
    sys.exit(1)

# =============================================================================
# Server Configuration and State
# =============================================================================

API_HOST = "0.0.0.0"
API_PORT = HTTP_API_PORT
TCP_RAW_HOST = "0.0.0.0"
TCP_RAW_PORT = TCP_STREAM_PORT
MAX_QUEUE_SIZE = 30

logger = logging.getLogger("MockServer")


def get_initial_mock_db() -> dict[str, Any]:
    """Returns the initial state of the mock database."""
    return {
        "single_shot_settings": SingleShotSettings.default(),
        "multi_shot_settings": MultiShotSettings.default(),
        "video_settings": VideoSettings.default(),
        "calculatory_settings": CalculatorySettings.default(),
        "camera_settings": CameraSettings.default(),
        "machine_settings": MachineSettings.default(),
        "machine_info": MachineInfo.default(),
        "preset_info": PresetInfo(gid=1, version=1),
        "presets": [
            Preset(id=1, gid=1, name="Default Mock Preset", version=1, comment="A default preset", isDeleted=False, createdAt="2024-01-01T12:00:00Z", updatedAt="2024-01-01T12:00:00Z"),
            Preset(id=2, gid=2, name="Another Preset", version=1, comment="Another preset for testing", isDeleted=False, createdAt="2024-01-02T12:00:00Z", updatedAt="2024-01-02T12:00:00Z"),
        ],
        "streaming_mode": False,
        "production_mode": False,
    }


mock_db = get_initial_mock_db()

# =============================================================================
# Flask HTTP API Endpoint
# =============================================================================

app = Flask(__name__)
werkzeug_log = logging.getLogger("werkzeug")
werkzeug_log.setLevel(logging.WARNING)


@app.route("/api/control", methods=["POST"])
def api_control() -> Response:
    """
    Main API endpoint that dispatches commands received from the client.

    This function handles incoming JSON requests, validates the command,
    and returns an appropriate JSON response or an error message.
    """
    global mock_db
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"})

    data = request.get_json()
    command = data.get("command")
    payload = data.get("payload")
    logger.info(f"API: Received command '{command}' with payload: {payload}")

    # --- Read-Only Command Handlers ---
    if command == "settings-read":
        all_settings = AllSettings(
            singleShot=mock_db["single_shot_settings"],
            multiShot=mock_db["multi_shot_settings"],
            video=mock_db["video_settings"],
            calculatory=mock_db["calculatory_settings"],
            camera=mock_db["camera_settings"],
            machine=mock_db["machine_settings"],
        )
        return jsonify(all_settings.to_dict())

    elif command in ["single-shot-settings-read", "multi-shot-settings-read", "video-settings-read", "calculatory-settings-read", "camera-settings-read", "machine-settings-read"]:
        key = command.replace("-read", "").replace("-", "_")
        return jsonify(mock_db[key].to_dict())

    elif command == "machine-info-read":
        mock_db["machine_info"].analysisunit.streaming_mode = mock_db["streaming_mode"]
        mock_db["machine_info"].analysisunit.production_mode = mock_db["production_mode"]
        return jsonify(mock_db["machine_info"].to_dict())

    elif command == "preset-info-read":
        return jsonify(mock_db["preset_info"].to_dict())

    elif command == "gpio-levels-read":
        return jsonify(GpioLevels.default().to_dict())

    # --- Write Command Handlers ---
    elif command == "camera-settings-write":
        try:
            mock_db["camera_settings"] = CameraSettings.model_validate(payload)
            return jsonify({"error": ""})
        except Exception as e:
            return Response({"error": "Invalid payload for camera-settings-write", "details": str(e)}, 422)

    elif command == "calculatory-settings-write":
        try:
            mock_db["calculatory_settings"] = CalculatorySettings.model_validate(payload)
            return jsonify({"error": ""})
        except Exception as e:
            return Response({"error": "Invalid payload for calculatory-settings-write", "details": str(e)}, 422)

    elif command == "machine-settings-write":
        try:
            mock_db["machine_settings"] = MachineSettings.model_validate(payload)
            return jsonify({"error": ""})
        except Exception as e:
            return Response({"error": "Invalid payload for machine-settings-write", "details": str(e)}, 422)

    elif command == "streaming-mode-write":
        is_active = payload.get("active", False)
        mock_db["streaming_mode"] = is_active
        if is_active:
            mock_db["production_mode"] = False
        logger.info(f"TCP streaming mode set to: {is_active}")
        return jsonify({"error": ""})

    elif command == "production-mode-write":
        is_active = payload.get("active", False)
        mock_db["production_mode"] = is_active
        if is_active:
            mock_db["streaming_mode"] = False
        logger.info(f"Production mode set to: {is_active}")
        return jsonify({"error": ""})

    # --- Preset Management Command Handlers ---
    elif command == "preset-list":
        return jsonify([p.to_dict() for p in mock_db["presets"]])

    elif command == "preset-load":
        try:
            data = PresetLoadPayload.model_validate(payload)
            for p in mock_db["presets"]:
                if p.gid == data.gid and p.version == data.version:
                    mock_db["preset_info"] = PresetInfo(gid=p.gid, version=p.version)
                    logger.info(f"Loaded preset GID={p.gid}, Version={p.version}")
                    return jsonify({"error": ""})
            return Response({"error": f"Preset with GID={data.gid}, Version={data.version} not found"}, 404)
        except Exception as e:
            return Response({"error": "Invalid payload for preset-load", "details": str(e)}, 422)

    elif command == "preset-create":
        try:
            data = PresetCreatePayload.model_validate(payload)
            now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            max_id = max([p.id for p in mock_db["presets"]] or [0])
            max_gid = max([p.gid for p in mock_db["presets"]] or [0])
            new_preset = Preset(id=max_id + 1, gid=max_gid + 1, name=data.name, comment=data.comment, version=1, isDeleted=False, createdAt=now_iso, updatedAt=now_iso)
            mock_db["presets"].append(new_preset)
            logger.info(f"Created new preset: {new_preset.name}")
            return jsonify(new_preset.to_dict())
        except Exception as e:
            return jsonify({"error": "Invalid payload for preset-create", "details": str(e)}, 422)

    elif command == "preset-create-version":
        try:
            data = PresetCreateVersionPayload.model_validate(payload)
            versions_for_gid = [p for p in mock_db["presets"] if p.gid == data.gid]
            if not versions_for_gid:
                return jsonify({"error": f"Preset with GID={data.gid} not found"}, 404)
            latest_version = max(versions_for_gid, key=lambda p: p.version)
            now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            max_id = max([p.id for p in mock_db["presets"]] or [0])
            new_version_preset = Preset(
                id=max_id + 1,
                gid=data.gid,
                name=latest_version.name,
                comment=data.comment or latest_version.comment,
                version=latest_version.version + 1,
                isDeleted=False,
                createdAt=now_iso,
                updatedAt=now_iso,
            )
            mock_db["presets"].append(new_version_preset)
            logger.info(f"Created new version for preset GID={data.gid}")
            return jsonify(new_version_preset.to_dict())
        except Exception as e:
            return jsonify({"error": "Invalid payload for preset-create-version", "details": str(e)}, 422)

    elif command == "preset-edit":
        try:
            data = PresetEditPayload.model_validate(payload)
            for preset in mock_db["presets"]:
                if preset.id == data.id:
                    preset.name = data.name
                    preset.comment = data.comment
                    preset.updatedAt = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    logger.info(f"Edited preset ID={data.id}")
                    return jsonify(preset.to_dict())
            return jsonify({"error": f"Preset with ID={data.id} not found"}, 404)
        except Exception as e:
            return jsonify({"error": "Invalid payload for preset-edit", "details": str(e)}, 422)

    elif command == "preset-delete":
        try:
            data = PresetDeletePayload.model_validate(payload)
            for preset in mock_db["presets"]:
                if preset.id == data.id:
                    preset.isDeleted = True
                    preset.updatedAt = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    logger.info(f"Deleted preset ID={data.id}")
                    return jsonify({"error": ""})
            return jsonify({"error": f"Preset with ID={data.id} not found"}, 404)
        except Exception as e:
            return jsonify({"error": "Invalid payload for preset-delete", "details": str(e)}, 422)

    # --- Action Command Handlers ---
    elif command == "single-shot":
        return jsonify(SingleShotResponse.default().to_dict())
    elif command == "multi-shot":
        return jsonify(MultiShotResponse.default().to_dict())
    elif command == "video":
        return jsonify(VideoResponse.default().to_dict())

    # --- System & Maintenance Command Handlers ---
    elif command in ["reset-errors", "reboot", "shutdown", "power-on-camera", "power-off-camera", "clear-data"]:
        logger.info(f"Executed mock command: {command}")
        return jsonify({"error": ""})

    elif command == "factory-reset":
        logger.warning("Executing factory reset. All settings and presets will be reset.")
        mock_db = get_initial_mock_db()
        return jsonify({"error": ""})

    return jsonify({"error": f"Unknown or unimplemented command '{command}'"}, 404)


# =============================================================================
# TCP Streaming Subsystem
# =============================================================================
class StatsCollector:
    """Collects and aggregates statistics for the TCP stream."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self._reset_stats()

    def _reset_stats(self) -> None:
        """Resets all collected statistics to zero."""
        self.sent_frames = 0
        self.raw_bytes_total = 0
        self.compressed_bytes_total = 0
        self.sent_bytes_total = 0

    def add_stats(self, raw_bytes: int, compressed_bytes: int, sent_bytes: int) -> None:
        """Adds new stats for a single sent frame."""
        with self.lock:
            self.sent_frames += 1
            self.raw_bytes_total += raw_bytes
            self.compressed_bytes_total += compressed_bytes
            self.sent_bytes_total += sent_bytes

    def get_and_reset_stats(self) -> dict[str, int | float]:
        """Returns a copy of the current stats and resets the counters."""
        with self.lock:
            stats_copy = {k: v for k, v in self.__dict__.items() if k != "lock"}
            self._reset_stats()
            return stats_copy


stats_collector = StatsCollector()


def stats_display_thread_func(interval: float) -> None:
    """
    Periodically logs streaming statistics such as FPS, bandwidth, and
    compression ratio.
    """
    logger.info(f"Stats display thread started. Updating every {interval}s.")
    while True:
        time.sleep(interval)
        stats = stats_collector.get_and_reset_stats()

        frames_per_second = stats["sent_frames"] / interval
        bandwidth_mbps = (stats["sent_bytes_total"] * 8) / (interval * 1024 * 1024)
        raw_bytes = stats["raw_bytes_total"]
        comp_bytes = stats["compressed_bytes_total"]
        compression_ratio = raw_bytes / comp_bytes if comp_bytes > 0 else 0.0

        print("-" * 60)
        print(f"| FPS: {frames_per_second:6.1f} | BW: {bandwidth_mbps:6.2f} Mbit/s | Ratio: {compression_ratio:4.1f}x |")
        print("-" * 60, flush=True)


def compress_task(raw_bytes: bytes, compression_type: CompressionAlgorithm) -> Any:
    """
    Compresses raw image data using a specified algorithm.
    This function is intended to be run in a separate process.
    """
    if compression_type == CompressionAlgorithm.LZ4:
        return lz4.frame.compress(raw_bytes)
    if compression_type == CompressionAlgorithm.ZLIB:
        return zlib.compress(raw_bytes)
    if compression_type == CompressionAlgorithm.ZSTD:
        return zstd.ZstdCompressor().compress(raw_bytes)
    return raw_bytes


def _generate_mock_frame(width: int, height: int, channels: int, frame_counter: int, args: argparse.Namespace) -> bytes:
    """Generates a mock image pattern for the stream based on provided arguments."""
    pattern = args.pattern
    # Common shape for color/grayscale
    shape = (height, width) if channels == ColorMode.GRAYSCALE.value else (height, width, channels)

    if pattern == "gradient":
        base_gradient = np.tile(np.linspace(0, 255, width, dtype=np.uint8), (height, 1))
        shifted_gradient = np.roll(base_gradient, shift=frame_counter, axis=1)
        if channels == ColorMode.GRAYSCALE.value:
            return cast(bytes, shifted_gradient.tobytes())

        zero_channel = np.zeros_like(base_gradient)
        return cast(bytes, np.stack([base_gradient, shifted_gradient, zero_channel], axis=-1).tobytes())

    elif pattern == "noise":
        noise_frame = np.random.randint(0, 256, size=shape, dtype=np.uint8)
        return cast(bytes, noise_frame.tobytes())

    elif pattern == "solid":
        color_str = args.solid_color
        # FIX START: Use a separate variable `fill_value` to avoid type clashes.
        fill_value: int | tuple[int, ...]
        try:
            if "," in color_str:
                color_tuple = tuple(map(int, color_str.split(",")))
                if channels == ColorMode.GRAYSCALE.value:
                    # Use luminance for grayscale conversion
                    fill_value = int(0.299 * color_tuple[0] + 0.587 * color_tuple[1] + 0.114 * color_tuple[2])
                else:
                    fill_value = color_tuple
            else:
                fill_value = int(color_str)
        except (ValueError, IndexError):
            logger.warning(f"Invalid --solid-color '{color_str}'. Defaulting to 128.")
            fill_value = 128

        solid_frame = np.full(shape, fill_value, dtype=np.uint8)
        # FIX END
        return cast(bytes, solid_frame.tobytes())

    elif pattern == "checkerboard":
        size = args.checker_size
        # Create indices for rows and columns, then tile them into a grid
        grid = np.indices(shape[:2]) // size
        # Use modulo arithmetic to create the checkerboard mask
        mask = (grid[0] + grid[1]) % 2

        frame = np.full(shape[:2], 255, dtype=np.uint8)
        frame[mask == 1] = 0

        if channels == ColorMode.RGB.value:
            # Stack the grayscale checkerboard into 3 channels
            frame = np.stack([frame] * 3, axis=-1)

        return cast(bytes, frame.tobytes())

    elif pattern == "stripes":
        stripe_width = args.stripe_width

        if args.stripe_dir == "vertical":
            # Create a 1D pattern for columns and broadcast it vertically
            cols = (np.arange(width) // stripe_width) % 2 * 255
            frame = np.broadcast_to(cols.astype(np.uint8), (height, width))
        else:  # horizontal
            # Create a 1D pattern for rows and broadcast it horizontally
            rows = (np.arange(height) // stripe_width) % 2 * 255
            frame = np.broadcast_to(rows.reshape(height, 1).astype(np.uint8), (height, width))

        if channels == ColorMode.RGB.value:
            frame = np.stack([frame] * 3, axis=-1)

        return cast(bytes, frame.tobytes())

    elif pattern == "counter":
        frame = np.zeros(shape, dtype=np.uint8)
        text = f"Frame: {frame_counter}"
        font_scale = max(1, height / 500)
        thickness = max(1, int(font_scale * 2))
        (text_width, text_height), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        org = ((width - text_width) // 2, (height + text_height) // 2)
        # FIX START: Add an explicit type hint for the `color` variable.
        color: int | tuple[int, int, int] = (255, 255, 255) if channels == ColorMode.RGB.value else 255
        # FIX END
        cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness, cv2.LINE_AA)
        return cast(bytes, frame.tobytes())

    elif pattern == "falling_drops":
        frame = np.zeros(shape, dtype=np.uint8)
        num_drops = 7
        base_speed = 4
        max_radius = 20

        for i in range(num_drops):
            # Use the drop index to create deterministic "randomness"
            # This ensures each drop has a consistent but different path and appearance
            seed = i + 1
            radius = 10 + (seed * 3) % (max_radius - 10)
            speed = base_speed + (seed % 4)
            # Start drops at different horizontal positions
            x_pos = (width // (num_drops + 1)) * seed
            # Calculate vertical position based on frame counter, making it wrap around
            y_pos = (frame_counter * speed + (seed * height // 5)) % (height + radius * 2) - radius

            color2: int | tuple[int, int, int] = (200 + (seed * 10 % 55), 200 + (seed * 20 % 55), 255) if channels == ColorMode.RGB.value else 255

            cv2.circle(frame, (x_pos, y_pos), radius, color2, -1)
            # Add a little bit of blur to make it look more like a drop
        frame = cv2.GaussianBlur(frame, (5, 5), 0)
        return cast(bytes, frame.tobytes())

    # Default to a simple black frame if pattern is unknown
    return np.zeros(shape, dtype=np.uint8).tobytes()


def producer_thread_func(q: queue.Queue, target_fps: int, width: int, height: int, channels: int, args: argparse.Namespace) -> None:
    """
    Generates mock frames and puts them into a queue for processing.
    The rate is controlled by `target_fps`.
    """
    frame_counter = 0
    frame_duration = 1.0 / target_fps if target_fps > 0 else 0
    next_frame_time = time.monotonic()

    while mock_db.get("streaming_mode", False):
        if q.full():
            time.sleep(0.005)
            continue

        raw_bytes = _generate_mock_frame(width, height, channels, frame_counter, args)
        timestamp_us = int(time.time() * 1_000_000)
        q.put((frame_counter, raw_bytes, timestamp_us))
        frame_counter += 1

        if frame_duration > 0:
            next_frame_time += frame_duration
            sleep_duration = next_frame_time - time.monotonic()
            if sleep_duration > 0:
                time.sleep(sleep_duration)

    logger.info("Producer thread finished.")
    q.put(None)


def sender_thread_func(client_connection: socket.socket, result_queue: queue.Queue) -> None:
    """Sends compressed packets from the result queue to the client."""
    try:
        while True:
            packet = result_queue.get()
            if packet is None:
                break
            client_connection.sendall(packet)
    except (ConnectionResetError, BrokenPipeError):
        logger.warning("Sender thread: Client connection lost.")
    finally:
        logger.info("Sender thread finished.")


def handle_client_connection(
    client_conn: socket.socket,
    client_addr: tuple[str, int],
    process_pool: ProcessPoolExecutor,
    compression: CompressionAlgorithm,
    width: int,
    height: int,
    fps: int,
    channels: int,
    bit_depth: BitDepth,
    args: argparse.Namespace,
) -> None:
    """
    Manages a single client connection, orchestrating frame production,
    compression in a process pool, and sending the final packets.
    """
    logger.info(f"TCP: Handling connection from {client_addr}")

    job_queue: queue.Queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
    result_queue: queue.Queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)

    producer = threading.Thread(target=producer_thread_func, args=(job_queue, fps, width, height, channels, args))
    sender = threading.Thread(target=sender_thread_func, args=(client_conn, result_queue))
    producer.daemon = sender.daemon = True
    producer.start()
    sender.start()

    future_to_meta: dict[Any, tuple[int, int, int]] = {}
    try:
        while True:
            try:
                job_data = job_queue.get(timeout=0.1)
                if job_data is None:
                    break
                frame_idx, raw_bytes, ts_us = job_data
                future = process_pool.submit(compress_task, raw_bytes, compression)
                future_to_meta[future] = (frame_idx, ts_us, len(raw_bytes))
            except queue.Empty:
                if not producer.is_alive():
                    break

            for future in as_completed(future_to_meta):
                frame_idx, ts_us, raw_size = future_to_meta.pop(future)
                try:
                    compressed_payload = future.result()
                    proto_header = struct.pack(PROTOCOL_HEADER_FORMAT, PROTOCOL_MAGIC_BYTES, 1, 0, FrameType.FRAME_DATA.value)
                    frame_header = struct.pack(
                        FRAME_HEADER_FORMAT, frame_idx, ts_us, frame_idx % 65536, frame_idx // 65536, width, height, channels, bit_depth.value, compression.value, len(compressed_payload)
                    )
                    packet = proto_header + frame_header + compressed_payload
                    result_queue.put(packet)
                    stats_collector.add_stats(raw_size, len(compressed_payload), len(packet))
                except Exception as e:
                    logger.error(f"Compression task failed: {e}", exc_info=True)
    finally:
        result_queue.put(None)
        producer.join(timeout=1)
        sender.join(timeout=1)
        client_conn.close()
        logger.info(f"TCP: Connection with {client_addr} closed.")


def run_tcp_server_listener(
    process_pool: ProcessPoolExecutor,
    compression: CompressionAlgorithm,
    width: int,
    height: int,
    fps: int,
    channels: int,
    bit_depth: BitDepth,
    args: argparse.Namespace,
) -> None:
    """
    Listens for new TCP connections and spawns a handler thread for each one.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((TCP_RAW_HOST, TCP_RAW_PORT))
        server_socket.listen(5)
        logger.info(f"TCP Listener started on {TCP_RAW_HOST}:{TCP_RAW_PORT}. Ready for connections.")
        while True:
            client_conn, client_addr = server_socket.accept()
            if not mock_db["streaming_mode"]:
                logger.warning(f"TCP: Denied connection from {client_addr} because streamingMode is off.")
                client_conn.close()
                continue
            handler_args = (client_conn, client_addr, process_pool, compression, width, height, fps, channels, bit_depth, args)
            threading.Thread(target=handle_client_connection, args=handler_args, daemon=True).start()


# =============================================================================
# Main Execution
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Process Mock Server.", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--workers", type=int, default=1, help="Number of CPU cores for parallel compression.")
    parser.add_argument("--algo", type=str, default="NONE", choices=[c.name for c in CompressionAlgorithm], help="Compression algorithm.")
    parser.add_argument("--resolution", type=str, default="1400x1600", help="Image resolution as WIDTHxHEIGHT.")
    parser.add_argument("--fps", type=int, default=90, help="Target frames per second.")
    parser.add_argument("--rgb", action="store_true", help="Enable RGB color mode. Default is grayscale.")
    parser.add_argument("--bit-depth", type=int, default=8, choices=[e.value for e in BitDepth], help="Bit depth of frames.")
    parser.add_argument("--pattern", type=str, default="gradient", choices=["gradient", "noise", "solid", "checkerboard", "stripes", "counter", "falling_drops"], help="Generated image pattern.")
    parser.add_argument("--solid-color", type=str, default="128", help="Color for 'solid' pattern. Grayscale (0-255) or RGB ('R,G,B').")
    parser.add_argument("--checker-size", type=int, default=50, help="Side length of squares for 'checkerboard' pattern (in pixels).")
    parser.add_argument("--stripe-dir", type=str, default="vertical", choices=["vertical", "horizontal"], help="Direction for 'stripes' pattern.")
    parser.add_argument("--stripe-width", type=int, default=20, help="Width of stripes for 'stripes' pattern (in pixels).")
    parser.add_argument("--stats-interval", type=float, default=2.0, help="Interval in seconds to display stats (0 to disable).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)-8s] %(name)-12s: %(message)s")

    width, height = map(int, args.resolution.split("x"))
    channels = ColorMode.RGB.value if args.rgb else ColorMode.GRAYSCALE.value
    bit_depth_enum = BitDepth(args.bit_depth)

    logger.info("=" * 60)
    logger.info("Mock Server Starting...")
    logger.info(f"  > Workers: {args.workers}, Algorithm: {args.algo}, FPS: {args.fps}")
    logger.info(f"  > Resolution: {width}x{height}, Color: {'RGB' if args.rgb else 'Gray'}, Bit Depth: {bit_depth_enum.value}")
    logger.info("=" * 60)

    if args.stats_interval > 0:
        threading.Thread(target=stats_display_thread_func, args=(args.stats_interval,), daemon=True).start()

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        tcp_args = (pool, CompressionAlgorithm[args.algo.upper()], width, height, args.fps, channels, bit_depth_enum, args)
        threading.Thread(target=run_tcp_server_listener, args=tcp_args, daemon=True).start()

        logger.info("Background TCP listener started. Starting Flask API server.")
        app.run(host=API_HOST, port=API_PORT)
