from __future__ import annotations

import codecs
import json
import logging
import os
import socket
import struct
import threading
import time
import zlib
from collections.abc import Callable, Generator, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from queue import Empty, Queue
from types import ModuleType
from typing import TYPE_CHECKING, Any, TypeVar, cast

import requests

from .models import (
    TERMINAL_MEASUREMENT_STATUSES,
    AllSettings,
    Attachment,
    BaseApiModel,
    CsvExportConfig,
    CsvExportConfigCollection,
    ExportJob,
    ExportProgressEvent,
    Feature,
    FormattingSettings,
    FrameFilters,
    GpioLevels,
    Infos,
    MachineStatusEvent,
    Measurement,
    MeasurementFilters,
    MeasurementFrame,
    MeasurementType,
    MeasurementUpdatedEvent,
    Page,
    Preset,
    PresetsChangedEvent,
    PresetVersion,
    SettingsUpdatedEvent,
    TriggerAdapterSettings,
    ValueMessage,
    ValveTypeSettings,
)

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

# ---------------------------------------------------------------------------
# Optional dependencies. The HTTP client works without any of these; only the
# TCP streaming / image-conversion features need them. They are imported
# defensively so that `import droptical_api_client` never fails on a machine
# that installed only the core (HTTP) dependencies.
# ---------------------------------------------------------------------------
np: ModuleType | None
cv2: ModuleType | None
Image: ModuleType | None
lz4: ModuleType | None
zstd: ModuleType | None

try:
    import cv2
    import numpy as np
    from PIL import Image
except ImportError:
    np, cv2, Image = None, None, None

try:
    import lz4.frame as _lz4_frame

    lz4 = _lz4_frame
except ImportError:
    lz4 = None

try:
    import zstandard as zstd
except ImportError:
    zstd = None


logger = logging.getLogger("dropticalAPIClient")


# =============================================================================
# Exceptions
# =============================================================================


class DeviceError(Exception):
    """Base class for all client errors."""


class DeviceConnectionError(DeviceError):
    """Raised when the device cannot be reached (network/transport failure)."""


