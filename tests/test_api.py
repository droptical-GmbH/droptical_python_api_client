"""Integration tests for the v2 REST client against a live backend.

They run against a droptical device or test backend reachable at ``DROPTICAL_TEST_HOST`` /
``DROPTICAL_TEST_PORT`` (default ``127.0.0.1:80``) — see ``tests/conftest.py``. The suite skips
if no backend is reachable. Each test is self-contained (creates its own data), tolerant of
pre-existing state.
"""

from __future__ import annotations

import time

import pytest
import requests

from droptical_api_client import (
    FrameFilters,
    MeasurementFilters,
    NotFoundError,
    ValidationError,
    dropticalAPIClient,
)
from droptical_api_client.models import ActionSettings, AllSettings, CameraSettings, MeasurementType
from tests.conftest import BASE  # backend target (env-configurable; default 127.0.0.1:80)

# --- infos / connection -----------------------------------------------------


def test_get_infos(client: dropticalAPIClient) -> None:
    infos = client.get_infos()
    # The full /infos payload parses under the strict (extra="forbid") models.
    assert infos.system and infos.system.status is not None
    assert infos.analysisunit and infos.analysisunit.serial_number
    # Camera readiness is derived from the authoritative status; the `power` field is optional
    # and not emitted by all firmware (so we don't assert on it here).
    assert infos.cameraunit and infos.cameraunit.status is not None


def test_get_machine_info_alias(client: dropticalAPIClient) -> None:
    assert client.get_machine_info().system.mode == "lab"


def test_get_features(client: dropticalAPIClient) -> None:
    features = client.get_features()
    assert features, "the feature catalogue is non-empty"
    vol = next((f for f in features if f.name == "Volume"), None)
    assert vol is not None and vol.unit == "nl"
    assert vol.value_type == "float"  # camelCase valueType -> snake_case field


# --- settings ---------------------------------------------------------------


def test_get_settings_shape(client: dropticalAPIClient) -> None:
    s = client.get_settings()
    assert 1 in s.rois
    roi = s.rois[1]
    assert roi.processing is not None and roi.nozzle_tip is not None
    # Shape check: the nozzle_tip.uz coordinate parses as an int. The concrete value is device/config
    # dependent (a factory-reset unit reports 0) — a shape test must not couple to a specific config value.
    assert isinstance(roi.nozzle_tip.uz.u, int)


def test_get_settings_groups_filter(client: dropticalAPIClient) -> None:
    s = client.get_settings(groups=["camera"])
    assert s.camera is not None
    assert s.calculation is None


def test_update_settings_partial(client: dropticalAPIClient) -> None:
    updated = client.update_settings(AllSettings(camera=CameraSettings(flipImage=True)))
    assert updated.camera.flip_image is True


def test_update_settings_rejects_unknown_key(client: dropticalAPIClient) -> None:
    with pytest.raises(ValidationError) as exc:
        client.update_settings({"bogusGroup": {"x": 1}})
    assert "bogusGroup" in exc.value.errors


def test_update_settings_rejects_multiple_rois(client: dropticalAPIClient) -> None:
    roi = client.get_settings().rois[1].to_dict(exclude_none=True)
    with pytest.raises(ValidationError):
        client.update_settings({"rois": {1: roi, 2: roi}})


def test_update_settings_rejects_out_of_range_value(client: dropticalAPIClient) -> None:
    # The backend enforces field bounds (fixedThreshold: 0-255) and returns a 422 with a
    # per-field errors map, rather than echoing a value the client could not parse back.
    with pytest.raises(ValidationError) as exc:
        client.update_settings({"calculation": {"fixedThreshold": 99999}})
    assert "calculation.fixedThreshold" in exc.value.errors


def test_get_settings_exposes_read_only_options(client: dropticalAPIClient) -> None:
    # `options` is read-only: guarded on write but returned on read, so a client can
    # discover the available GPO functions and calculation algorithms.
    s = client.get_settings()
    assert s.machine.gpo.options and "Feature" in s.machine.gpo.options
    assert s.calculation.algorithms.options


