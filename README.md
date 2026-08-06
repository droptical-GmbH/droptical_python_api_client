# Python droptical API Client

## Overview

A Python client for the droptical Analysis Unit. It provides a high-level interface for
controlling the device through its **v2 REST API** (`/api/v2`) and for consuming its
high-performance **TCP video stream**.

The project includes:

  * `src/droptical_api_client/client.py`: the core client classes and HTTP transport.
  * `src/droptical_api_client/models.py`: Pydantic models mirroring the v2 API contract.
  * A clear hierarchy of custom exceptions for predictable error handling.
  * A convenience wrapper that makes the video stream compatible with OpenCV's `VideoCapture`.
  * Example applications (`general`, `cv2`, `gui`).
  * An integration test suite that runs against a live device/backend (no bundled mock).

> **Versioning:** this client tracks the device's OpenAPI specification 1:1. Client
> **2.0.0** targets **OpenAPI 2.0.0** (the RESTful `/api/v2` surface). The previous
> command-based API (`POST /api/control`) is no longer used.

## Features

  * **REST + TCP**: a RESTful control API (`/api/v2`) plus a low-latency TCP video stream.
  * **Type-safe models**: Pydantic models for every request/response, validated strictly against
    the API contract — an unexpected field fails loudly, signalling the client is out of date with
    the device rather than silently dropping data.
  * **Cursor pagination**: list endpoints (measurements, frames, jobs) use keyset cursors;
    `iter_*()` helpers walk all pages automatically.
  * **High-performance streaming**: a multi-threaded TCP client handling LZ4 / ZSTD / Zlib
    codecs, with `ImageFrame` → Pillow / NumPy(OpenCV) conversion helpers.
  * **Robust errors**: a typed exception hierarchy (`ValidationError`, `NotIdleError`,
    `NotFoundError`, `ConflictError`, `DeviceConnectionError`, …).

## Prerequisites

  * Python 3.10 or newer
  * `pip` and `venv`

## Installation

```bash
git clone git@github.com:droptical-GmbH/droptical_python_api_client.git
cd droptical_python_api_client
python3 -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\activate
pip install .
```

**Optional extras** (combine as needed):

| Extra | Adds | Use for |
|---|---|---|
| `image` | Pillow | `ImageFrame.to_pil_image()` / `ImageFrame.save()` |
| `stream` | lz4, zstandard | LZ4 / ZSTD stream decompression |
| `opencv` | opencv-python | `ImageFrame.to_numpy_array()`, `dropticalImageStreamCapture` |
| `events` | websocket-client | `event_stream()` — realtime Reverb/Pusher events |
| `gui` | PySide6, pyinstaller | the PySide6 GUI example (LGPL — app stays MIT) |
| `test` | pytest | running the test suite (against a live backend) |

```bash
pip install '.[image,stream,opencv]'      # everything the HTTP+stream client needs
pip install '.[test]'                      # to run the test suite (integration tests, see tests/)
```

> **License note:** the core library and all extras are permissive-friendly. The optional
> **`gui`** extra pulls in **PySide6/shiboken6 (LGPL-3.0)** and PyInstaller; LGPL keeps the
> example's own code MIT and only asks that the bundled Qt libraries stay replaceable (use a
> PyInstaller one-folder build when distributing). The `gui` extra is not needed to use the client.

## Getting started: examples

The command-line examples take an optional `IP [PORT]` (default `127.0.0.1 80`) and run against a
droptical device (or any reachable test backend). Point them at your device:

```bash
python -m examples.general.rest_example 192.168.1.100 80   # REST tour
python -m examples.general.live_stream_example 192.168.1.100 80   # console live stream
python -m examples.general.events_example 192.168.1.100 80        # realtime events (needs [events])
python -m examples.cv2.cv2_capture_example 192.168.1.100 80       # OpenCV window
```

> **Testing:** the test suite (`tests/`) runs as integration tests against a live device or test
> backend — point it with `DROPTICAL_TEST_HOST` / `DROPTICAL_TEST_PORT` (default `127.0.0.1:80`);
> it skips if none is reachable. The pure model/parsing tests in `tests/test_models.py` need no
> backend. No device mock is bundled with the client.

-----

## Usage

### Connecting

```python
from droptical_api_client import dropticalAPIClient, DeviceConnectionError

api = dropticalAPIClient()
api.connect("192.168.1.100")          # api_port defaults to 80

try:
    infos = api.get_infos()
    print(infos.system.status, infos.cameraunit.type)
except DeviceConnectionError as e:
    print(f"Connection failed: {e}")
```

