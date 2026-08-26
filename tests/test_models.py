"""Backend-free unit tests for the client's model / serialization layer.

These need no running device or backend — they exercise pure parsing, alias/serialization and
the strict (``extra="forbid"``) behavior. Kept standalone so they always run, independent of the
integration tests (which target a live backend via the ``client`` fixture).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from droptical_api_client import Algorithm, FrameFilters, MeasurementFilters, ValueMessage, dropticalAPIClient
from droptical_api_client.models import (
    AllSettings,
    CroppingSettings,
    CsvDataConfig,
    ExportJob,
    GeneralSettings,
    SystemInfo,
)


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


def test_clean_params_expands_a_list_of_objects() -> None:
    """A list of objects goes out as PHP reads it back: `key[0][field]=value`.

    The `key[]=` form used for scalar lists sends the dicts' *key names* as values — the query
    became `parameter_filters[]=key&parameter_filters[]=min` and the API filtered by nothing at
    all, with a 200 and a full result set to show for it.
    """
    cleaned = dropticalAPIClient._clean_params(
        {"feature_filters": [{"feature": 3, "min": 0.3, "max": 0.5}, {"feature": 7, "min": 2}]}
    )

    assert cleaned == {
        "feature_filters[0][feature]": 3,
        "feature_filters[0][min]": 0.3,
        "feature_filters[0][max]": 0.5,
        "feature_filters[1][feature]": 7,
        "feature_filters[1][min]": 2,
    }


def test_clean_params_still_uses_the_bracket_form_for_scalar_lists() -> None:
    cleaned = dropticalAPIClient._clean_params({"status": ["nominal", "warning_plus"], "feature": [1, 2]})

    assert cleaned == {"status[]": ["nominal", "warning_plus"], "feature[]": [1, 2]}


def test_clean_params_drops_empty_fields_of_an_object_entry() -> None:
    # An open-ended range carries one bound; the other must not travel as an empty parameter.
    cleaned = dropticalAPIClient._clean_params({"feature_filters": [{"feature": 3, "min": 0.3, "max": None}]})

    assert cleaned == {"feature_filters[0][feature]": 3, "feature_filters[0][min]": 0.3}


def test_feature_filters_reach_the_query_from_both_filter_models() -> None:
    ranges = [{"feature": 3, "min": 0.3, "max": 0.5}]

    assert FrameFilters(feature_filters=ranges).to_query() == {"feature_filters": ranges}
    assert MeasurementFilters(feature_filters=ranges).to_query() == {"feature_filters": ranges}


def test_cropping_carries_a_z_window_per_view() -> None:
    """API 2.2.0: `hsize` left the wire; each view has its own start and they share a width."""
    cropping = CroppingSettings(zwidth=704, zstart1=400, zstart2=696)

    assert cropping.model_dump(exclude_none=True) == {"zwidth": 704, "zstart1": 400, "zstart2": 696}
    with pytest.raises(PydanticValidationError):
        CroppingSettings(hsize=800)  # type: ignore[call-arg]
    with pytest.raises(PydanticValidationError):
        CroppingSettings(zwidth=200)  # below the 240 minimum


def test_machine_settings_carry_the_trigger_passthrough() -> None:
    settings = GeneralSettings.model_validate({"triggerPassthrough": True})

    assert settings.trigger_passthrough is True
    assert settings.model_dump(by_alias=True, exclude_none=True) == {"triggerPassthrough": True}


def test_system_infos_carry_the_storage_wear() -> None:
    """The device reports `system.wear.ssd`; the models forbid unknown fields, so a missing
    declaration does not degrade — every get_infos() call raises."""
    infos = SystemInfo.model_validate({"status": "idle", "wear": {"ssd": 4}})

    assert infos.wear is not None
    assert infos.wear.ssd == 4


def test_csv_data_config_carries_the_measurement_parameter_flag() -> None:
    """The device returns `data.include_measurement_parameters`; the models forbid unknown fields,
    so a missing declaration makes every get_csv_export_config() raise (as `system.wear.ssd` did)."""
    data = CsvDataConfig.model_validate({"include_header": True, "include_measurement_parameters": False})

    assert data.include_measurement_parameters is False
    # Snake_case on the wire, camelCase still accepted on input.
    assert data.to_dict(exclude_none=True) == {"include_header": True, "include_measurement_parameters": False}
    assert CsvDataConfig.model_validate({"includeMeasurementParameters": True}).include_measurement_parameters is True


def test_system_infos_carry_the_api_version() -> None:
    """The device reports the contract it implements as `system.api_version`; undeclared, the
    strict models would fail every get_infos() call, the way `system.wear.ssd` did."""
    infos = SystemInfo.model_validate({"status": "idle", "apiVersion": "2.2.0"})

    assert infos.api_version == "2.2.0"
    # Absent on a unit older than the field, and that is the answer rather than an error.
    assert SystemInfo.model_validate({"status": "idle"}).api_version is None


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


# ── Algorithm catalogue (GET /algorithms, API 2.2.0) ─────────────────────────

# One entry of the real device response, kept verbatim: the point of these cases is that the
# models accept what the machine actually sends, and `extra="forbid"` turns any drift into a
# failure here rather than at a customer.
AI_ALGORITHM = {
    "key": "AI - Detection",
    "label": "AI - Detection",
    "description": "Segmentation network trained on droplet images.",
    "active": False,
    "camera_types": ["nsxigen2"],
    "fields": {
        "calculation.fixed_threshold": {"state": "irrelevant"},
        "calculation.background_correction": {"state": "editable", "requiredValue": True},
    },
    "roi": {
        "allowed_sizes": [{"width": 160, "height": 160}, {"width": 320, "height": 320}],
        "applies_to": ["processing"],
        "origin_freely_choosable": True,
        "nozzle_tip": {"state": "irrelevant"},
    },
}


def test_algorithm_parses_the_device_shape() -> None:
    algorithm = Algorithm.model_validate(AI_ALGORITHM)

    assert algorithm.key == "AI - Detection"
    assert algorithm.camera_types == ["nsxigen2"]
    # Sizes arrive smallest first and stay in that order — the first one is the fallback the
    # device fills in when the caller sends none.
    assert [(s.width, s.height) for s in algorithm.roi.allowed_sizes] == [(160, 160), (320, 320)]
    assert algorithm.roi.applies_to == ["processing"]


def test_algorithm_reads_the_camel_cased_required_value() -> None:
    # `requiredValue` is the one camelCase key inside an otherwise snake_case payload; reading
    # it as `required_value` only works through the explicit alias.
    fields = Algorithm.model_validate(AI_ALGORITHM).fields

    assert fields["calculation.background_correction"].required_value is True
    assert fields["calculation.fixed_threshold"].state == "irrelevant"
    assert fields["calculation.fixed_threshold"].required_value is None


def test_algorithm_keeps_the_three_region_states_apart() -> None:
    # None, [] and a list mean three different things, and collapsing any two of them would
    # make an unusable algorithm look selectable.
    free = Algorithm.model_validate({"key": "Fixed Threshold", "roi": {"allowed_sizes": None}})
    unpublished = Algorithm.model_validate({"key": "Pending", "roi": {"allowed_sizes": []}})

    assert free.roi.allowed_sizes is None
    assert unpublished.roi.allowed_sizes == []


def test_algorithm_forbids_an_unknown_field() -> None:
    # A key this client does not know means the device is ahead of it; failing loudly is the
    # contract (see BaseApiModel).
    with pytest.raises(PydanticValidationError):
        Algorithm.model_validate({**AI_ALGORITHM, "unexpected": 1})


def test_export_job_reads_an_unfiltered_bag_from_either_json_type() -> None:
    """Devices built before the object type was pinned send ``"filters": []``.

    The contract types the field as an object, so both spellings must land as an empty
    dict -- otherwise listing jobs on a released device raises instead of parsing.
    """
    assert ExportJob(id=1, filters=[]).filters == {}
    assert ExportJob(id=1, filters={}).filters == {}
    assert ExportJob(id=1, filters={"measurement_id": 7}).filters == {"measurement_id": 7}
    assert ExportJob(id=1).filters is None

    # A populated list is a real type error, not the empty-array quirk.
    with pytest.raises(PydanticValidationError):
        ExportJob(id=1, filters=[{"measurement_id": 7}])