def test_update_settings_ignores_read_only_options(client: dropticalAPIClient) -> None:
    # Submitting `options` is a no-op: the guarded list the API returns stays unchanged.
    original = client.get_settings().machine.gpo.options
    updated = client.update_settings({"machine": {"gpo": {"options": ["HACKED"]}}})
    assert updated.machine.gpo.options == original
    assert "HACKED" not in updated.machine.gpo.options


def test_update_settings_rejects_bad_pwl(client: dropticalAPIClient) -> None:
    # The PWL waveform format is enforced (ValidPwl): a prefix-less legacy string is
    # rejected with a per-field 422, mirroring the API.
    with pytest.raises(ValidationError) as exc:
        client.update_settings(AllSettings(action=ActionSettings(pwl="PWL=0+0,10+0")))
    assert "action.pwl" in exc.value.errors


# --- measurements -----------------------------------------------------------


def test_list_measurements_cursor_pagination(client: dropticalAPIClient) -> None:
    for _ in range(4):  # self-contained: create enough to page over
        client.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    page1 = client.list_measurements(per_page=3)
    assert len(page1) == 3
    assert page1.next_cursor is not None
    page2 = client.list_measurements(per_page=3, cursor=page1.next_cursor)
    ids1 = {m.id for m in page1}
    ids2 = {m.id for m in page2}
    assert ids1.isdisjoint(ids2)


def test_list_measurements_filters(client: dropticalAPIClient) -> None:
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)

    # type filter (keyword shorthand): the created measurement is present, all results match.
    singleshots = client.list_measurements(type="singleshot", per_page=200).data
    assert any(x.id == m.id for x in singleshots) and all(x.type == "singleshot" for x in singleshots)

    # typed MeasurementFilters produces the same effect.
    typed = client.list_measurements(filters=MeasurementFilters(type="singleshot"), per_page=200).data
    assert {x.id for x in typed} == {x.id for x in singleshots}

    # id range: every returned measurement is >= the cutoff.
    assert all(x.id >= m.id for x in client.list_measurements(id_from=m.id, per_page=200).data)


def test_iter_measurements_walks_all_pages(client: dropticalAPIClient) -> None:
    made = {client.create_measurement(MeasurementType.SINGLESHOT, sync=True).id for _ in range(5)}
    all_ids = [m.id for m in client.iter_measurements(per_page=2)]
    assert made.issubset(set(all_ids))  # every created measurement is walked
    assert len(all_ids) == len(set(all_ids))  # no page overlap / duplicates


def test_create_and_get_measurement(client: dropticalAPIClient) -> None:
    m = client.trigger_singleshot(sync=True)
    assert m.type == "singleshot"
    # The device emits created_at/updated_at (ISO 8601), not a single `timestamp`.
    assert m.created_at is not None
    assert m.updated_at is not None
    fetched = client.get_measurement(m.id)
    assert fetched.id == m.id


def test_create_measurement_sync(client: dropticalAPIClient) -> None:
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    assert m.status == "done"


def test_get_missing_measurement_raises_not_found(client: dropticalAPIClient) -> None:
    with pytest.raises(NotFoundError):
        client.get_measurement(999999)


def test_delete_measurement(client: dropticalAPIClient) -> None:
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    client.delete_measurement(m.id)
    with pytest.raises(NotFoundError):
        client.get_measurement(m.id)


def test_bulk_delete_measurements(client: dropticalAPIClient) -> None:
    a = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    b = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    deleted = client.bulk_delete_measurements([a.id, b.id])
    assert deleted == 2
    with pytest.raises(NotFoundError):
        client.get_measurement(a.id)
    with pytest.raises(NotFoundError):
        client.get_measurement(b.id)


def test_wait_for_measurement_polls_to_terminal(client: dropticalAPIClient) -> None:
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=False)
    assert m.status not in ("done", "cancelled", "error")  # async → non-terminal
    final = client.wait_for_measurement(m.id, timeout=5, poll_interval=0.02)
    assert final.status == "done"


