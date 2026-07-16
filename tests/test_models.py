"""Backend-free unit tests for the client's model / serialization layer.

These need no running device or backend — they exercise pure parsing, alias/serialization and
the strict (``extra="forbid"``) behavior. Kept standalone so they always run, independent of the
integration tests (which target a live backend via the ``client`` fixture).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from droptical_api_client import FrameFilters, MeasurementFilters, ValueMessage, dropticalAPIClient
from droptical_api_client.models import AllSettings


def test_measurement_filters_model_serializes_snake_case() -> None:
    q = MeasurementFilters(status="done", type=["singleshot", "video"], id_from=5).to_query()
    assert q == {"status": "done", "type": ["singleshot", "video"], "id_from": 5}


def test_frame_filters_model_serializes_snake_case() -> None:
    q = FrameFilters(measurement_id=7, has_image=True, feature=[1, 2], status="nominal", id_from=100).to_query()
    assert q == {"measurement_id": 7, "has_image": True, "feature": [1, 2], "status": "nominal", "id_from": 100}
    # status takes the ResultStatus api value(s), not the raw integer.
    assert FrameFilters(status=["nominal", "warning_plus"]).to_query() == {"status": ["nominal", "warning_plus"]}
    # extra="allow" keeps the filter bag forward-compatible with future server filters.
    assert FrameFilters(some_future_filter=9).to_query() == {"some_future_filter": 9}


def test_clean_params_serializes_booleans() -> None:
    # Booleans must go out as "1"/"0" (the API's boolean rule rejects "True"/"False").
    cleaned = dropticalAPIClient._clean_params({"a": True, "b": False, "c": 5, "d": None})
    assert cleaned == {"a": "1", "b": "0", "c": 5}


def test_models_forbid_unknown_fields() -> None:
    """extra='forbid': an undocumented key raises instead of being silently dropped, so a device
    that has drifted ahead of the client surfaces loudly (the client is versioned 1:1 with the spec)."""
    # A documented alias still parses (populate_by_name); an unknown group does not.
    AllSettings.model_validate({"camera": {"flipImage": False}})
    with pytest.raises(PydanticValidationError):
        AllSettings.model_validate({"camera": {"flipImage": False}, "unknown_group": {}})


def test_value_message_tolerates_fuller_measurement_document() -> None:
    """The value stream can push more than the lean per-frame results: a shot completed while
    streaming yields a fuller measurement document (extra top-level keys + a per-frame image
    path). ValueMessage must parse it (extra='ignore') so one such message can't kill the
    value-listener thread — the extra keys are dropped, the core results stay intact."""
    msg = {
        "id": 12, "type": 3, "status": 2, "frame_count": 1, "timestamp": 123,
        # measurement-level extras the lean value model does not declare
        "progress": 100, "attachments": [], "preset": {"gid": 0, "version": 1}, "error": "",
        "frames": [{
            "index": 0, "timestamp": 123,
            "path": "./images/regular/img.png",  # per-frame extra (stored image)
            "rois": [{"index": 1, "results": [{"feature_id": 7, "value": 1.2, "status": 0}], "drops": []}],
        }],
    }

    vm = ValueMessage.model_validate(msg)

    assert not hasattr(vm, "progress")  # extra dropped, not retained
    assert len(vm.frames) == 1
    assert not hasattr(vm.frames[0], "path")  # per-frame extra dropped
    assert vm.frames[0].rois[0].results[0].feature_id == 7  # core results intact