### Settings (`GET` / `PATCH /settings`)

Settings are grouped into `camera`, `calculation`, `export`, `action`, `machine`, `rois`
and `features`. `rois` and `features` are **1-based maps** (the key is the identity). Only a
single ROI may be configured; each ROI holds `processing` / `nozzle` / `exclusion`
rectangles plus the point-based `nozzleTip`.

```python
from droptical_api_client import AllSettings, CameraSettings, CalculationSettings

settings = api.get_settings()                       # full payload
roi = settings.rois[1]
print(roi.nozzle_tip.uz.u, roi.processing.uz.width)

# Partial update — only send what you change:
api.update_settings(AllSettings(camera=CameraSettings(flip_image=True)))
api.update_settings({"calculation": {"fixedThreshold": 130}})   # dicts work too

# Read only certain groups:
cam = api.get_settings(groups=["camera"]).camera
```

Validation is enforced server-side: unknown keys, a second ROI, an out-of-bounds value or an
exclusion outside the nozzle raise `ValidationError` (with a per-field `.errors` map);
changing settings while the unit is busy raises `NotIdleError`.

### Measurements

```python
from droptical_api_client import MeasurementType

# Trigger (async by default; sync=True blocks until the measurement finishes)
m = api.create_measurement(MeasurementType.SINGLESHOT, sync=True)
# or the convenience wrappers:
api.trigger_singleshot()
api.trigger_multishot(sync=True)

# Read / list (cursor pagination)
one = api.get_measurement(m.id)
page = api.list_measurements(per_page=50, status="done")
for meas in api.iter_measurements(type="video"):    # walks every page
    print(meas.id, meas.status)

api.abort_measurement(m.id)
api.delete_measurement(m.id)
```

### Frames

```python
frame = api.get_frame(42)                    # includes rois/results
img_bytes = api.get_frame_image(42)          # image/jpeg|png bytes

for f in api.iter_frames(measurement_id=7):  # global frame list, filtered
    ...

for f in api.iter_measurement_frames(7):     # frames scoped to a measurement
    ...
```

### Machine actions, mode & GPIO

```python
api.reboot(); api.shutdown()
api.reset_errors(); api.clear_messages()
api.power_on_camera(); api.power_off_camera()
api.set_lab_mode()
api.set_production_mode(True)                 # False → lab mode
# ⚠️ irreversible + device-scoped: pass the TARGET device's analysis-unit serial number
# (api.get_infos().analysisunit.serial_number) as a confirmation. It guards against wiping the
# WRONG unit in a multi-device setup — not access control. Pass the serial you *expect* rather
# than reading it back from the device you're about to wipe, or the safeguard is moot; a
# missing/mismatching value is rejected with HTTP 422 (ValidationError).
api.factory_reset(confirm_serial="SN-AU-1234")   # ⚠️ resets to defaults
api.clear_data(confirm_serial="SN-AU-1234")      # ⚠️ deletes measurement data

levels = api.get_gpio_levels()                # {gpi: {...}, gpo: {...}}
api.set_gpo("GPO1", True)                     # name must be GPO1..GPO5
```

### Presets

```python
presets = api.list_presets(include_deleted=False, sort_by="id", direction="desc")
p = api.create_preset("Recipe A", comment="…")
api.edit_preset(p.id, name="Recipe A2")
api.create_preset_version(p.id)
api.load_preset(gid=p.gid, version=1)
api.delete_preset(p.id)
```

### Exports & jobs

```python
# Direct (streamed) download — returns zip bytes:
data = api.download_measurement(7, format="csv", config_name="excel_global")

# Queued export job (for large sets):
job = api.create_measurement_export(7, format="json")
print(job.status)                             # "queued"
job = api.get_job(job.id)
api.abort_job(job.id, force=False)
for j in api.iter_jobs():
    ...
```

### Error handling

All API errors derive from `ApiError` (itself a `DeviceError`):

| Exception | HTTP | Meaning |
|---|---|---|
| `ValidationError` | 422 | request failed validation — see `.errors` |
| `NotIdleError` | 423 | settings changed while the unit is not idle |
| `NotFoundError` | 404 | resource does not exist |
| `ConflictError` | 409 | conflicts with current state (e.g. active job) |
| `DeviceCommandError` | 5xx | the device reported a functional error |
| `DeviceConnectionError` | — | the device could not be reached (transport) |

