import argparse
import logging
import os
import sys
import threading
import time

# This block allows the example to be run without installing the package.
# It adds the project's 'src' directory to the Python path.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(project_root, "src"))


from droptical_api_client import (  # noqa: E402
    ActionSettings,
    AllSettings,
    ApiError,
    CameraSettings,
    DeviceConnectionError,
    MeasurementTimeout,
    dropticalAPIClient,
)

logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(message)s")

# --- Setup Command-Line Argument Parsing ---
parser = argparse.ArgumentParser(
    description="Subscribe to the device's realtime event stream, perform a few safe actions, and print the events they trigger.",
    epilog="Requires the optional 'events' dependency: pip install droptical-api-client[events]",
)
parser.add_argument("ip_address", type=str, nargs="?", default="127.0.0.1", help="The IP address or hostname of the droptical device. Defaults to 127.0.0.1.")
parser.add_argument("port", type=int, nargs="?", default=80, help="The device REST API port. Default: 80.")
args = parser.parse_args()

api = dropticalAPIClient()

DEMO_PRESET_NAME = "python-events-demo"


def remove_demo_presets(fallback_gid: int, fallback_version: int) -> None:
    """Delete any leftover demo preset (e.g. from an interrupted earlier run).

    The create endpoint activates the new preset, and the currently-loaded preset cannot be
    deleted — so if a demo is loaded, load the fallback (default) preset first to un-load it.
    """
    demos = [p for p in api.list_presets() if p.name == DEMO_PRESET_NAME]
    if not demos:
        return
    loaded = api.get_infos().preset
    loaded_gid = loaded.gid if loaded is not None else None
    if loaded_gid is not None and loaded_gid in {p.gid for p in demos}:
        api.load_preset(gid=fallback_gid, version=fallback_version)
    for p in demos:
        try:
            api.delete_preset(p.id)
        except ApiError:
            pass  # best-effort cleanup


def listen_for_events() -> None:
    """Run the event stream on a background thread and print each broadcast as it arrives."""
    try:
        with api.event_stream_session() as events:
            for event in events:
                # `typed()` returns the matching model (e.g. SettingsUpdatedEvent,
                # PresetsChangedEvent) or None for events this client doesn't model.
                payload = event.typed() or event.data
                print(f"   ← event  [{event.channel}/{event.event}]  {payload}")
    except ImportError as exc:
        # websocket-client not installed — the actions below still run, just without events.
        print(f"   (event stream unavailable: {exc})")
    except Exception as exc:  # noqa: BLE001 - a demo listener should never crash the example
        print(f"   (event stream stopped: {exc})")


try:
    print(f"Connecting to device at: {args.ip_address}")
    api.connect(args.ip_address, api_port=args.port)

    # Fetch the current state first so we can restore anything we touch.
    settings = api.get_settings()
    original_flip = bool(settings.camera.flip_image) if settings.camera else False

    # Start listening in the background, then give the stream a moment to connect
    # to the device's customer Reverb app and subscribe to the channels.
    print("\nStarting event stream (channels: infos, measurement, presets, settings)...")
    listener = threading.Thread(target=listen_for_events, daemon=True)
    listener.start()
    time.sleep(2.0)

    try:
        # --- Action 1: change a machine setting (and restore it) -> 'settings' events ---
        print("\n1) Toggling camera.flip_image and restoring it...")
        api.update_settings(AllSettings(camera=CameraSettings(flip_image=not original_flip)))
        time.sleep(1.0)
        api.update_settings(AllSettings(camera=CameraSettings(flip_image=original_flip)))
        time.sleep(1.0)

        # --- Action 2: run a multi-shot on a throwaway preset -> presets + settings + measurement + export events ---
        # Customer-safe by design: we do everything on a NEW preset, so the customer's active
        # preset/settings are never touched. Reloading their preset at the end resets the
        # settings we changed. Internal trigger + a fixed frame count makes the burst
        # self-complete, so it also works on a real device without an external trigger source.
        print("\n2) Running an isolated multi-shot on a throwaway preset (customer settings stay untouched)...")

        # The default preset (gid 0) always exists and is a safe neutral fallback.
        default = next((p for p in api.list_presets() if p.gid == 0), None)
        fallback_gid = default.gid if default else 0
        fallback_version = default.version if (default and default.version is not None) else 1

        # Clear any leftover demo from an earlier interrupted run, then remember the customer's
        # currently-active preset so we can restore it afterwards.
        remove_demo_presets(fallback_gid, fallback_version)
        original = api.get_infos().preset
        original_gid = original.gid if (original is not None and original.gid is not None) else fallback_gid
        original_version = original.version if (original is not None and original.version is not None) else fallback_version

        created = api.create_preset(DEMO_PRESET_NAME, comment="events example — throwaway")
        try:
            api.load_preset(gid=created.gid, version=created.version)  # work on the demo preset
            time.sleep(1.0)

            # Self-triggering 5-frame burst at 5 Hz (internal trigger => no external signal needed).
            api.update_settings(AllSettings(action=ActionSettings(use_external_trigger=False, image_count=5, frequency=5)))
            time.sleep(1.0)

            print("   Triggering multi-shot...")
            measurement = api.trigger_multishot(sync=False)
            try:
                final = api.wait_for_measurement(measurement.id, timeout=20)
                print(f"   measurement {measurement.id} reached: {final.status}")

                # --- Action 3: export the measurement -> 'exports'/'updated' events ---
                # Queue an async CSV export (the hardcoded 'excel_global' config always exists),
                # then poll the job to a terminal state so its progress events flush. The export
                # runs entirely on the throwaway measurement, so the customer's data is untouched.
                try:
                    print("   Exporting the measurement to CSV (fires 'exports'/'updated' events)...")
                    job = api.create_measurement_export(measurement.id, format="csv", config_name="excel_global")
                    terminal = {"complete", "failed", "cancelled", "deleted"}
                    for _ in range(20):
                        job = api.get_job(job.id)
                        if job.status in terminal:
                            break
                        time.sleep(0.5)
                    print(f"   export job {job.id} reached: {job.status}")
                    api.delete_job(job.id)
                    time.sleep(1.0)
                except ApiError as exc:
                    print(f"   (export skipped: {exc})")
            except MeasurementTimeout:
                print("   (measurement didn't finish in time — aborting)")
                api.abort_measurement(measurement.id)
                time.sleep(1.0)
            time.sleep(1.0)
            api.delete_measurement(measurement.id)
        finally:
            # Restore the customer's preset (this resets the settings we changed), then drop the demo.
            try:
                api.load_preset(gid=original_gid, version=original_version)
                time.sleep(1.0)
                api.delete_preset(created.id)
                time.sleep(1.0)
            except ApiError as exc:
                print(f"   (cleanup warning: {exc})")
        time.sleep(1.0)

        # Let any final events flush before we stop the stream.
        print("\nWaiting briefly for the last events...")
        time.sleep(1.5)
    except ApiError as exc:
        # e.g. the unit is not idle (423) — the demo can't drive it right now.
        print(f"\nCould not perform an action ({exc}). The device may be busy; try again when it is idle.")
    finally:
        api.stop_event_stream()
        listener.join(timeout=5)

    print("\nDone. If no events appeared, make sure the device's external event app is enabled and reachable on the Reverb port.")

except DeviceConnectionError as exc:
    print(f"Connection failed: {exc}")
    sys.exit(1)