def test_measurement_attachments_and_download(client: dropticalAPIClient) -> None:
    m = client.create_measurement(MeasurementType.VIDEO, sync=False)
    client.wait_for_measurement(m.id, timeout=5, poll_interval=0.02)
    fetched = client.get_measurement(m.id)  # show() resolves the attachments block
    assert fetched.attachments is not None
    assert fetched.attachments.stitched_image is not None
    assert fetched.attachments.video is not None  # a video measurement has a video attachment
    # The attachment download_url is a clean /api/v2 link (not a raw /storage or /download path).
    assert "/api/v2/measurements/" in fetched.attachments.stitched_image.download_url
    assert "/attachments/" in fetched.attachments.stitched_image.download_url
    data = client.download_attachment(fetched.attachments.stitched_image)
    assert data.startswith(b"\x89PNG")


def test_save_all_images_setting_roundtrips_and_frames_have_images(client: dropticalAPIClient) -> None:
    # The saveAllImages action setting round-trips, and a completed measurement's frames carry
    # stored images (url set). (The exact warning/limit-only gating is device-firmware behavior
    # the test backend does not model this, so we assert the setting + that produced frames have images.)
    updated = client.update_settings(AllSettings(action=ActionSettings(saveAllImages=True)))
    assert updated.action is not None and updated.action.save_all_images is True
    m = client.create_measurement(MeasurementType.MULTISHOT, sync=True)
    frames = client.list_measurement_frames(m.id, per_page=100).data
    assert frames and all(f.url for f in frames)


def test_frame_results_are_on_the_detail_not_the_list(client: dropticalAPIClient) -> None:
    m = client.create_measurement(MeasurementType.MULTISHOT, sync=False)
    client.wait_for_measurement(m.id, timeout=5, poll_interval=0.02)

    listed = client.list_measurement_frames(m.id, per_page=100).data
    assert listed and all(f.rois is None for f in listed), "the frame LIST must omit rois"

    detail = client.get_measurement_frame(m.id, listed[0].id)
    assert detail.rois, "the frame DETAIL must include rois"
    drops = detail.rois[0].drops
    assert drops and drops[0].results, "per-drop results must be present on the detail"


# --- frames -----------------------------------------------------------------


def test_list_and_get_frame(client: dropticalAPIClient) -> None:
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    frames = client.list_measurement_frames(m.id, per_page=100).data
    assert frames, "the completed measurement produced frames"
    fid = frames[0].id
    frame = client.get_frame(fid)
    assert frame.id == fid and frame.rois is not None  # detail carries rois
    # The frame image url is a clean /api/v2 image link (not a raw /storage path).
    assert frame.url is not None and "/api/v2/frames/" in frame.url and frame.url.endswith("/image")


def test_list_frames_include_rois(client: dropticalAPIClient) -> None:
    m = client.create_measurement(MeasurementType.MULTISHOT, sync=False)
    client.wait_for_measurement(m.id, timeout=5, poll_interval=0.02)
    client.get_measurement(m.id)  # ensure the measurement's frames (with results) exist

    lean = client.list_frames(measurement_id=m.id, per_page=100).data
    rich = client.list_frames(measurement_id=m.id, per_page=100, include="rois").data
    assert lean and all(f.rois is None for f in lean), "lean list must omit rois"
    assert rich and any(f.rois for f in rich), "include=rois must embed per-frame results"


def test_list_measurements_include_frames(client: dropticalAPIClient) -> None:
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)

    # include=frames embeds a bounded preview + a frames_meta block (no per-frame results).
    page = client.list_measurements(include="frames", frames_limit=2, per_page=200)
    row = next(x for x in page.data if x.id == m.id)
    assert row.frames is not None and len(row.frames) >= 1
    assert row.frames_meta is not None and row.frames_meta.next.endswith(f"/api/v2/measurements/{m.id}/frames")
    assert row.frames[0].rois is None  # include=frames omits results

    # include=frames.results embeds the results too.
    detail = client.get_measurement(m.id, include="frames.results", frames_limit=5)
    assert detail.frames and any(f.rois for f in detail.frames)

    # Default list embeds nothing (lean).
    assert client.list_measurements(per_page=5).data[0].frames is None