```python
from droptical_api_client import ValidationError, NotIdleError

try:
    api.update_settings({"calculation": {"fixedThreshold": 9999}})
except ValidationError as e:
    print(e.status_code, e.errors)            # {'rois.1...': ['...'], ...}
except NotIdleError:
    print("Unit is busy — cannot change settings right now.")
```

### TCP video streaming

The binary TCP stream is independent of the REST API; the recommended entry point is the
`image_stream_session` context manager, which starts and stops the stream for you. The image
stream is mode-independent and `image_stream_session` does **not** change the device mode, so put
the device in a suitable mode first (e.g. `api.set_streaming_mode()`); in lab/production each
frame additionally carries its measurement values in `frame.metadata`.

```python
import cv2
from droptical_api_client import dropticalAPIClient

api = dropticalAPIClient()
api.connect("192.168.1.100")
api.set_streaming_mode()  # or set_lab_mode() / set_production_mode(); the stream no longer sets this

with api.image_stream_session() as frames:
    for frame in frames:
        print(f"ImageFrame {frame.index}  latency {frame.latency_ms:.1f} ms  {frame.width}x{frame.height}")
        cv2.imshow("Live", frame.to_numpy_array(bgr=True))
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
cv2.destroyAllWindows()
```

`api.capture_frames(count)` grabs a fixed number of frames as a blocking burst.

**The `ImageFrame` dataclass** (a live stream image — distinct from the REST `MeasurementFrame`
resource): `index` (frame index since connection start), `server_timestamp`,
`reception_timestamp`, `width`, `height`, `compression`, `color_mode`, `bit_depth`, `raw_data`,
and `metadata` (a `ValueMessage` with the frame's measurement results in lab/production mode,
or `None` in plain streaming mode); plus `latency_ms`, `to_pil_image()`,
`to_numpy_array(bgr=True)`, `save(path_template)`.

**The value stream** (`api.value_stream()` / `api.value_stream_session()`, port 51223) is a
second, independent connection that yields `ValueMessage` documents (measurement results as
JSON) whenever a measurement is triggered — no image data. Its schema is the same as a
`ImageFrame.metadata`.

### Realtime events (WebSocket)

`api.event_stream()` / `api.event_stream_session()` subscribe to the device's realtime event
channel (a Reverb/Pusher WebSocket on port 8080) and yield `BroadcastEvent` objects. These are
**notifications** — when one arrives, treat the matching REST endpoint as the source of truth.
Requires the optional dependency: `pip install droptical-api-client[events]` (websocket-client,
Apache-2.0).

```python
from droptical_api_client import dropticalAPIClient, MeasurementUpdatedEvent

api = dropticalAPIClient()
api.connect("192.168.1.100")  # REST host; the event stream uses port 8080 automatically

with api.event_stream_session() as events:          # default channels: infos, measurement, exports, presets, settings
    for event in events:
        print(event.channel, event.event, event.data)
        payload = event.typed()                      # parsed model, or None for unmodeled events
        if isinstance(payload, MeasurementUpdatedEvent) and payload.status_changed:
            print("measurement", payload.measurement_id, "->", payload.measurement.status)
```

Each `BroadcastEvent` carries `channel`, `event` (the wire name, e.g. `updated`, `changed`),
and the raw `data` dict (snake_case, matching the REST API). `event.typed()` returns the
matching model — `MachineStatusEvent`, `MeasurementUpdatedEvent`, `ExportProgressEvent`,
`PresetsChangedEvent`, or `SettingsUpdatedEvent` — or `None` for an event this client version does
not model (unknown events still surface as raw `data`). The stream runs on its own thread and, with `reconnect=True`
(default), transparently re-subscribes after a connection drop. The customer app key
(`strobe-events-public`) is fixed fleet-wide and applied by default; pass `app_key=`/`port=` to
override. Call `api.stop_event_stream()` (or leave the `event_stream_session` context) to stop.

### OpenCV-style capture wrapper

```python
from droptical_api_client import dropticalImageStreamCapture
import cv2

with dropticalImageStreamCapture("192.168.1.100") as cap:
    while cap.isOpened():
        ret, frame = cap.read()               # frame is a BGR NumPy array
        if not ret:
            break
        cv2.imshow("droptical", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
cv2.destroyAllWindows()
```
