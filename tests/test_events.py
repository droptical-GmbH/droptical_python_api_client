"""Backend-free unit tests for the realtime broadcast event models and decoding.

These mirror ``test_models.py``: pure parsing/dispatch, no device or WebSocket needed
(the ``websocket-client`` dependency is imported lazily only when a stream is opened).
"""

from __future__ import annotations

import json

from droptical_api_client import (
    BroadcastEvent,
    ExportProgressEvent,
    MachineStatusEvent,
    MeasurementUpdatedEvent,
    PresetsChangedEvent,
    SettingsUpdatedEvent,
    dropticalAPIClient,
)

# --- model parsing (v2 wire is snake_case) ---------------------------------


def test_measurement_updated_event_parses() -> None:
    m = MeasurementUpdatedEvent.model_validate(
        {"measurement_id": 5, "status_changed": True, "frames_inserted_count": 3, "from_frame_id": 1, "to_frame_id": 3, "measurement": {"type": "single", "status": "in_progress"}}
    )
    assert m.measurement_id == 5
    assert m.status_changed is True
    assert m.frames_inserted_count == 3
    assert m.measurement is not None and m.measurement.status == "in_progress"


def test_export_progress_event() -> None:
    m = ExportProgressEvent.model_validate({"id": 3, "status": "complete", "progress": 100, "format": "csv", "download_url": "/storage/exports/3.zip"})
    assert m.id == 3
    assert m.status == "complete"
    assert m.download_url == "/storage/exports/3.zip"


def test_presets_changed_event() -> None:
    m = PresetsChangedEvent.model_validate({"action": "created", "preset_id": 7, "name": "My Preset", "version": 1, "timestamp": "2024-01-15T10:30:00+00:00"})
    assert m.action == "created"
    assert m.preset_id == 7
    assert m.name == "My Preset"


def test_settings_updated_event() -> None:
    # A notification: only the change set, no values.
    m = SettingsUpdatedEvent.model_validate({"changed_groups": ["camera", "rois"], "changed_keys": ["camera.roi.width"], "timestamp": "t"})
    assert m.changed_groups == ["camera", "rois"]
    assert m.changed_keys == ["camera.roi.width"]


def test_machine_status_event() -> None:
    m = MachineStatusEvent.model_validate({"status": "idle", "mode": "lab", "timestamp": "t"})
    assert m.status == "idle"
    assert m.mode == "lab"


def test_event_models_ignore_unknown_fields_for_forward_compat() -> None:
    # Broadcast events use extra="ignore": a field added by a newer backend must not break parsing.
    m = PresetsChangedEvent.model_validate({"action": "loaded", "preset_id": 1, "some_future_field": 123})
    assert m.action == "loaded"
    assert m.preset_id == 1


# --- BroadcastEvent.typed() dispatch ---------------------------------------


def test_typed_dispatches_known_pairs() -> None:
    assert isinstance(BroadcastEvent("measurement", "updated", {"measurement_id": 1}).typed(), MeasurementUpdatedEvent)
    assert isinstance(BroadcastEvent("exports", "updated", {"id": 1}).typed(), ExportProgressEvent)
    assert isinstance(BroadcastEvent("presets", "changed", {"action": "deleted"}).typed(), PresetsChangedEvent)
    assert isinstance(BroadcastEvent("settings", "updated", {}).typed(), SettingsUpdatedEvent)
    assert isinstance(BroadcastEvent("infos", "changed", {}).typed(), MachineStatusEvent)


def test_typed_returns_none_for_unknown_pair() -> None:
    assert BroadcastEvent("presets", "some-future-event", {}).typed() is None
    assert BroadcastEvent("unknown-channel", "updated", {}).typed() is None


# --- Pusher frame decoding (_dispatch_broadcast) ---------------------------


def test_dispatch_decodes_json_string_payload() -> None:
    # Pusher wraps the payload as a JSON-encoded string in the frame's "data" field.
    received: list[BroadcastEvent] = []
    frame = {"channel": "measurement", "event": "updated", "data": json.dumps({"measurement_id": 9, "status_changed": False})}
    dropticalAPIClient._dispatch_broadcast(frame, received.append)

    assert len(received) == 1
    evt = received[0]
    assert evt.channel == "measurement"
    assert evt.event == "updated"
    assert evt.data["measurement_id"] == 9
    typed = evt.typed()
    assert isinstance(typed, MeasurementUpdatedEvent)
    assert typed.measurement_id == 9


def test_dispatch_accepts_object_payload() -> None:
    received: list[BroadcastEvent] = []
    frame = {"channel": "presets", "event": "changed", "data": {"action": "updated", "preset_id": 4}}
    dropticalAPIClient._dispatch_broadcast(frame, received.append)
    assert len(received) == 1
    assert received[0].data["action"] == "updated"


def test_dispatch_skips_non_json_string_payload() -> None:
    received: list[BroadcastEvent] = []
    dropticalAPIClient._dispatch_broadcast({"channel": "presets", "event": "changed", "data": "{not valid json"}, received.append)
    assert received == []