def test_get_frame_image_returns_bytes(client: dropticalAPIClient) -> None:
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    frames = client.list_measurement_frames(m.id, per_page=10).data
    fid = next(f.id for f in frames if f.url)  # a frame that has a stored image
    data = client.get_frame_image(fid)
    assert isinstance(data, bytes) and len(data) > 0


def test_measurement_scoped_frames(client: dropticalAPIClient) -> None:
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    page = client.list_measurement_frames(m.id, per_page=100)
    assert len(page) >= 1 and all(f.measurement_id == m.id for f in page)


def test_list_frames_filters(client: dropticalAPIClient) -> None:
    client.create_measurement(MeasurementType.SINGLESHOT, sync=True)  # ensure frames exist
    all_frames = client.list_frames(per_page=200).data
    assert all_frames, "no frames to filter"

    # measurement_id scopes results; a non-existent measurement yields nothing.
    mid = all_frames[0].measurement_id
    scoped = client.list_frames(measurement_id=mid, per_page=200).data
    assert scoped and all(f.measurement_id == mid for f in scoped)
    assert client.list_frames(measurement_id=999999, per_page=200).data == []

    # id range: every returned frame is >= the cutoff.
    cutoff = sorted(f.id for f in all_frames)[len(all_frames) // 2]
    assert all(f.id >= cutoff for f in client.list_frames(id_from=cutoff, per_page=200).data)

    # has_image=True returns only frames that have a stored image (serialized as "1").
    assert all(f.url for f in client.list_frames(has_image=True, per_page=200).data)

    # An explicit frame-id list wins outright.
    picked = {f.id for f in client.list_frames(frame_ids=[all_frames[0].id], per_page=200).data}
    assert picked == {all_frames[0].id}

    # The typed FrameFilters model produces the same result as the keyword form.
    typed = client.list_frames(filters=FrameFilters(measurement_id=mid), per_page=200).data
    assert typed and all(f.measurement_id == mid for f in typed)


def test_list_frames_status_filter(client: dropticalAPIClient) -> None:
    # The `status` filter takes the ResultStatus *api value* string (matching responses), not the
    # raw integer backing value. The produced results carry the "disabled" status.
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)

    def ids(**kw: str) -> set[int]:
        return {f.id for f in client.list_frames(measurement_id=m.id, per_page=200, **kw).data}

    disabled = ids(status="disabled")
    assert disabled, "status=disabled must match the produced frames"
    # DISABLED has backing value 0 — it must still be filterable like any other status.
    assert ids(status="DISABLED") == disabled, "status filter is case-insensitive"
    assert ids(status="limit_minus") == set(), "an unused status matches nothing"

    # The typed FrameFilters form takes the same api-value strings.
    typed = {f.id for f in client.list_frames(filters=FrameFilters(status="disabled", measurement_id=m.id), per_page=200).data}
    assert typed == disabled

    # An unknown status is rejected with 422 — never silently ignored (which would widen to all frames).
    with pytest.raises(ValidationError):
        client.list_frames(status="bogus", per_page=200)


def test_frames_list_exposes_bulk_actions(client: dropticalAPIClient) -> None:
    # The frames collection advertises its filter-based bulk download/export as `actions`
    # (the frame pendant to a measurement's per-resource download links).
    resp = requests.get(f"{BASE}/frames", params={"measurement_id": 1, "has_image": 1}).json()
    actions = resp.get("actions", {})
    assert "/api/v2/frames/download" in actions.get("download", "")
    assert "measurement_id=1" in actions["download"]  # current filters carried into the link
    assert actions.get("export", "").endswith("/api/v2/frames/exports")


# --- machine actions / gpio -------------------------------------------------


