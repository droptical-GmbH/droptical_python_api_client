"""A guided tour of the v2 REST surface: infos, settings, measurements, frames,
cursor pagination and presets.

Defaults to 127.0.0.1:80 (a device or a locally-running backend).
Run against a real device with, e.g.::

    python -m examples.general.rest_example 192.168.1.100 80
"""

from __future__ import annotations

import argparse
import logging

from droptical_api_client import (
    AllSettings,
    ApiError,
    CameraSettings,
    DeviceConnectionError,
    MeasurementType,
    ValidationError,
    dropticalAPIClient,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

parser = argparse.ArgumentParser(description="Tour of the droptical v2 REST API.")
parser.add_argument("ip_address", type=str, nargs="?", default="127.0.0.1", help="Device IP / hostname. Defaults to 127.0.0.1.")
parser.add_argument("port", type=int, nargs="?", default=80, help="Device API port. Default: 80.")
args = parser.parse_args()

api = dropticalAPIClient()

try:
    api.connect(args.ip_address, api_port=args.port)

    # --- infos ----------------------------------------------------------
    infos = api.get_infos()
    print(f"Unit status: {infos.system.status if infos.system else '?'} | camera: {infos.cameraunit.type if infos.cameraunit else '?'}")

    # --- settings -------------------------------------------------------
    settings = api.get_settings()
    roi = (settings.rois or {}).get(1)
    if roi and roi.processing and roi.processing.uz:
        print(f"ROI 1 processing.uz: startU={roi.processing.uz.start_u} width={roi.processing.uz.width}")

    # Partial update — only the fields you set are sent.
    api.update_settings(AllSettings(camera=CameraSettings(flip_image=True)))
    print("Flipped the camera image.")

    # The backend rejects unknown keys and out-of-bounds values:
    try:
        api.update_settings({"calculation": {"fixedThreshold": 99999}})
    except ValidationError as e:
        print(f"Rejected invalid setting (expected): {e.errors or e.message}")

    # --- measurements + cursor pagination -------------------------------
    m = api.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    print(f"Triggered measurement #{m.id} -> {m.status}")

    print("Recent measurements:")
    for meas in api.iter_measurements(per_page=5):
        print(f"  #{meas.id}  {meas.type}  {meas.status}")

    # --- frames ---------------------------------------------------------
    frames_page = api.list_frames(per_page=5)
    print(f"First page of frames: {[f.id for f in frames_page]} (next_cursor={frames_page.next_cursor})")

    # --- presets --------------------------------------------------------
    print("Presets:")
    for p in api.list_presets():
        print(f"  #{p.id} gid={p.gid} v{p.version}  {p.name}")

except DeviceConnectionError as e:
    print(f"Connection failed: {e}")
except ApiError as e:
    print(f"API error: {e}")
