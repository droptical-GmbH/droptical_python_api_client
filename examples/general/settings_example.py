"""Settings — explore the whole settings tree, then do a verified read-modify-write.

First it walks every settings group and its sub-members (generically, from the
returned model, so it adapts to whatever the device sends), drills into the nested
ROI tree with typed access, and then shows how to *use* the data: derive an ROI
area, flip a value and confirm the round-trip, update only when needed, and let the
backend reject an out-of-range value.

Defaults to 127.0.0.1:80 (a device or a locally-running backend).
Run against a real device with, e.g.::

    python -m examples.general.settings_example 192.168.1.100 80
"""

from __future__ import annotations

import argparse
import os
import sys

# Allow running from a source checkout without installing the package.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(project_root, "src"))

from droptical_api_client import (  # noqa: E402
    AllSettings,
    ApiError,
    CalculationSettings,
    CameraSettings,
    DeviceConnectionError,
    NotIdleError,
    ValidationError,
    dropticalAPIClient,
)

FLAT_GROUPS = ["camera", "calculation", "export", "action", "machine"]  # rois/features are maps


def show_group(name: str, group) -> None:
    """Print a group's populated fields; nested objects are shown as their member names."""
    if group is None:
        print(f"[{name}] (not set)")
        return
    data = group.model_dump(exclude_none=True)
    print(f"[{name}] {len(data)} field(s)")
    for key, value in data.items():
        if isinstance(value, dict):
            print(f"    {key}: {{{', '.join(value)}}}")  # nested -> just the sub-member names
        elif isinstance(value, list):
            print(f"    {key}: [{len(value)} item(s)]")
        else:
            print(f"    {key} = {value}")


parser = argparse.ArgumentParser(description="Explore and update the droptical settings tree.")
parser.add_argument("ip_address", type=str, nargs="?", default="127.0.0.1", help="Device IP/hostname. Default: 127.0.0.1.")
parser.add_argument("port", type=int, nargs="?", default=80, help="Device API port. Default: 80.")
args = parser.parse_args()

api = dropticalAPIClient()

try:
    api.connect(args.ip_address, api_port=args.port)

    settings = api.get_settings()
    print(f"Settings groups: {list(AllSettings.model_fields)}\n")

    # --- explore every flat group and its sub-members -----------------------
    for name in FLAT_GROUPS:
        show_group(name, getattr(settings, name, None))

    # --- explore the map groups (rois / features) ---------------------------
    rois = settings.rois or {}
    print(f"[rois] {len(rois)} ROI(s)")
    for rid, roi in rois.items():
        print(f"    ROI {rid}: {{{', '.join(roi.model_dump(exclude_none=True))}}}")

    features = settings.features or {}
    print(f"[features] {len(features)} feature setting(s)")
    sample = next(iter(features.values()), None)
    if sample is not None:
        print(f"    each feature has: {{{', '.join(sample.model_dump(exclude_none=True))}}}")

    # --- drill into the nested ROI tree with typed access -------------------
    roi = rois.get(1)
    if roi:
        print("\nROI 1 rectangles (uz plane):")
        for role in ("processing", "nozzle", "exclusion"):
            rect = getattr(roi, role, None)
            if rect and rect.uz:
                uz = rect.uz
                print(f"    {role}: {uz.width}x{uz.height} @ ({uz.start_u},{uz.start_z}) -> area {uz.width * uz.height:,} px²")
        if roi.nozzle_tip and roi.nozzle_tip.uz:
            print(f"    nozzleTip: point ({roi.nozzle_tip.uz.u},{roi.nozzle_tip.uz.z})")

    # --- read only certain groups ------------------------------------------
    subset = api.get_settings(groups=["camera", "calculation"])
    print(f"\nFiltered read (camera+calculation only): calculation set? {subset.calculation is not None}, action set? {subset.action is not None}")

    # --- verified read-modify-write of a boolean ---------------------------
    original_flip = bool(settings.camera and settings.camera.flip_image)
    after = api.update_settings(AllSettings(camera=CameraSettings(flip_image=not original_flip)))
    new_flip = bool(after.camera and after.camera.flip_image)
    print(f"\nflip_image {original_flip} -> {new_flip} ({'round-trip confirmed' if new_flip != original_flip else 'MISMATCH'})")
    api.update_settings(AllSettings(camera=CameraSettings(flip_image=original_flip)))  # restore

    # --- update only when the value actually differs -----------------------
    desired = 130
    current = settings.calculation.fixed_threshold if settings.calculation else None
    if current != desired:
        api.update_settings(AllSettings(calculation=CalculationSettings(fixed_threshold=desired)))
        print(f"fixedThreshold {current} -> {desired}")
    else:
        print(f"fixedThreshold already {desired}; no update sent")

    # --- let the backend reject an out-of-range value (422) ----------------
    try:
        api.update_settings({"calculation": {"fixedThreshold": 99999}})
    except ValidationError as e:
        print(f"Backend rejected out-of-range value (expected): {e.errors or e}")

    print("Done.")
except NotIdleError:
    print("Unit is busy — settings can only be changed while it is idle.")
except DeviceConnectionError as e:
    print(f"Connection failed: {e}")
except ApiError as e:
    print(f"API error: {e}")
