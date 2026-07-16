"""Presets — find/upsert a preset by name and apply it, then clean up.

Shows how to *work with* the preset list: indexing it by name, deciding whether to
create or reuse (an upsert), applying a specific version, and only deleting what
this example itself created.

Defaults to 127.0.0.1:80 (a device or a locally-running backend).
Run against a real device with, e.g.::

    python -m examples.general.presets_example 192.168.1.100 80
"""

from __future__ import annotations

import argparse
import os
import sys

# Allow running from a source checkout without installing the package.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(project_root, "src"))

from droptical_api_client import ApiError, DeviceConnectionError, ValidationError, dropticalAPIClient  # noqa: E402

TARGET_NAME = "Example Recipe"

parser = argparse.ArgumentParser(description="Find, apply and manage droptical presets.")
parser.add_argument("ip_address", type=str, nargs="?", default="127.0.0.1", help="Device IP/hostname. Default: 127.0.0.1.")
parser.add_argument("port", type=int, nargs="?", default=80, help="Device API port. Default: 80.")
args = parser.parse_args()

api = dropticalAPIClient()

try:
    api.connect(args.ip_address, api_port=args.port)

    # --- index the preset list by name --------------------------------------
    presets = api.list_presets(sort_by="id", direction="asc")
    by_name = {p.name: p for p in presets}
    default = next((p for p in presets if p.gid == 0), None)
    print(f"{len(presets)} preset(s); default = {default.name if default else '?'}")
    for p in presets:
        print(f"  #{p.id} gid={p.gid} v{p.version}  {p.name}")

    # --- upsert: reuse the target preset if it exists, else create it -------
    created_here = False
    target = by_name.get(TARGET_NAME)
    if target is None:
        target = api.create_preset(TARGET_NAME, comment="created by the presets example")
        created_here = True
        print(f"Created '{TARGET_NAME}' as #{target.id} (gid={target.gid}).")
    else:
        print(f"Reusing existing '{TARGET_NAME}' (#{target.id}, gid={target.gid}, v{target.version}).")

    # --- apply the newest version of it onto the device --------------------
    api.load_preset(gid=target.gid, version=target.version)
    print(f"Loaded gid={target.gid} v{target.version}.")

    # --- clean up only what we created -------------------------------------
    if created_here:
        # The currently-loaded preset cannot be deleted (409), so switch to the
        # default first to release it, then delete what we created.
        if default is not None and default.id != target.id:
            api.load_preset(gid=default.gid, version=default.version)
            print(f"Released it by loading '{default.name}' (gid={default.gid}).")
            api.delete_preset(target.id)
            print(f"Deleted the preset this example created (#{target.id}).")
        else:
            print(f"Kept #{target.id} (no other preset to switch to before deleting).")
    else:
        print("Left the pre-existing preset untouched.")

    print("Done.")
except ValidationError as e:
    print(f"Preset validation failed: {e.errors or e}")  # e.g. name must be 3-32 characters
except DeviceConnectionError as e:
    print(f"Connection failed: {e}")
except ApiError as e:
    print(f"API error: {e}")
