"""History — browse recorded frames, aggregate a feature across them, and save an image.

Shows how to *use* the history: build a per-frame summary table, aggregate one
feature (min/max/mean) over the most recent frames, and persist a frame image to disk.

Defaults to 127.0.0.1:80 (a device or a locally-running backend).
Run against a real device with, e.g.::

    python -m examples.general.history_example 192.168.1.100 80
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys

# Allow running from a source checkout without installing the package.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(project_root, "src"))

from droptical_api_client import ApiError, DeviceConnectionError, FrameFilters, MeasurementFrame, dropticalAPIClient  # noqa: E402

RECENT = 15  # how many recent frames to summarise


def first_value(frame: MeasurementFrame, feature_id: int):
    """First numeric value for a feature in a frame (per-drop results when present, else per-ROI)."""
    for roi in frame.rois or []:
        sources = [d.results for d in roi.drops] if roi.drops else [roi.results]
        for results in sources:
            for r in results:
                if r.feature_id == feature_id and isinstance(r.value, (int, float)):
                    return r.value
    return None


parser = argparse.ArgumentParser(description="Summarise recent droptical frames and save one image.")
parser.add_argument("ip_address", type=str, nargs="?", default="127.0.0.1", help="Device IP/hostname. Default: 127.0.0.1.")
parser.add_argument("port", type=int, nargs="?", default=80, help="Device API port. Default: 80.")
args = parser.parse_args()

api = dropticalAPIClient()

try:
    api.connect(args.ip_address, api_port=args.port)

    # Resolve by id, not by name: ids are stable (they key the stream payloads and the
    # stored results), names follow the firmware's catalogue and have changed before.
    VOLUME_FEATURE_ID = 1
    volume = next((f for f in api.get_features() if f.id == VOLUME_FEATURE_ID), None)

    # --- fetch the most recent frames WITH results in ONE call --------------
    # The lean list omits per-frame rois; opt in with include="rois" so every frame
    # already carries its results — no extra get_frame() per frame (avoids the N+1).
    frames = api.list_frames(per_page=RECENT, include="rois").data
    if not frames:
        print("No frames in history yet.")
        raise SystemExit(0)

    # --- per-frame summary table -------------------------------------------
    print(f"{'frame':>7}  {'timestamp':<20}  volume")
    volumes = []
    for fr in frames:
        vol = first_value(fr, volume.id) if volume else None
        if vol is not None:
            volumes.append(vol)
        ts = (fr.timestamp or "")[:19].replace("T", " ")
        print(f"{fr.id:>7}  {ts:<20}  {vol if vol is not None else '-'}")

    # --- aggregate the feature over those frames ---------------------------
    if volumes and volume:
        print(f"\nVolume [{volume.unit}] over {len(volumes)} frame(s): "
              f"mean={statistics.mean(volumes):.3f} "
              f"min={min(volumes):.3f} max={max(volumes):.3f}")

    # --- filtered queries (GET /frames supports a rich filter set) ----------
    # Filters are captured in the typed FrameFilters model (see also plain kwargs).
    mid = frames[0].measurement_id
    newest = len(api.list_frames(per_page=200))
    same_meas = len(api.list_frames(filters=FrameFilters(measurement_id=mid), per_page=200))
    with_images = len(api.list_frames(filters=FrameFilters(has_image=True), per_page=200))
    print(f"\nFilters (within the newest {newest} frames):")
    print(f"  measurement_id={mid}          -> {same_meas} frame(s)")
    print(f"  has_image=True                -> {with_images} frame(s)")
    if volume:
        with_volume = len(api.list_frames(filters=FrameFilters(feature=volume.id), per_page=200))
        print(f"  feature={volume.id} (Volume result) -> {with_volume} frame(s)")
    # status takes the ResultStatus api value (e.g. "nominal"), not the raw integer.
    nominal = len(api.list_frames(filters=FrameFilters(status="nominal"), per_page=200))
    print(f"  status='nominal'                    -> {nominal} frame(s)")
    # Filters combine; iter_frames walks every page of a filtered query:
    combined = sum(1 for _ in api.iter_frames(filters=FrameFilters(measurement_id=mid, has_image=True)))
    print(f"  measurement_id={mid} AND has_image -> {combined} frame(s) (all pages)")

    # --- persist a frame image to disk -------------------------------------
    image = api.get_frame_image(frames[0].id)  # raw image/jpeg|png bytes
    out_path = os.path.abspath(f"frame_{frames[0].id}.png")
    with open(out_path, "wb") as fh:
        fh.write(image)
    print(f"Saved frame #{frames[0].id} image ({len(image)} bytes) -> {out_path}")

    # Measurement-scoped variants: list_measurement_frames(mid) / get_measurement_frame(mid, fid)
    # and iter_frames(...) / iter_measurement_frames(mid) to walk every page.

    print("Done.")
except DeviceConnectionError as e:
    print(f"Connection failed: {e}")
except ApiError as e:
    print(f"API error: {e}")