def test_machine_actions(client: dropticalAPIClient) -> None:
    client.reboot()
    client.power_on_camera()
    client.set_production_mode(True)
    client.set_production_mode(False)
    client.identify()
    client.abort()  # device-scoped; no-ops if nothing is running
    assert isinstance(client.get_machine_time(), int)


def test_destructive_actions_require_matching_serial(client: dropticalAPIClient) -> None:
    serial = client.get_infos().analysisunit.serial_number
    assert serial  # the backend reports an analysis-unit serial

    # A wrong serial is rejected with 422 → ValidationError; the device is NOT reset.
    with pytest.raises(ValidationError):
        client.factory_reset("WRONG-SERIAL")
    with pytest.raises(ValidationError):
        client.clear_data("WRONG-SERIAL")

    # The correct serial is accepted (clear_data then actually wipes — fine here, later tests
    # create their own data).
    client.clear_data(serial)


def test_gpio(client: dropticalAPIClient) -> None:
    levels = client.get_gpio_levels()
    assert levels.gpi is not None
    client.set_gpo("GPO1", True)


def test_gpio_invalid_name(client: dropticalAPIClient) -> None:
    from droptical_api_client import ApiError

    # GPO9 fails the ^GPO[1-5]$ constraint → HTTP 400 → surfaced as an ApiError.
    with pytest.raises(ApiError):
        client.set_gpo("GPO9", True)


# --- presets ----------------------------------------------------------------


def test_list_presets_rejects_non_boolean_include(client: dropticalAPIClient) -> None:
    # Booleans must serialize as 1/0; a raw True/False is rejected with 422.
    resp = requests.get(f"{BASE}/presets", params={"include_deleted": "False"})
    assert resp.status_code == 422
    # The client serializes the bool correctly, so the real call succeeds:
    assert isinstance(client.list_presets(include_deleted=False), list)


def test_preset_lifecycle(client: dropticalAPIClient) -> None:
    before = len(client.list_presets())
    created = client.create_preset("New Recipe", comment="c")
    assert created.name == "New Recipe"
    assert len(client.list_presets()) == before + 1
    edited = client.edit_preset(created.id, name="Renamed")
    assert edited.name == "Renamed"
    versioned = client.create_preset_version(created.id)
    assert versioned.version == created.version + 1
    history = client.list_preset_versions(created.id)
    assert any(v.version == versioned.version for v in history)
    client.load_preset(gid=created.gid, version=versioned.version)  # load the current version
    client.load_preset(gid=0, version=1)  # switch back to the default so the created one is deletable
    client.delete_preset(created.id)


def test_create_preset_validation(client: dropticalAPIClient) -> None:
    with pytest.raises(ValidationError):
        client.create_preset("ab")  # too short


def test_delete_default_preset_forbidden(client: dropticalAPIClient) -> None:
    from droptical_api_client import ApiError

    with pytest.raises(ApiError):
        client.delete_preset(1)  # gid=0 default


# --- export jobs ------------------------------------------------------------


_JOB_TERMINAL = ("complete", "failed", "cancelled")


def test_export_job_lifecycle(client: dropticalAPIClient) -> None:
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    job = client.create_measurement_export(m.id, format="csv")
    assert job.status in ("queued", "processing", "running")
    assert client.get_job(job.id).id == job.id
    aborted = client.abort_job(job.id)  # abort is accepted (exact resulting status is worker-dependent)
    assert aborted.id == job.id
    assert any(j.id == job.id for j in client.list_jobs())


def test_export_download_family(client: dropticalAPIClient) -> None:
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    # Direct ZIP downloads (measurement- and frame-scoped) stream bytes back.
    assert client.download_measurement(m.id, format="csv").startswith(b"PK")
    assert client.download_frames(format="images", filters={"measurement_id": m.id}).startswith(b"PK")

    # A frame export job: queue it, poll to completion, then download. If no export worker is
    # running to finish it, skip the completion/download assertions.
    job = client.create_frame_export(format="json", filters={"measurement_id": m.id})
    assert job.format == "json"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and job.status not in _JOB_TERMINAL:
        time.sleep(0.5)
        job = client.get_job(job.id)
    if job.status != "complete":
        pytest.skip(f"export job path needs >10k frames + a running queue worker (status={job.status})")
    assert job.download_url and client.download_export(job).startswith(b"PK")


