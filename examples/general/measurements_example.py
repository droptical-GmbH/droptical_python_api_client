"""Actions & measurements — trigger a capture, then turn its results into statistics.

The point of this example is what happens *after* the trigger: fetch the captured
frames, walk their per-drop results, resolve numeric feature ids to names via the
feature catalogue, and aggregate the values (count, mean, min/max, pass/fail).

Defaults to 127.0.0.1:80 (a device or a locally-running backend).
Run against a real device with, e.g.::

    python -m examples.general.measurements_example 192.168.1.100 80
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import Counter

# Allow running from a source checkout without installing the package.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(project_root, "src"))

from droptical_api_client import (  # noqa: E402
    ApiError,
    DeviceConnectionError,
    MeasurementFilters,
    MeasurementFrame,
    MeasurementTimeout,
    MeasurementType,
    dropticalAPIClient,
)


def frame_results(frame: MeasurementFrame):
    """Yield a frame's typed results: per-drop when drops are present, else per-ROI."""
    for roi in frame.rois or []:
        sources = [d.results for d in roi.drops] if roi.drops else [roi.results]
        for results in sources:
            yield from results


parser = argparse.ArgumentParser(description="Trigger a measurement and analyse its results.")
parser.add_argument("ip_address", type=str, nargs="?", default="127.0.0.1", help="Device IP/hostname. Default: 127.0.0.1.")
parser.add_argument("port", type=int, nargs="?", default=80, help="Device API port. Default: 80.")
args = parser.parse_args()

api = dropticalAPIClient()

try:
    api.connect(args.ip_address, api_port=args.port)

    # --- trigger asynchronously and wait for it to finish -------------------
    m = api.create_measurement(MeasurementType.MULTISHOT, sync=False)
    print(f"Multi shot #{m.id} started; waiting…")
    try:
        m = api.wait_for_measurement(
            m.id,
            timeout=60,
            poll_interval=0.5,
            on_poll=lambda meas: print(f"  #{meas.id}: {meas.status} ({meas.progress or 0}%)", end="\r"),
        )
    except MeasurementTimeout as e:
        print(f"\nTimed out: {e}")
        raise SystemExit(1) from e
    print(f"\nMeasurement #{m.id} finished: {m.status} ({m.frames_count} frames)")

    # --- fetch the measurement WITH its frames AND results in ONE call ------
    # include="frames.results" embeds a bounded preview of frames (each carrying its
    # per-drop results) right on the measurement — no per-frame get call (avoids N+1).
    # It is heavier than the lean default, hence opt-in; frames_meta reports how many
    # frames were embedded and links to the full paginated list when truncated.
    detail = api.get_measurement(m.id, include="frames.results", frames_limit=100)
    frames = detail.frames or []
    if detail.frames_meta and detail.frames_meta.truncated:
        print(f"  (embedded {detail.frames_meta.embedded} frames; more at {detail.frames_meta.next})")

    # --- resolve the features and aggregate the per-drop values -------------
    # Keyed by id: that is what the results carry, and what stays put across firmware
    # versions. The name is only for printing — the catalogue decides what it reads.
    by_id = {f.id: f for f in api.get_features()}
    print(f"\nAnalysing {sum(len(list(frame_results(f))) for f in frames)} result(s) "
          f"across {len(frames)} frame(s):")
    for feature_id in (1, 7):  # 1 = drop volume, 7 = main drop velocity
        feature = by_id.get(feature_id)
        if not feature:
            continue
        feature_name = feature.name or f"feature {feature_id}"
        values = [r.value for f in frames for r in frame_results(f)
                  if r.feature_id == feature.id and isinstance(r.value, (int, float))]
        if values:
            print(f"  {feature_name} [{feature.unit}]: n={len(values)} "
                  f"mean={statistics.mean(values):.3f} "
                  f"min={min(values):.3f} max={max(values):.3f} "
                  f"stdev={statistics.pstdev(values):.3f}")
        else:
            print(f"  {feature_name}: no values")

    # --- pass/fail summary from result statuses -----------------------------
    statuses = Counter(r.status for f in frames for r in frame_results(f))
    print(f"  result statuses: {dict(statuses)}")

    # --- find related measurements with typed filters ----------------------
    done = api.list_measurements(filters=MeasurementFilters(status="done"), per_page=5).data
    print(f"\nMost recent done measurements: {[x.id for x in done]}")
    # Other lifecycle calls: iter_measurements(filters=...), get_measurement(id),
    # abort(), delete_measurement(id), bulk_delete_measurements(ids). Per-frame access without embedding:
    # list_measurement_frames(id) / get_measurement_frame(id, frame_id).

    print("Done.")
except DeviceConnectionError as e:
    print(f"Connection failed: {e}")
except ApiError as e:
    print(f"API error: {e}")