class ApiError(DeviceError):
    """Raised when the API returns an error response.

    Carries the HTTP ``status_code``, a human ``message``, an optional per-field
    ``errors`` map (HTTP 422 validation), and any extra ``details``.
    """

    def __init__(self, message: str, *, status_code: int | None = None, errors: dict[str, Any] | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.errors = errors or {}
        self.details = details or {}

    def __str__(self) -> str:
        base = f"[{self.status_code}] {self.message}" if self.status_code else self.message
        if self.errors:
            base += f" | errors: {self.errors}"
        return base


class ValidationError(ApiError):
    """HTTP 422 — request failed validation (see ``.errors`` for per-field messages)."""


class NotIdleError(ApiError):
    """HTTP 423 — settings can only be changed while the analysis unit is idle."""


class NotFoundError(ApiError):
    """HTTP 404 — the requested resource does not exist."""


class ConflictError(ApiError):
    """HTTP 409 — the request conflicts with the current state (e.g. active job)."""


class DeviceCommandError(ApiError):
    """A functional error reported by the device/machine (typically HTTP 500 ``{error}``)."""


class StreamDisconnectedError(DeviceError):
    """Raised when the TCP stream is closed by the server."""


class ProtocolError(DeviceError):
    """Raised on a malformed TCP stream (bad magic bytes / header)."""


class MeasurementTimeout(DeviceError):
    """Raised when a measurement does not reach a terminal status within the wait timeout."""


# =============================================================================
# Protocol / stream constants
# =============================================================================

TCP_STREAM_PORT = 51222
VALUE_STREAM_PORT = 51223
HTTP_API_PORT = 80
API_BASE_PATH = "/api/v2"
DEFAULT_TIMEOUT = 15.0
CSP_PROTOCOL_MAJOR = 2

# Realtime event channel (customer-facing Reverb app, Pusher protocol).
# The app key is fixed and identical on every device (non-security-critical, LAN only).
REVERB_PORT = 8080
REVERB_APP_KEY = "strobe-events-public"
EVENT_CHANNELS = ("infos", "measurement", "exports", "presets", "settings")

T = TypeVar("T", bound=BaseApiModel)


class FrameType(Enum):
    FRAME_DATA = 1


class CompressionAlgorithm(Enum):
    NONE = 0
    LZ4 = 1
    ZLIB = 2
    ZSTD = 3


class ColorMode(Enum):
    GRAYSCALE = 1
    RGB = 3


class BitDepth(Enum):
    BPP_8 = 8
    BPP_10 = 10
    BPP_12 = 12
    BPP_16 = 16


PROTOCOL_MAGIC_BYTES = b"CSP"
PROTOCOL_HEADER_FORMAT = "!3sBBB"
PROTOCOL_HEADER_SIZE = struct.calcsize(PROTOCOL_HEADER_FORMAT)
# CSP v2 image-frame header is split: a fixed part, then a variable-length JSON
# metadata field, then a standalone payload-length prefix (see the wire spec).
FRAME_HEADER_FIXED_FORMAT = "!QQHHBBBI"
FRAME_HEADER_FIXED_SIZE = struct.calcsize(FRAME_HEADER_FIXED_FORMAT)
PAYLOAD_LEN_FORMAT = "!I"
PAYLOAD_LEN_SIZE = struct.calcsize(PAYLOAD_LEN_FORMAT)


@dataclass
class ImageFrame:
    """A single image frame received from the TCP video stream.

    Distinct from :class:`droptical_api_client.models.MeasurementFrame`, which is a
    measurement-frame *resource* (rois/results) returned by the REST API."""

    index: int
    server_timestamp: datetime
    reception_timestamp: datetime
    width: int
    height: int
    compression: CompressionAlgorithm
    color_mode: ColorMode
    bit_depth: BitDepth
    raw_data: bytes
    metadata: ValueMessage | None = None

    @property
    def latency_ms(self) -> float:
        return (self.reception_timestamp - self.server_timestamp).total_seconds() * 1000

    def to_pil_image(self) -> PILImage:
        if Image is None:
            raise ImportError("Pillow is required for image conversion. Install with: pip install droptical-api-client[image]")
        if self.bit_depth != BitDepth.BPP_8:
            logger.warning(f"to_pil_image conversion for {self.bit_depth.value}-bit data may be lossy.")
        mode = "L" if self.color_mode == ColorMode.GRAYSCALE else "RGB"
        return cast("PILImage", Image.frombytes(mode, (self.width, self.height), self.raw_data))

    def to_numpy_array(self, bgr: bool = True) -> Any:
        if np is None or cv2 is None:
            raise ImportError("numpy and opencv-python are required. Install with: pip install droptical-api-client[opencv]")
        dtype_map = {8: np.uint8, 16: np.uint16}
        dtype = dtype_map.get(self.bit_depth.value)
        if dtype is None:
            raise NotImplementedError(f"NumPy conversion for {self.bit_depth.value}-bit depth not supported.")
        channels = 1 if self.color_mode == ColorMode.GRAYSCALE else 3
        shape = (self.height, self.width) if channels == 1 else (self.height, self.width, channels)
        img_array = np.frombuffer(self.raw_data, dtype=dtype).reshape(shape).copy()
        if self.color_mode == ColorMode.RGB and bgr:
            return cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        return img_array

    def save(self, path_template: str) -> None:
        img = self.to_pil_image()
        directory = os.path.dirname(path_template)
        if directory:
            os.makedirs(directory, exist_ok=True)
        filename = path_template.format(index=self.index, width=self.width, height=self.height, timestamp=self.server_timestamp.strftime("%Y%m%d_%H%M%S_%f"))
        img.save(filename)


# =============================================================================
# Realtime events
# =============================================================================

# Maps a (channel, event) pair to the model that types its payload. Used by
# BroadcastEvent.typed(); unmapped pairs return None so unknown events still
# surface as raw data instead of raising.
_EVENT_MODELS: dict[tuple[str, str], type[BaseApiModel]] = {
    ("infos", "changed"): MachineStatusEvent,
    ("measurement", "updated"): MeasurementUpdatedEvent,
    ("exports", "updated"): ExportProgressEvent,
    ("presets", "changed"): PresetsChangedEvent,
    ("settings", "updated"): SettingsUpdatedEvent,
}


@dataclass
class BroadcastEvent:
    """A single realtime event received from the device's customer Reverb app.

    ``data`` is always the raw (decoded) payload dict. :meth:`typed` parses it into
    the matching model (:class:`MeasurementUpdatedEvent`, :class:`ExportProgressEvent`,
    :class:`PresetsChangedEvent`, :class:`SettingsUpdatedEvent`, :class:`MachineStatusEvent`),
    or returns ``None`` for an event this client version does not model.
    """

    channel: str
    event: str
    data: dict[str, Any]

    def typed(self) -> BaseApiModel | None:
        """Return the parsed payload model for known (channel, event) pairs, else ``None``."""
        model = _EVENT_MODELS.get((self.channel, self.event))
        return model.model_validate(self.data) if model is not None else None


# =============================================================================
# Main client
# =============================================================================


class dropticalAPIClient:
    """Client for the droptical Analysis Unit's v2 REST API and its TCP video stream."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._ip_address: str | None = None
        self._base_url: str | None = None
        self._timeout = timeout
        self._session = requests.Session()
        # Image-stream state
        self._is_image_streaming = False
        self._image_listener_thread: threading.Thread | None = None
        self._image_stop_event = threading.Event()
        # Value-stream state (independent of the image stream)
        self._is_value_streaming = False
        self._value_listener_thread: threading.Thread | None = None
        self._value_stop_event = threading.Event()
        # Event-stream state (WebSocket / Reverb, independent of the above)
        self._is_event_streaming = False
        self._event_listener_thread: threading.Thread | None = None
        self._event_stop_event = threading.Event()

    # --- connection -------------------------------------------------------

    def connect(self, ip_address: str, api_port: int = HTTP_API_PORT) -> None:
        """Configure the target device. No network call is made here (lazy)."""
        self._ip_address = ip_address
        self._base_url = f"http://{ip_address}:{api_port}{API_BASE_PATH}"

    # --- transport --------------------------------------------------------

    def _request(self, method: str, path: str, *, params: Mapping[str, Any] | None = None, json: Any = None) -> Any:
        """Perform an HTTP request and return the parsed JSON (or None for 204).

        Raises the appropriate :class:`ApiError` subclass on 4xx/5xx and
        :class:`DeviceConnectionError` on transport failure.
        """
        if not self._base_url:
            raise DeviceConnectionError("Client is not connected. Call connect() first.")
        url = f"{self._base_url}{path}"
        try:
            response = self._session.request(method, url, params=self._clean_params(params), json=json, timeout=self._timeout)
        except requests.exceptions.RequestException as exc:
            raise DeviceConnectionError(f"Failed to reach the device at {url}: {exc}") from exc

        if response.ok:
            if response.status_code == 204 or not response.content:
                return None
            return response.json()

        self._raise_for_error(response)

    def _request_bytes(self, method: str, path: str, *, params: Mapping[str, Any] | None = None, json: Any = None) -> bytes:
        """Like :meth:`_request` but returns the raw response body (images, zip downloads)."""
        if not self._base_url:
            raise DeviceConnectionError("Client is not connected. Call connect() first.")
        url = f"{self._base_url}{path}"
        try:
            response = self._session.request(method, url, params=self._clean_params(params), json=json, timeout=self._timeout)
        except requests.exceptions.RequestException as exc:
            raise DeviceConnectionError(f"Failed to reach the device at {url}: {exc}") from exc
        if response.ok:
            return response.content
        self._raise_for_error(response)
        return b""  # unreachable

    def _raise_for_error(self, response: requests.Response) -> None:
        status = response.status_code
        message = f"HTTP {status}"
        errors: dict[str, Any] = {}
        details: dict[str, Any] = {}
        try:
            body = response.json()
            if isinstance(body, dict):
                message = body.get("error") or body.get("message") or message
                errors = body.get("errors") or {}
                details = {k: v for k, v in body.items() if k not in ("error", "message", "errors")}
        except ValueError:
            if response.text:
                message = response.text[:500]

        if status == 422:
            raise ValidationError(message, status_code=status, errors=errors, details=details)
        if status == 423:
            raise NotIdleError(message, status_code=status, errors=errors, details=details)
        if status == 404:
            raise NotFoundError(message, status_code=status, errors=errors, details=details)
        if status == 409:
            raise ConflictError(message, status_code=status, errors=errors, details=details)
        raise DeviceCommandError(message, status_code=status, errors=errors, details=details)

    @staticmethod
    def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if not params:
            return None
        out: dict[str, Any] = {}
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, bool):
                # Serialize booleans as "1"/"0": requests would otherwise send "True"/"False",
                # which the API's boolean validation rejects.
                out[key] = "1" if value else "0"
            elif isinstance(value, (list, tuple)):
                # Array query params must use the `key[]=` notation, otherwise the API
                # collapses repeated scalars to the last value and the filter is silently ignored
                # (e.g. type / status / feature / measurement_ids / frame_ids).
                out[f"{key}[]"] = list(value)
            else:
                out[key] = value
        return out

    @staticmethod
    def _filter_query(filters: Any, extra: Mapping[str, Any]) -> dict[str, Any]:
        """Merge a typed filter model (FrameFilters / MeasurementFilters) or a plain dict
        with ad-hoc keyword filters into a single query dict."""
        base: dict[str, Any] = filters.to_query() if hasattr(filters, "to_query") else dict(filters or {})
        return {**base, **extra}

    @staticmethod
    def _body(payload: BaseApiModel | Mapping[str, Any] | None) -> Any:
        if payload is None:
            return None
        if isinstance(payload, BaseApiModel):
            return payload.to_dict(exclude_none=True)
        return payload

    # --- pagination helpers ----------------------------------------------

    def _get_page(self, path: str, model: type[T], params: Mapping[str, Any] | None = None) -> Page[T]:
        raw = self._request("GET", path, params=params)
        data = raw.get("data", []) if isinstance(raw, dict) else raw
        meta = raw.get("meta", {}) if isinstance(raw, dict) else {}
        return Page[model](  # type: ignore[valid-type]
            data=[model.model_validate(item) for item in data],
            next_cursor=meta.get("next_cursor"),
            prev_cursor=meta.get("prev_cursor"),
            per_page=meta.get("per_page"),
        )

    def _iter_pages(self, path: str, model: type[T], params: Mapping[str, Any] | None = None) -> Generator[T, None, None]:
        query: dict[str, Any] = dict(params or {})
        while True:
            page = self._get_page(path, model, query)
            yield from page.data
            if not page.next_cursor:
                break
            query["cursor"] = page.next_cursor

    # =====================================================================
    # Settings
    # =====================================================================

    def get_settings(self, groups: Iterable[str] | None = None) -> AllSettings:
        """Read the full settings payload (optionally only certain groups)."""
        params = {"groups": ",".join(groups)} if groups else None
        return AllSettings.model_validate(self._request("GET", "/settings", params=params))

    def update_settings(self, settings: AllSettings | Mapping[str, Any]) -> AllSettings:
        """Patch settings partially. Only a single ROI may be configured; unknown
        keys are rejected by the server (:class:`ValidationError`)."""
        return AllSettings.model_validate(self._request("PATCH", "/settings", json=self._body(settings)))

    # =====================================================================
    # Infos / machine actions / gpio
    # =====================================================================

    def get_infos(self, groups: Iterable[str] | None = None) -> Infos:
        params = {"groups": ",".join(groups)} if groups else None
        return Infos.model_validate(self._request("GET", "/infos", params=params))

    # Alias for get_infos().
    def get_machine_info(self) -> Infos:
        return self.get_infos()

    def get_features(self) -> list[Feature]:
        """The measurement-feature catalogue (id → name/unit/type). Use it to resolve the
        numeric ``featureId`` values carried by the value and image streams."""
        raw = self._request("GET", "/features")
        data = raw.get("data", []) if isinstance(raw, dict) else raw
        return [Feature.model_validate(f) for f in data]

    def reboot(self) -> None:
        self._request("POST", "/machine/reboot")

    def shutdown(self) -> None:
        self._request("POST", "/machine/shutdown")

    def reset_errors(self) -> None:
        self._request("POST", "/machine/reset-errors")

    def clear_messages(self) -> None:
        self._request("POST", "/machine/clear-messages")

    def identify(self) -> None:
        """Make the device physically identify itself (e.g. blink an LED) so it can be located."""
        self._request("POST", "/machine/identify")

    def abort(self) -> None:
        """Abort whatever the machine is currently running (measurement, live view, …).

        Device-scoped, not tied to a specific measurement; the device no-ops if nothing is
        running. The status is updated asynchronously — poll or listen for the change."""
        self._request("POST", "/machine/abort")

    def get_machine_time(self) -> int:
        """Return the machine's current system time as Unix epoch milliseconds."""
        return int(self._request("GET", "/machine/time")["epoch_ms"])

    def clear_data(self, confirm_serial: str) -> None:
        """Permanently delete all measurement data on the device.

        Guardrail: you must pass the target device's analysis-unit serial number
        (:attr:`AnalysisUnitInfo.serial_number`, from :meth:`get_infos`) as ``confirm_serial``.
        The server rejects a missing/mismatching value with HTTP 422 (:class:`ValidationError`).
        This prevents wiping the *wrong* device in a multi-unit setup — it is not access control.
        Do **not** auto-fill it from ``get_infos()`` right before the call, or the safeguard is moot:
        the whole point is that the caller states which device they mean."""
        logger.warning("clear_data() permanently deletes measurement data on the device.")
        self._request("POST", "/machine/clear-data", json={"confirm_serial": confirm_serial})

    def factory_reset(self, confirm_serial: str) -> None:
        """Reset the device to factory defaults.

        Guardrail: pass the target device's analysis-unit serial number as ``confirm_serial``
        (see :meth:`clear_data`); a missing/mismatching value is rejected with HTTP 422
        (:class:`ValidationError`)."""
        logger.warning("factory_reset() resets the device to factory defaults.")
        self._request("POST", "/machine/factory-reset", json={"confirm_serial": confirm_serial})

    def power_on_camera(self) -> None:
        self._request("POST", "/machine/camera-power/on")

    def power_off_camera(self) -> None:
        self._request("POST", "/machine/camera-power/off")

    def set_lab_mode(self) -> None:
        self._request("POST", "/machine/mode/lab")

    def set_production_mode(self, enabled: bool = True) -> None:
        """Enter production mode (``enabled=True``) or return to lab mode."""
        self._request("POST", "/machine/mode/production" if enabled else "/machine/mode/lab")

    def set_streaming_mode(self, enabled: bool = True) -> None:
        """Enter streaming mode (``enabled=True``) or return to lab mode."""
        self._request("POST", "/machine/mode/streaming" if enabled else "/machine/mode/lab")

    def get_gpio_levels(self) -> GpioLevels:
        return GpioLevels.model_validate(self._request("GET", "/machine/gpios"))

    def set_gpo(self, name: str, value: bool) -> None:
        """Set a GPO output level. ``name`` must match ``GPO1``..``GPO5``."""
        self._request("PATCH", f"/machine/gpios/{name}", json={"value": value})

    # =====================================================================
    # Measurements
    # =====================================================================

    def list_measurements(
        self,
        *,
        cursor: str | None = None,
        per_page: int | None = None,
        filters: MeasurementFilters | Mapping[str, Any] | None = None,
        include: str | None = None,
        frames_limit: int | None = None,
        **extra: Any,
    ) -> Page[Measurement]:
        """List measurements (newest id first), cursor-paginated.

        Pass a typed :class:`MeasurementFilters` (recommended) and/or plain keyword filters:
        ``id`` / ``id_from`` / ``id_to``, ``type`` and ``status`` (value or list),
        ``min_frames`` / ``max_frames``, ``date_from`` / ``date_to`` (or legacy ``date``),
        ``preset`` (id or list), and ``parameter_filters``. e.g.
        ``list_measurements(filters=MeasurementFilters(status="done", type="video"))``.

        ``include="frames"`` (or ``"frames.results"``) embeds a bounded preview of each
        measurement's frames (``frames_limit`` per measurement, default 25) plus a
        ``frames_meta`` block; the outer page size is capped harder in this mode. Heavy —
        follow ``frames_meta.next`` for a measurement's full (paginated) frame set.
        """
        params = {**self._filter_query(filters, extra), "cursor": cursor, "per_page": per_page, "include": include, "frames_limit": frames_limit}
        return self._get_page("/measurements", Measurement, params)

    def iter_measurements(
        self, *, per_page: int | None = None, filters: MeasurementFilters | Mapping[str, Any] | None = None, include: str | None = None, frames_limit: int | None = None, **extra: Any
    ) -> Generator[Measurement, None, None]:
        """Walk every page of :meth:`list_measurements`; accepts the same ``filters`` / ``include``."""
        return self._iter_pages("/measurements", Measurement, {**self._filter_query(filters, extra), "per_page": per_page, "include": include, "frames_limit": frames_limit})

    def get_measurement(self, measurement_id: int, *, include: str | None = None, frames_limit: int | None = None) -> Measurement:
        """Fetch a single measurement (resolves attachments). ``include="frames"`` /
        ``"frames.results"`` embeds a bounded preview of its frames (see ``list_measurements``)."""
        params = self._clean_params({"include": include, "frames_limit": frames_limit})
        return Measurement.model_validate(self._request("GET", f"/measurements/{measurement_id}", params=params))

    def create_measurement(self, type: str | MeasurementType, *, sync: bool = False, parameters: list[dict[str, Any]] | None = None) -> Measurement:
        """Trigger a measurement of the given type.

        With ``sync=True`` the call blocks until the measurement reaches a terminal state. If the
        server-side wait (~30 s) elapses first, the outcome depends on whether it progressed:

        * **progressed but not terminal** (running / awaiting its trigger) → the still-running
          measurement is returned (HTTP 202) with its current, non-terminal ``status`` — *not* an
          error. Check ``result.status`` / :attr:`MeasurementStatus.is_terminal` and keep polling
          with :meth:`wait_for_measurement` if needed.
        * **never started** (still ``waiting``, no progress/frames) → the analysis software did not
          pick it up; this raises :class:`ApiError` (HTTP 504).

        Prefer ``sync=False`` + :meth:`wait_for_measurement` for long runs (video, large multi-shots)."""
        type_value = type.value if isinstance(type, MeasurementType) else str(type)
        body: dict[str, Any] = {"type": type_value, "sync": sync}
        if parameters:
            body["parameters"] = parameters
        return Measurement.model_validate(self._request("POST", "/measurements", json=body))

    def delete_measurement(self, measurement_id: int) -> None:
        self._request("DELETE", f"/measurements/{measurement_id}")

    def bulk_delete_measurements(self, ids: list[int]) -> int:
        """Delete multiple measurements by id; returns the number deleted.

        The whole batch is rejected (HTTP 409 → :class:`ConflictError`) if any measurement is
        still running or has an active export job — nothing is deleted in that case."""
        raw = self._request("DELETE", "/measurements", json={"ids": ids})
        return int(raw.get("deleted", 0)) if isinstance(raw, dict) else 0

    # Convenience triggers (thin wrappers over create_measurement)
    def trigger_singleshot(self, *, sync: bool = False, parameters: list[dict[str, Any]] | None = None) -> Measurement:
        return self.create_measurement(MeasurementType.SINGLESHOT, sync=sync, parameters=parameters)

    def trigger_multishot(self, *, sync: bool = False, parameters: list[dict[str, Any]] | None = None) -> Measurement:
        return self.create_measurement(MeasurementType.MULTISHOT, sync=sync, parameters=parameters)

    def trigger_video(self, *, sync: bool = False, parameters: list[dict[str, Any]] | None = None) -> Measurement:
        return self.create_measurement(MeasurementType.VIDEO, sync=sync, parameters=parameters)

    def trigger_production(self, *, sync: bool = False, parameters: list[dict[str, Any]] | None = None) -> Measurement:
        return self.create_measurement(MeasurementType.PRODUCTION, sync=sync, parameters=parameters)

    def wait_for_measurement(
        self,
        measurement_id: int,
        *,
        timeout: float | None = 300.0,
        poll_interval: float = 0.5,
        on_poll: Callable[[Measurement], None] | None = None,
        should_abort: Callable[[], bool] | None = None,
    ) -> Measurement:
        """Poll ``GET /measurements/{id}`` until it reaches a terminal status.

        Measurements run asynchronously on the device, so results (frames,
        stitched image, video) only become available once the measurement is
        terminal — prefer ``create_measurement(..., sync=False)`` + this poller
        over the server-side ``sync=True`` block, which is capped at ~30 s and
        thus unreliable for video / long multi-shots.

        Returns the final :class:`Measurement`. ``on_poll(measurement)`` is
        invoked after every poll (progress UIs). If ``should_abort()`` returns
        True the loop stops early and the latest measurement is returned (this
        does *not* abort it on the device — call :meth:`abort`
        separately). Raises :class:`MeasurementTimeout` if ``timeout`` elapses
        before a terminal status (pass ``timeout=None`` to wait indefinitely).
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            measurement = self.get_measurement(measurement_id)
            if on_poll is not None:
                on_poll(measurement)
            if measurement.status in TERMINAL_MEASUREMENT_STATUSES:
                return measurement
            if should_abort is not None and should_abort():
                return measurement
            if deadline is not None and time.monotonic() >= deadline:
                raise MeasurementTimeout(f"Measurement {measurement_id} did not reach a terminal status within " f"{timeout}s (last status: {measurement.status!r}).")
            time.sleep(poll_interval)

    # =====================================================================
    # Frames
    # =====================================================================

    def list_frames(
        self, *, cursor: str | None = None, per_page: int | None = None, filters: FrameFilters | Mapping[str, Any] | None = None, include: str | None = None, **extra: Any
    ) -> Page[MeasurementFrame]:
        """List frames across all measurements (newest id first), cursor-paginated.

        Pass a typed :class:`FrameFilters` (recommended) and/or plain keyword filters; both
        are forwarded as snake_case query parameters:

        * ``measurement_id`` / ``measurement_id_from`` / ``measurement_id_to`` — scope by measurement
        * ``measurement_ids`` — list of measurement ids (matches any id in the list)
        * ``id`` / ``id_from`` / ``id_to`` — frame id (exact / range)
        * ``frame_ids`` — explicit list of frame ids (wins over the other id filters)
        * ``index`` — frame index within its measurement
        * ``has_image`` — ``True`` to return only frames that have a stored image
        * ``date_from`` / ``date_to`` — timestamp range (``"YYYY-MM-DD"`` or ``"YYYY-MM-DD HH:MM:SS"``)
        * ``feature`` — feature id, or a list of ids, the frame has a ROI/drop result for
        * ``status`` — result status as the ``ResultStatus`` api value (e.g. ``"nominal"``,
          ``"warning_plus"``), or a list of them; case-insensitive

        e.g. ``list_frames(filters=FrameFilters(measurement_id=7, has_image=True))`` or the
        shorthand ``list_frames(measurement_id=7, has_image=True)``. The measurement-scoped
        ``list_measurement_frames`` does not filter — use ``measurement_id`` here instead.

        ``include="rois"`` embeds each frame's results (rois/drops) — the same shape as
        ``get_frame`` — instead of the lean list form. Heavy on large pages.
        """
        query = {**self._filter_query(filters, extra), "cursor": cursor, "per_page": per_page, "include": include}
        return self._get_page("/frames", MeasurementFrame, query)

    def iter_frames(self, *, per_page: int | None = None, filters: FrameFilters | Mapping[str, Any] | None = None, include: str | None = None, **extra: Any) -> Generator[MeasurementFrame, None, None]:
        """Walk every page of :meth:`list_frames`; accepts the same ``filters`` / ``include``."""
        return self._iter_pages("/frames", MeasurementFrame, {**self._filter_query(filters, extra), "per_page": per_page, "include": include})

    def get_frame(self, frame_id: int) -> MeasurementFrame:
        return MeasurementFrame.model_validate(self._request("GET", f"/frames/{frame_id}"))

    def get_frame_image(self, frame_id: int) -> bytes:
        return self._request_bytes("GET", f"/frames/{frame_id}/image")

    def list_measurement_frames(self, measurement_id: int, *, cursor: str | None = None, per_page: int | None = None) -> Page[MeasurementFrame]:
        return self._get_page(f"/measurements/{measurement_id}/frames", MeasurementFrame, {"cursor": cursor, "per_page": per_page})

    def iter_measurement_frames(self, measurement_id: int, *, per_page: int | None = None) -> Generator[MeasurementFrame, None, None]:
        return self._iter_pages(f"/measurements/{measurement_id}/frames", MeasurementFrame, {"per_page": per_page})

    def get_measurement_frame(self, measurement_id: int, frame_id: int) -> MeasurementFrame:
        return MeasurementFrame.model_validate(self._request("GET", f"/measurements/{measurement_id}/frames/{frame_id}"))

    def get_measurement_frame_image(self, measurement_id: int, frame_id: int) -> bytes:
        return self._request_bytes("GET", f"/measurements/{measurement_id}/frames/{frame_id}/image")

    # =====================================================================
    # Downloads & export jobs
    # =====================================================================

    def _download_url(self, url: str | None, what: str) -> bytes:
        """GET an absolute download URL (the ``download_url`` links returned by the API are
        full ``/api/v2`` URLs), returning the raw body."""
        if not url:
            raise DeviceConnectionError(f"{what} has no download_url.")
        try:
            response = self._session.get(url, timeout=self._timeout)
        except requests.exceptions.RequestException as exc:
            raise DeviceConnectionError(f"Failed to download {what.lower()} at {url}: {exc}") from exc
        if response.ok:
            return response.content
        self._raise_for_error(response)
        return b""  # unreachable

    def download_attachment(self, attachment: Attachment | str) -> bytes:
        """Download a measurement attachment (stitched image, video or export).

        Accepts an :class:`Attachment` (uses its ``download_url`` — a full ``/api/v2``
        attachment link) or a URL string.
        """
        url = attachment.download_url if isinstance(attachment, Attachment) else attachment
        return self._download_url(url, "Attachment")

    def download_export(self, job: ExportJob | str) -> bytes:
        """Download a completed export job's file.

        Accepts an :class:`ExportJob` (uses its ``download_url`` — set only once the job is
        ``complete``) or a URL string.
        """
        url = job.download_url if isinstance(job, ExportJob) else job
        return self._download_url(url, "Export job")

    def download_measurement(self, measurement_id: int, *, format: str, config_name: str | None = None) -> bytes:
        """Stream a measurement export directly (zip bytes). ``format`` is one of
        ``images|csv|json|attachments``."""
        return self._request_bytes("GET", f"/measurements/{measurement_id}/download", params={"format": format, "config_name": config_name})

    def download_report_archive(self) -> bytes:
        """Download the diagnostic report archive as zip bytes (logs, config, machine snapshot, …)."""
        return self._request_bytes("GET", "/downloads/report-archive")

    def download_licenses_archive(self) -> bytes:
        """Download the bundled third-party licenses archive as zip bytes."""
        return self._request_bytes("GET", "/downloads/licenses-archive")

    def create_measurement_export(self, measurement_id: int, *, format: str, config_name: str | None = None, first_frame_id: int | None = None, last_frame_id: int | None = None) -> ExportJob:
        body = {"format": format, "config_name": config_name, "first_frame_id": first_frame_id, "last_frame_id": last_frame_id}
        raw = self._request("POST", f"/measurements/{measurement_id}/exports", json={k: v for k, v in body.items() if v is not None})
        return ExportJob.model_validate(raw["data"] if isinstance(raw, dict) and "data" in raw else raw)

    def download_frames(self, *, format: str, config_name: str | None = None, filters: FrameFilters | Mapping[str, Any] | None = None, **extra: Any) -> bytes:
        """Stream a frame export (same frame filters as :meth:`list_frames`)."""
        params = {"format": format, "config_name": config_name, **self._filter_query(filters, extra)}
        return self._request_bytes("GET", "/frames/download", params=params)

    def create_frame_export(self, *, format: str, config_name: str | None = None, filters: FrameFilters | Mapping[str, Any] | None = None, **extra: Any) -> ExportJob:
        """Queue a frame export job (same frame filters as :meth:`list_frames`)."""
        body = {"format": format, "config_name": config_name, **self._filter_query(filters, extra)}
        raw = self._request("POST", "/frames/exports", json={k: v for k, v in body.items() if v is not None})
        return ExportJob.model_validate(raw["data"] if isinstance(raw, dict) and "data" in raw else raw)

    def list_jobs(self, *, cursor: str | None = None, per_page: int | None = None) -> Page[ExportJob]:
        return self._get_page("/jobs/exports", ExportJob, {"cursor": cursor, "per_page": per_page})

    def iter_jobs(self, *, per_page: int | None = None) -> Generator[ExportJob, None, None]:
        return self._iter_pages("/jobs/exports", ExportJob, {"per_page": per_page})

    def get_job(self, job_id: int) -> ExportJob:
        raw = self._request("GET", f"/jobs/exports/{job_id}")
        return ExportJob.model_validate(raw["data"] if isinstance(raw, dict) and "data" in raw else raw)

    def abort_job(self, job_id: int, *, force: bool = False) -> ExportJob:
        raw = self._request("POST", f"/jobs/exports/{job_id}/abort", params={"force": force})
        return ExportJob.model_validate(raw["data"] if isinstance(raw, dict) and "data" in raw else raw)

    def delete_job(self, job_id: int) -> None:
        self._request("DELETE", f"/jobs/exports/{job_id}")

    # =====================================================================
    # Presets
    # =====================================================================

    def list_presets(self, *, include_deleted: bool = False, sort_by: str = "id", direction: str = "desc") -> list[Preset]:
        raw = self._request("GET", "/presets", params={"include_deleted": include_deleted, "sort_by": sort_by, "direction": direction})
        data = raw.get("data", []) if isinstance(raw, dict) else raw
        return [Preset.model_validate(p) for p in data]

    def get_preset(self, preset_id: int) -> Preset:
        return self._unwrap_preset(self._request("GET", f"/presets/{preset_id}"))

    def create_preset(self, name: str, comment: str | None = None) -> Preset:
        return self._unwrap_preset(self._request("POST", "/presets", json={k: v for k, v in {"name": name, "comment": comment}.items() if v is not None}))

    def edit_preset(self, preset_id: int, name: str, comment: str | None = None) -> Preset:
        return self._unwrap_preset(self._request("PATCH", f"/presets/{preset_id}", json={k: v for k, v in {"name": name, "comment": comment}.items() if v is not None}))

    def delete_preset(self, preset_id: int) -> None:
        self._request("DELETE", f"/presets/{preset_id}")

    def load_preset(self, gid: int, version: int) -> None:
        self._request("POST", "/presets/load", json={"gid": gid, "version": version})

    def create_preset_version(self, preset_id: int, comment: str | None = None) -> Preset:
        return self._unwrap_preset(self._request("POST", f"/presets/{preset_id}/versions", json={k: v for k, v in {"comment": comment}.items() if v is not None}))

    def list_preset_versions(self, preset_id: int) -> list[PresetVersion]:
        """List all versions of the preset group the given preset belongs to, newest first."""
        raw = self._request("GET", f"/presets/{preset_id}/versions")
        data = raw.get("versions", []) if isinstance(raw, dict) else raw
        return [PresetVersion.model_validate(v) for v in data]

    @staticmethod
    def _unwrap_preset(raw: Any) -> Preset:
        return Preset.model_validate(raw["data"] if isinstance(raw, dict) and "data" in raw else raw)

    # =====================================================================
    # GUI settings (WebGUI-local)
    # =====================================================================

    def get_formatting_settings(self) -> FormattingSettings:
        return FormattingSettings.model_validate(self._request("GET", "/gui-settings/formatting"))

    def update_formatting_settings(self, settings: FormattingSettings | Mapping[str, Any]) -> FormattingSettings:
        return FormattingSettings.model_validate(self._request("PATCH", "/gui-settings/formatting", json=self._body(settings)))

    def get_valve_type(self) -> ValveTypeSettings:
        return ValveTypeSettings.model_validate(self._request("GET", "/gui-settings/valve-type"))

    def set_valve_type(self, valve_type: str) -> ValveTypeSettings:
        return ValveTypeSettings.model_validate(self._request("PATCH", "/gui-settings/valve-type", json={"valve_type": valve_type}))

    def get_trigger_adapter(self) -> TriggerAdapterSettings:
        return TriggerAdapterSettings.model_validate(self._request("GET", "/gui-settings/trigger-adapter"))

    def get_csv_export_config(self) -> CsvExportConfigCollection:
        """Read the CSV export configs: the read-only hardcoded presets plus the
        user-editable ``custom_config`` (or None if not yet configured)."""
        return CsvExportConfigCollection.model_validate(self._request("GET", "/gui-settings/csv-export-config"))

    def update_csv_export_config(self, config: CsvExportConfig | Mapping[str, Any]) -> CsvExportConfig:
        """Save (or replace) the Custom CSV export config. The server forces
        ``config_name`` to ``custom`` regardless of what is sent."""
        raw = self._request("PATCH", "/gui-settings/csv-export-config", json=self._body(config))
        return CsvExportConfig.model_validate(raw["custom_config"] if isinstance(raw, dict) and "custom_config" in raw else raw)

    # =====================================================================
    # TCP streaming subsystem (binary CSP protocol; toggled via mode)
    # =====================================================================

    @contextmanager
    def image_stream_session(self, buffer_size: int = 60) -> Generator[Generator[ImageFrame, None, None], None, None]:
        """Context manager for a robust streaming session."""
        try:
            yield self.image_stream(buffer_size=buffer_size)
        finally:
            if self._is_image_streaming:
                self.stop_image_stream()

    def image_stream(self, buffer_size: int = 60) -> Generator[ImageFrame, None, None]:
        """Start the TCP stream and yield :class:`ImageFrame` objects as they arrive."""
        if self._is_image_streaming:
            raise RuntimeError("A stream is already active. Use one stream at a time.")
        frame_queue: Queue[ImageFrame] = Queue(maxsize=buffer_size)

        def _queue_callback(frame: ImageFrame) -> None:
            if frame_queue.full():
                logger.warning("ImageFrame queue is full, dropping oldest frame to keep stream live.")
                try:
                    frame_queue.get_nowait()
                except Empty:
                    pass
            frame_queue.put(frame)

        self._start_image_listener_thread(frame_callback=_queue_callback)
        logger.info("Streaming started. Iterating over frames...")
        while self._is_image_streaming or not frame_queue.empty():
            try:
                yield frame_queue.get(timeout=0.1)
            except Empty:
                if not self._is_image_streaming and frame_queue.empty():
                    break
                continue

    def capture_frames(self, count: int) -> list[ImageFrame]:
        """Capture a specific number of frames from the stream (blocking burst)."""
        if count <= 0:
            return []
        frames: list[ImageFrame] = []
        try:
            with self.image_stream_session() as frame_stream:
                for frame in frame_stream:
                    frames.append(frame)
                    if len(frames) >= count:
                        break
        except DeviceError as e:
            logger.error(f"Failed to get frames due to a device error: {e}")
        return frames

    def stop_image_stream(self) -> None:
        """Stop the data stream and the listener thread."""
        if not self._is_image_streaming:
            return
        logger.info("Stopping stream...")
        self._image_stop_event.set()
        # Stopping the image stream does NOT change the device's operating mode (the stream
        # is mode-independent); the caller owns the mode via set_*_mode().
        if self._image_listener_thread and self._image_listener_thread.is_alive():
            self._image_listener_thread.join(timeout=2)
        self._is_image_streaming = False
        logger.info("Stream stopped.")

    def _start_image_listener_thread(self, frame_callback: Callable[[ImageFrame], None], tcp_port: int = TCP_STREAM_PORT) -> None:
        # The image stream is mode-independent; opening it does NOT change the device's
        # operating mode. Put the device in the desired mode (set_streaming_mode /
        # set_lab_mode / set_production_mode) beforehand — in lab/production the frames
        # additionally carry per-frame measurement values in ImageFrame.metadata.
        self._is_image_streaming = True
        self._image_stop_event.clear()
        self._image_listener_thread = threading.Thread(target=self._listen_for_image_frames, args=(tcp_port, frame_callback), daemon=True)
        self._image_listener_thread.start()
        logger.info("Stream listener thread started.")

    def _listen_for_image_frames(self, port: int, callback: Callable[[ImageFrame], None]) -> None:
        time.sleep(0.2)
        zstd_decompressor = zstd.ZstdDecompressor() if zstd is not None else None

        if self._ip_address is None:
            logger.error("Cannot start listener: IP address not set.")
            return

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                client_socket.connect((self._ip_address, port))
                logger.info(f"TCP listener connected to stream on port {port}.")

                while not self._image_stop_event.is_set():
                    proto_header_data = self._read_exact(client_socket, PROTOCOL_HEADER_SIZE)
                    if not proto_header_data:
                        if not self._image_stop_event.is_set():
                            raise StreamDisconnectedError("Stream closed by server (protocol header).")
                        break

                    identifier, major, minor, ftype_val = struct.unpack(PROTOCOL_HEADER_FORMAT, proto_header_data)
                    if identifier != PROTOCOL_MAGIC_BYTES:
                        raise ProtocolError(f"Invalid protocol magic bytes. Expected {PROTOCOL_MAGIC_BYTES!r}, got {identifier!r}.")
                    if major != CSP_PROTOCOL_MAJOR:
                        raise ProtocolError(f"Unsupported CSP protocol major version {major}. Expected {CSP_PROTOCOL_MAJOR}.")

                    try:
                        frame_type = FrameType(ftype_val)
                    except ValueError:
                        logger.warning(f"Received unknown frame_type '{ftype_val}'. Skipping this packet.")
                        continue

                    if frame_type == FrameType.FRAME_DATA:
                        frame_header_data = self._read_exact(client_socket, FRAME_HEADER_FIXED_SIZE)
                        if not frame_header_data:
                            raise StreamDisconnectedError("Stream closed by server (frame header).")

                        index, ts, w, h, c_mode, b_depth, comp, metadata_len = struct.unpack(FRAME_HEADER_FIXED_FORMAT, frame_header_data)

                        metadata: ValueMessage | None = None
                        if metadata_len:
                            metadata_data = self._read_exact(client_socket, metadata_len)
                            if metadata_data is None:
                                raise StreamDisconnectedError("Stream closed by server (metadata).")
                            metadata = ValueMessage.model_validate(json.loads(metadata_data.decode("utf-8")))

                        payload_len_data = self._read_exact(client_socket, PAYLOAD_LEN_SIZE)
                        if not payload_len_data:
                            raise StreamDisconnectedError("Stream closed by server (payload length).")
                        (p_len,) = struct.unpack(PAYLOAD_LEN_FORMAT, payload_len_data)

                        payload = self._read_exact(client_socket, p_len)
                        if payload is None:
                            raise StreamDisconnectedError("Stream closed by server (payload).")

                        reception_ts = datetime.now(timezone.utc)
                        raw_data = self._decompress_payload(payload, CompressionAlgorithm(comp), zstd_decompressor)

                        callback(
                            ImageFrame(
                                index=index,
                                server_timestamp=datetime.fromtimestamp(ts / 1_000_000, tz=timezone.utc),
                                reception_timestamp=reception_ts,
                                width=w,
                                height=h,
                                compression=CompressionAlgorithm(comp),
                                color_mode=ColorMode(c_mode),
                                bit_depth=BitDepth(b_depth),
                                raw_data=raw_data,
                                metadata=metadata,
                            )
                        )
                    else:
                        logger.info(f"Received packet with frame_type '{frame_type.name}'. No handler implemented yet.")

        except (OSError, ConnectionRefusedError) as e:
            logger.error(f"TCP connection failed: {e}")
        except (StreamDisconnectedError, ProtocolError) as e:
            logger.warning(str(e))
        except Exception as e:
            if not self._image_stop_event.is_set():
                logger.error(f"Unexpected error in listener thread: {e}", exc_info=True)
        finally:
            self._is_image_streaming = False
            self._image_stop_event.set()
            logger.info("TCP listener thread finished.")

    def _read_exact(self, sock: socket.socket, num_bytes: int) -> bytes | None:
        if num_bytes == 0:
            return b""
        sock.settimeout(2.0)
        chunks = bytearray(num_bytes)
        view = memoryview(chunks)
        bytes_recd = 0
        while bytes_recd < num_bytes and not self._image_stop_event.is_set():
            try:
                n = sock.recv_into(view[bytes_recd:], num_bytes - bytes_recd)
                if n == 0:
                    return None
                bytes_recd += n
            except TimeoutError:
                continue
        return bytes(chunks) if bytes_recd == num_bytes else None

    def _decompress_payload(self, payload: bytes, compression: CompressionAlgorithm, zstd_ctx: Any) -> bytes:
        if compression == CompressionAlgorithm.NONE:
            return payload
        if compression == CompressionAlgorithm.LZ4:
            if lz4 is None:
                raise ImportError("lz4 is required for LZ4-compressed streams. Install with: pip install droptical-api-client[stream]")
            return cast(bytes, lz4.decompress(payload))
        if compression == CompressionAlgorithm.ZLIB:
            return zlib.decompress(payload)
        if compression == CompressionAlgorithm.ZSTD:
            if zstd_ctx is None:
                raise ImportError("zstandard is required for ZSTD-compressed streams. Install with: pip install droptical-api-client[stream]")
            return cast(bytes, zstd_ctx.decompress(payload))
        raise ValueError(f"Unknown compression type: {compression}")

    # =====================================================================
    # TCP value stream (port 51223; raw JSON, no CSP framing)
    # =====================================================================

    @contextmanager
    def value_stream_session(self, buffer_size: int = 60) -> Generator[Generator[ValueMessage, None, None], None, None]:
        """Context manager for a robust value-stream session (see :meth:`value_stream`)."""
        try:
            yield self.value_stream(buffer_size=buffer_size)
        finally:
            if self._is_value_streaming:
                self.stop_value_stream()

    def value_stream(self, buffer_size: int = 60) -> Generator[ValueMessage, None, None]:
        """Connect to the raw-JSON value stream and yield :class:`ValueMessage` documents.

        Unlike :meth:`image_stream`, this does NOT toggle the device's mode. The server pushes a
        JSON document on port :data:`VALUE_STREAM_PORT` per measurement **only in lab/production
        mode** — in streaming mode the value stream is silent. Put the unit in lab/production
        (e.g. :meth:`set_production_mode`) before you expect values. Runs on its own listener
        thread, independent of the image stream.
        """
        if self._is_value_streaming:
            raise RuntimeError("A value stream is already active. Use one value stream at a time.")
        message_queue: Queue[ValueMessage] = Queue(maxsize=buffer_size)

        def _queue_callback(message: ValueMessage) -> None:
            if message_queue.full():
                logger.warning("Value-message queue is full, dropping oldest message to keep stream live.")
                try:
                    message_queue.get_nowait()
                except Empty:
                    pass
            message_queue.put(message)

        self._start_value_listener_thread(message_callback=_queue_callback)
        logger.info("Value stream started. Iterating over value messages...")
        while self._is_value_streaming or not message_queue.empty():
            try:
                yield message_queue.get(timeout=0.1)
            except Empty:
                if not self._is_value_streaming and message_queue.empty():
                    break
                continue

    def stop_value_stream(self) -> None:
        """Stop the value stream and its listener thread."""
        if not self._is_value_streaming:
            return
        logger.info("Stopping value stream...")
        self._value_stop_event.set()
        if self._value_listener_thread and self._value_listener_thread.is_alive():
            self._value_listener_thread.join(timeout=2)
        self._is_value_streaming = False
        logger.info("Value stream stopped.")

    def _start_value_listener_thread(self, message_callback: Callable[[ValueMessage], None], tcp_port: int = VALUE_STREAM_PORT) -> None:
        self._is_value_streaming = True
        self._value_stop_event.clear()
        self._value_listener_thread = threading.Thread(target=self._listen_for_values, args=(tcp_port, message_callback), daemon=True)
        self._value_listener_thread.start()
        logger.info("Value-stream listener thread started.")

    def _listen_for_values(self, port: int, callback: Callable[[ValueMessage], None]) -> None:
        if self._ip_address is None:
            logger.error("Cannot start value listener: IP address not set.")
            return

        # An incremental decoder correctly handles multi-byte UTF-8 characters that
        # get split across recv() calls; the JSON decoder carves out complete
        # documents from the accumulated text buffer.
        incremental_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        json_decoder = json.JSONDecoder()
        buffer = ""

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                client_socket.connect((self._ip_address, port))
                client_socket.settimeout(2.0)
                logger.info(f"TCP value listener connected to stream on port {port}.")

                while not self._value_stop_event.is_set():
                    try:
                        data = client_socket.recv(65536)
                    except TimeoutError:
                        continue
                    if not data:
                        if not self._value_stop_event.is_set():
                            raise StreamDisconnectedError("Value stream closed by server.")
                        break
                    buffer += incremental_decoder.decode(data)
                    buffer = self._carve_value_messages(buffer, json_decoder, callback)

        except (OSError, ConnectionRefusedError) as e:
            logger.error(f"TCP value connection failed: {e}")
        except StreamDisconnectedError as e:
            logger.warning(str(e))
        except Exception as e:
            if not self._value_stop_event.is_set():
                logger.error(f"Unexpected error in value listener thread: {e}", exc_info=True)
        finally:
            self._is_value_streaming = False
            self._value_stop_event.set()
            logger.info("TCP value listener thread finished.")

    @staticmethod
    def _carve_value_messages(buffer: str, decoder: json.JSONDecoder, callback: Callable[[ValueMessage], None]) -> str:
        """Carve every complete JSON document out of ``buffer`` and dispatch it.

        Because TCP is a byte stream, ``buffer`` may hold zero, one, or several
        complete JSON documents plus the *start* of the next. Each complete
        document is validated into a :class:`ValueMessage` and passed to
        ``callback``; the incomplete tail is returned to be prepended to the next
        chunk of received bytes.
        """
        idx, n = 0, len(buffer)
        while idx < n:
            while idx < n and buffer[idx].isspace():
                idx += 1
            if idx >= n:
                break
            try:
                obj, end = decoder.raw_decode(buffer, idx)
            except json.JSONDecodeError:
                # Not a complete JSON value yet -> keep the tail for the next chunk.
                break
            idx = end
            if isinstance(obj, dict):
                callback(ValueMessage.model_validate(obj))
            else:
                logger.warning(f"Value stream produced non-object JSON, skipping: {obj!r}")
        return buffer[idx:]

    # --- realtime event stream (WebSocket / Reverb) -----------------------

    @contextmanager
    def event_stream_session(
        self,
        *,
        channels: Iterable[str] = EVENT_CHANNELS,
        app_key: str = REVERB_APP_KEY,
        port: int = REVERB_PORT,
        use_tls: bool = False,
        reconnect: bool = True,
        buffer_size: int = 100,
    ) -> Generator[Generator[BroadcastEvent, None, None], None, None]:
        """Context manager for a realtime event session (see :meth:`event_stream`)."""
        try:
            yield self.event_stream(channels=channels, app_key=app_key, port=port, use_tls=use_tls, reconnect=reconnect, buffer_size=buffer_size)
        finally:
            if self._is_event_streaming:
                self.stop_event_stream()

    def event_stream(
        self,
        *,
        channels: Iterable[str] = EVENT_CHANNELS,
        app_key: str = REVERB_APP_KEY,
        port: int = REVERB_PORT,
        use_tls: bool = False,
        reconnect: bool = True,
        buffer_size: int = 100,
    ) -> Generator[BroadcastEvent, None, None]:
        """Subscribe to the device's realtime event channel and yield :class:`BroadcastEvent`.

        Connects to the customer-facing Reverb app (Pusher protocol) over WebSocket and
        subscribes to ``channels`` (by default: infos, measurement, exports, presets, settings).
        Runs on its own listener thread and, like :meth:`value_stream`, does not toggle any
        device mode. Requires the optional ``websocket-client`` dependency
        (``pip install droptical-api-client[events]``).

        Notifications, not a source of truth: on a broadcast the corresponding REST
        endpoint should be treated as authoritative. With ``reconnect=True`` (default) the
        stream transparently re-subscribes after a connection drop.
        """
        if self._is_event_streaming:
            raise RuntimeError("An event stream is already active. Use one event stream at a time.")
        event_queue: Queue[BroadcastEvent] = Queue(maxsize=buffer_size)

        def _queue_callback(event: BroadcastEvent) -> None:
            if event_queue.full():
                logger.warning("Event queue is full, dropping oldest event to keep the stream live.")
                try:
                    event_queue.get_nowait()
                except Empty:
                    pass
            event_queue.put(event)

        self._start_event_listener_thread(callback=_queue_callback, channels=tuple(channels), app_key=app_key, port=port, use_tls=use_tls, reconnect=reconnect)
        logger.info("Event stream started. Iterating over broadcast events...")
        while self._is_event_streaming or not event_queue.empty():
            try:
                yield event_queue.get(timeout=0.1)
            except Empty:
                if not self._is_event_streaming and event_queue.empty():
                    break
                continue

    def stop_event_stream(self) -> None:
        """Stop the event stream and its listener thread."""
        if not self._is_event_streaming:
            return
        logger.info("Stopping event stream...")
        self._event_stop_event.set()
        if self._event_listener_thread and self._event_listener_thread.is_alive():
            self._event_listener_thread.join(timeout=3)
        self._is_event_streaming = False
        logger.info("Event stream stopped.")

    def _start_event_listener_thread(self, *, callback: Callable[[BroadcastEvent], None], channels: tuple[str, ...], app_key: str, port: int, use_tls: bool, reconnect: bool) -> None:
        self._is_event_streaming = True
        self._event_stop_event.clear()
        self._event_listener_thread = threading.Thread(
            target=self._listen_for_events,
            kwargs={"callback": callback, "channels": channels, "app_key": app_key, "port": port, "use_tls": use_tls, "reconnect": reconnect},
            daemon=True,
        )
        self._event_listener_thread.start()
        logger.info("Event-stream listener thread started.")

    def _listen_for_events(self, *, callback: Callable[[BroadcastEvent], None], channels: tuple[str, ...], app_key: str, port: int, use_tls: bool, reconnect: bool) -> None:
        if self._ip_address is None:
            logger.error("Cannot start event listener: IP address not set.")
            self._is_event_streaming = False
            return
        try:
            import websocket  # websocket-client (Apache-2.0)
        except ImportError:
            self._is_event_streaming = False
            raise ImportError("websocket-client is required for the event stream. Install with: pip install droptical-api-client[events]") from None

        scheme = "wss" if use_tls else "ws"
        url = f"{scheme}://{self._ip_address}:{port}/app/{app_key}?protocol=7&client=droptical-python-api-client&version=2.0.0&flash=false"
        backoff = 1.0
        try:
            while not self._event_stop_event.is_set():
                try:
                    ws = websocket.create_connection(url, timeout=self._timeout)
                    ws.settimeout(2.0)
                    logger.info(f"Event stream connected to {url}.")
                    backoff = 1.0
                    try:
                        self._pump_pusher(ws, channels, callback)
                    finally:
                        ws.close()
                except (OSError, websocket.WebSocketException) as e:
                    if self._event_stop_event.is_set():
                        break
                    logger.warning(f"Event stream connection lost: {e}")

                if not reconnect or self._event_stop_event.is_set():
                    break
                # Interruptible backoff so stop_event_stream() returns promptly.
                self._event_stop_event.wait(backoff)
                backoff = min(backoff * 2, 30.0)
        finally:
            self._is_event_streaming = False
            self._event_stop_event.set()
            logger.info("Event listener thread finished.")

    def _pump_pusher(self, ws: Any, channels: tuple[str, ...], callback: Callable[[BroadcastEvent], None]) -> None:
        """Run the Pusher-protocol receive loop on an open connection until stopped or closed."""
        import websocket

        while not self._event_stop_event.is_set():
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except websocket.WebSocketConnectionClosedException:
                if not self._event_stop_event.is_set():
                    raise StreamDisconnectedError("Event stream closed by server.") from None
                return
            if not raw:
                continue
            try:
                frame = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Event stream produced non-JSON frame, skipping.")
                continue
            if not isinstance(frame, dict):
                continue

            event = frame.get("event", "")
            if event == "pusher:connection_established":
                for channel in channels:
                    ws.send(json.dumps({"event": "pusher:subscribe", "data": {"channel": channel}}))
            elif event == "pusher:ping":
                ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
            elif event in ("pusher:pong", "pusher_internal:subscription_succeeded"):
                continue
            elif event == "pusher:error":
                logger.warning(f"Pusher error frame: {frame.get('data')!r}")
            else:
                self._dispatch_broadcast(frame, callback)

    @staticmethod
    def _dispatch_broadcast(frame: dict[str, Any], callback: Callable[[BroadcastEvent], None]) -> None:
        """Decode a broadcast frame (Pusher wraps the payload as a JSON *string*) and dispatch it."""
        channel = frame.get("channel", "")
        event = frame.get("event", "")
        data = frame.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                logger.warning(f"Broadcast '{channel}:{event}' carried non-JSON data, skipping.")
                return
        if isinstance(data, dict):
            callback(BroadcastEvent(channel=channel, event=event, data=data))
        else:
            logger.warning(f"Broadcast '{channel}:{event}' had non-object data, skipping: {data!r}")


# =============================================================================
# cv2.VideoCapture-like wrapper
# =============================================================================


class dropticalImageStreamCapture:
    """A wrapper that makes the stream behave like ``cv2.VideoCapture``."""

    def __init__(self, ip_address: str, api_port: int = HTTP_API_PORT) -> None:
        self.api = dropticalAPIClient()
        self.api.connect(ip_address, api_port=api_port)
        self._frame_stream_generator: Generator[ImageFrame, None, None] | None = None
        self.thread: threading.Thread | None = None
        self.frame_queue: Queue[ImageFrame] = Queue(maxsize=5)
        self.is_running = False
        self._start()

    def _start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self._frame_stream_generator = self.api.image_stream(buffer_size=10)
        self.thread = threading.Thread(target=self._reader_thread, daemon=True)
        self.thread.start()

    def _reader_thread(self) -> None:
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

    def read(self) -> tuple[bool, Any]:
        if not self.isOpened():
            return False, None
        try:
            frame_obj = self.frame_queue.get(timeout=2.0)
            return True, frame_obj.to_numpy_array(bgr=True)
        except Empty:
            return self.is_running, None

    def release(self) -> None:
        if self.is_running:
            self.is_running = False
            self.api.stop_image_stream()
            if self.thread:
                self.thread.join(timeout=2)
            self.thread = None

    def isOpened(self) -> bool:
        return self.is_running or not self.frame_queue.empty()

    def __enter__(self) -> dropticalImageStreamCapture:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any | None) -> None:
        self.release()