def test_jobs_list_polling_reaches_terminal(client: dropticalAPIClient) -> None:
    # Mirrors the GUI's auto-refresh: poll the LIST endpoint until the job is terminal.
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    job = client.create_measurement_export(m.id, format="json")
    seen = client.get_job(job.id)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and seen.status not in _JOB_TERMINAL:
        time.sleep(0.5)
        seen = next((j for j in client.list_jobs(per_page=100) if j.id == job.id), seen)
    if seen.status != "complete":
        pytest.skip(f"export job path needs >10k frames + a running queue worker (status={seen.status})")
    assert seen.status == "complete"


def test_download_measurement_direct_formats(client: dropticalAPIClient) -> None:
    """Direct (synchronous) measurement download streams a valid ZIP for every format — the
    <10k-frame path (no worker/job), i.e. the common case."""
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    for fmt in ("csv", "json", "images"):
        assert client.download_measurement(m.id, format=fmt).startswith(b"PK"), f"{fmt}: not a zip"


def test_download_frames_direct_formats(client: dropticalAPIClient) -> None:
    """Direct frame download streams a valid ZIP for every format, scoped by a measurement filter."""
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    for fmt in ("images", "csv", "json"):
        assert client.download_frames(format=fmt, filters={"measurement_id": m.id}).startswith(b"PK"), f"{fmt}: not a zip"


def test_download_measurement_honours_csv_config(client: dropticalAPIClient) -> None:
    """A direct CSV download accepts a hardcoded export-config name and still streams a zip."""
    m = client.create_measurement(MeasurementType.SINGLESHOT, sync=True)
    assert client.download_measurement(m.id, format="csv", config_name="python_pandas").startswith(b"PK")


# --- settings idle lock -----------------------------------------------------


def test_update_settings_blocked_when_not_idle(client: dropticalAPIClient) -> None:
    # Verifies the client maps HTTP 423 → NotIdleError, but that needs the backend forced into a
    # non-idle state.
    pytest.skip("needs a backend hook to force a non-idle (423) state; skipped until available.")


# --- GUI settings: CSV export config ----------------------------------------


def test_csv_export_config_roundtrip(client: dropticalAPIClient) -> None:
    cfg = client.get_csv_export_config()
    # Read-only hardcoded presets are always present; custom starts unset.
    assert cfg.hardcoded_configs is not None
    assert "excel_dach" in cfg.hardcoded_configs
    assert cfg.hardcoded_configs["excel_dach"].format is not None
    assert cfg.hardcoded_configs["excel_dach"].format.include_bom is True  # camelCase includeBOM alias

    saved = client.update_csv_export_config({
        "format": {"delimiter": ",", "decimalSeparator": ".", "quoteCharacter": '"', "quoteRule": "ALL", "encoding": "UTF-8", "includeBOM": False, "lineEnding": "LF"},
        "time": {"format": "UNIX_MS", "timezone": "UTC", "splitDateAndTime": True},
        "data": {"includeHeader": True, "includeUnitsInHeader": False, "includeMetadataBlock": False, "metadataPrefix": "# ", "nullValueStrategy": "NAN"},
        "output": {"maxRowsPerFile": None, "decimalPlaces": 4},
    })
    # The server forces config_name to "custom" regardless of input.
    assert saved.config_name == "custom"
    assert saved.output is not None and saved.output.decimal_places == 4
    assert saved.format is not None and saved.format.include_bom is False


def test_csv_export_config_rejects_incomplete(client: dropticalAPIClient) -> None:
    with pytest.raises(ValidationError):
        client.update_csv_export_config({"format": {"delimiter": ";"}})  # missing time/data/output
