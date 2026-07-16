"""Machine — turn device info into a readiness check, then control mode and GPIO.

Shows not just which calls exist, but how to *use* their results: computing a
readiness verdict from infos, building a reusable feature lookup, switching mode
only when needed, and reading a GPO back to confirm a write.

Defaults to 127.0.0.1:80 (a device or a locally-running backend).
Run against a real device with, e.g.::

    python -m examples.general.machine_example 192.168.1.100 80
"""

from __future__ import annotations

import argparse
import os
import sys

# Allow running from a source checkout without installing the package.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(project_root, "src"))

from droptical_api_client import ApiError, DeviceConnectionError, dropticalAPIClient  # noqa: E402

parser = argparse.ArgumentParser(description="Check device readiness and control mode/GPIO.")
parser.add_argument("ip_address", type=str, nargs="?", default="127.0.0.1", help="Device IP/hostname. Default: 127.0.0.1.")
parser.add_argument("port", type=int, nargs="?", default=80, help="Device API port. Default: 80.")
args = parser.parse_args()

api = dropticalAPIClient()

try:
    api.connect(args.ip_address, api_port=args.port)

    # --- turn infos into a readiness verdict --------------------------------
    infos = api.get_infos()
    checks = {
        "idle": infos.system.status == "idle",
        # Use the authoritative camera status (the `power` field is optional and not emitted by
        # all firmware); `powered_on` is the ready state.
        "camera powered on": bool(infos.cameraunit and infos.cameraunit.status == "powered_on"),
        "storage < 90% used": bool(infos.storage and infos.storage.free / infos.storage.size > 0.10),
    }
    for label, passed in checks.items():
        print(f"  [{'OK ' if passed else 'XX '}] {label}")
    if infos.storage:
        print(f"  storage free: {infos.storage.free / infos.storage.size:.0%}")
    ready = all(checks.values())
    print(f"Device ready for a measurement: {ready}")

    # --- build a reusable feature lookup (id -> name/unit) ------------------
    # Streams and frame results reference features by numeric id; keep this map to
    # label them later (see the measurements / history examples).
    feature_by_id = {f.id: f for f in api.get_features()}
    print(f"Feature catalogue: {len(feature_by_id)} features")
    sample = next(iter(feature_by_id.values()), None)
    if sample:
        print(f"  e.g. #{sample.id} = {sample.name} [{sample.unit}]")

    # --- switch mode only if it is not already what we want -----------------
    if infos.system.mode != "lab":
        api.set_lab_mode()
        print(f"Mode was '{infos.system.mode}' -> switched to lab.")
    else:
        print("Already in lab mode; no change.")

    # --- write a GPO and read it back to confirm ----------------------------
    api.set_gpo("GPO1", True)  # name must match ^GPO[1-5]$
    gpo1 = api.get_gpio_levels().gpo.get("GPO1")
    print(f"GPO1 after set-high: {gpo1} ({'confirmed' if gpo1 else 'NOT confirmed'})")

    # Maintenance (safe): api.reset_errors() / api.clear_messages()
    # DESTRUCTIVE — never called here: reboot() / shutdown() / factory_reset() / clear_data()

    print("Done.")
except DeviceConnectionError as e:
    print(f"Connection failed: {e}")
except ApiError as e:
    print(f"API error: {e}")
