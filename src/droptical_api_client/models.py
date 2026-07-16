from __future__ import annotations

from enum import Enum
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# =============================================================================
# Base
# =============================================================================


class BaseApiModel(BaseModel):
    """Base model for all v2 API data classes.

    Field names are Pythonic ``snake_case`` and the v2 wire format is ``snake_case`` too, so
    ``to_dict()`` serializes by field name. The camelCase aliases (generator + explicit) are kept
    only so the client still *accepts* camelCase input (``populate_by_name``), which keeps it
    tolerant of older payloads; they are no longer used on output.

    ``extra="forbid"``: unknown keys raise instead of being silently dropped. The API returns a
    stable, typed contract, so an unexpected key means this client is out of date with the device;
    ``extra="forbid"`` makes that fail loudly instead of silently dropping data. A spec change
    therefore ships as a client update. (The query-filter bags ``FrameFilters``/``MeasurementFilters``
    keep ``extra="allow"`` on purpose — they are client-supplied inputs, not device responses.)
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        populate_by_name=True,
    )

    def to_dict(self, **kwargs: Any) -> dict[str, Any]:
        """Serialize to a dict using snake_case field names (the v2 wire format)."""
        return self.model_dump(by_alias=False, **kwargs)


# =============================================================================
# Enums (values mirror the v2 API — lowercase for responses unless noted)
# =============================================================================


class MeasurementType(str, Enum):
    NONE = "none"
    CONTINUOUS_SINGLESHOT = "continuous_singleshot"
    PRODUCTION = "production"
    SINGLESHOT = "singleshot"
    MULTISHOT = "multishot"
    VIDEO = "video"


class MeasurementStatus(str, Enum):
    """Lifecycle status of a measurement (matches the value the API returns)."""

    NONE = "none"
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"
    NO_TRIGGER_RECEIVED = "no_trigger_received"
    ERROR = "error"

    @property
    def is_terminal(self) -> bool:
        """True once the measurement has stopped progressing (no further polling).

        ``NO_TRIGGER_RECEIVED`` is intentionally *not* terminal: the machine keeps awaiting its
        trigger (it does not give up), so a poller should keep waiting until DONE/CANCELLED/ERROR
        or its own timeout. Mirrors the API's terminal status set."""
        return self in {
            MeasurementStatus.DONE,
            MeasurementStatus.CANCELLED,
            MeasurementStatus.ERROR,
        }

    @property
    def is_success(self) -> bool:
        """True only when the measurement finished successfully (results available)."""
        return self is MeasurementStatus.DONE


# Terminal status strings, for tolerant checks against the raw ``Measurement.status``
# string without raising on values a future device firmware might add.
TERMINAL_MEASUREMENT_STATUSES: frozenset[str] = frozenset(s.value for s in MeasurementStatus if s.is_terminal)


class ExportJobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    RUNNING = "running"
    FINALISING = "finalising"
    ABORTING = "aborting"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DELETED = "deleted"


class ResultStatus(int, Enum):
    """ROI/drop result status. Responses carry the lowercase api value (e.g. ``"nominal"``);
    the ``GET /frames`` ``status`` filter takes those same strings (see ``api_value``)."""

    @property
    def api_value(self) -> str:
        """The lowercase string form used in responses and the ``status`` filter."""
        return self.name.lower()

    DISABLED = 0
    LIMIT_MINUS = 1
    WARNING_MINUS = 2
    NOMINAL = 3
    WARNING_PLUS = 4
    LIMIT_PLUS = 5


class AnalysisUnitStatus(str, Enum):
    NONE = "none"
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"


class AnalysisUnitMode(str, Enum):
    NONE = "none"
    LAB = "lab"
    PRODUCTION = "production"
    STREAMING = "streaming"


class CameraUnitType(str, Enum):
    NONE = "none"
    US = "us"
    NSXD = "nsxd"
    NSXI = "nsxi"
    NEOSCALE = "neoscale"


class TriggerEdge(str, Enum):
    """Machine-facing trigger edge (settings payload — UPPERCASE, not lowercased)."""

    FALLING_EDGE = "FALLING_EDGE"
    RISING_EDGE = "RISING_EDGE"


# =============================================================================
# Settings — ROI tree
# =============================================================================


class RoiUzDimension(BaseApiModel):
    WIDTH_MIN: ClassVar[int] = 10
    HEIGHT_MIN: ClassVar[int] = 10

    start_u: int | None = Field(None, ge=0)
    start_z: int | None = Field(None, ge=0)
    width: int | None = Field(None, ge=WIDTH_MIN)
    height: int | None = Field(None, ge=HEIGHT_MIN)

    @classmethod
    def default(cls) -> RoiUzDimension:
        return cls(start_u=0, start_z=0, width=cls.WIDTH_MIN, height=cls.HEIGHT_MIN)


class RoiVzDimension(BaseApiModel):
    WIDTH_MIN: ClassVar[int] = 10
    HEIGHT_MIN: ClassVar[int] = 10

    start_v: int | None = Field(None, ge=0)
    start_z: int | None = Field(None, ge=0)
    width: int | None = Field(None, ge=WIDTH_MIN)
    height: int | None = Field(None, ge=HEIGHT_MIN)

    @classmethod
    def default(cls) -> RoiVzDimension:
        return cls(start_v=0, start_z=0, width=cls.WIDTH_MIN, height=cls.HEIGHT_MIN)


class RoiSettings(BaseApiModel):
    """One ROI role (processing / nozzle / exclusion): a rectangle per plane."""

    uz: RoiUzDimension | None = None
    vz: RoiVzDimension | None = None

    @classmethod
    def default(cls) -> RoiSettings:
        return cls(uz=RoiUzDimension.default(), vz=RoiVzDimension.default())


class NozzleTipUz(BaseApiModel):
    u: int | None = Field(None, ge=0, le=1400)
    z: int | None = Field(None, ge=0, le=1600)

    @classmethod
    def default(cls) -> NozzleTipUz:
        return cls(u=0, z=0)


class NozzleTipVz(BaseApiModel):
    v: int | None = Field(None, ge=0, le=1400)
    z: int | None = Field(None, ge=0, le=1600)

    @classmethod
    def default(cls) -> NozzleTipVz:
        return cls(v=0, z=0)


class NozzleTipSettings(BaseApiModel):
    """Point-based nozzle-tip position (not a rectangle)."""

    U_MIN: ClassVar[int] = 0
    U_MAX: ClassVar[int] = 1400
    V_MIN: ClassVar[int] = 0
    V_MAX: ClassVar[int] = 1400
    Z_MIN: ClassVar[int] = 0
    Z_MAX: ClassVar[int] = 1600

    uz: NozzleTipUz | None = None
    vz: NozzleTipVz | None = None

    @classmethod
    def default(cls) -> NozzleTipSettings:
        return cls(uz=NozzleTipUz.default(), vz=NozzleTipVz.default())


class RoiSet(BaseApiModel):
    """One complete region of interest: the three rectangles + the nozzle-tip point.

    Elements of the 1-based ``rois`` map."""

    processing: RoiSettings | None = None
    nozzle: RoiSettings | None = None
    exclusion: RoiSettings | None = None
    nozzle_tip: NozzleTipSettings | None = Field(None, alias="nozzleTip")

    @classmethod
    def default(cls) -> RoiSet:
        return cls(
            processing=RoiSettings.default(),
            nozzle=RoiSettings.default(),
            exclusion=RoiSettings.default(),
            nozzle_tip=NozzleTipSettings.default(),
        )


# =============================================================================
# Settings — camera / calculation / export / action / machine / features
# =============================================================================


class ExposureSettings(BaseApiModel):
    EXPOSURE_TIME_MIN: ClassVar[float] = 0.0234375
    EXPOSURE_TIME_MAX: ClassVar[float] = 5.0

    uz: float | None = Field(None, ge=EXPOSURE_TIME_MIN, le=EXPOSURE_TIME_MAX)
    vz: float | None = Field(None, ge=EXPOSURE_TIME_MIN, le=EXPOSURE_TIME_MAX)


class CroppingSettings(BaseApiModel):
    H_SIZE_MIN: ClassVar[int] = 120
    H_SIZE_MAX: ClassVar[int] = 800
    V_SIZE_MIN: ClassVar[int] = 150
    V_SIZE_MAX: ClassVar[int] = 1400
    V_START_MIN: ClassVar[int] = 0
    V_START_MAX: ClassVar[int] = 1400

    hsize: int | None = Field(None, ge=H_SIZE_MIN, le=H_SIZE_MAX)
    vsize1: int | None = Field(None, ge=V_SIZE_MIN, le=V_SIZE_MAX)
    vsize2: int | None = Field(None, ge=V_SIZE_MIN, le=V_SIZE_MAX)
    vstart1: int | None = Field(None, ge=V_START_MIN, le=V_START_MAX)
    vstart2: int | None = Field(None, ge=V_START_MIN, le=V_START_MAX)


class CameraSettings(BaseApiModel):
    exposure_time: ExposureSettings | None = Field(None, alias="exposureTime")
    cropping: CroppingSettings | None = None
    flip_image: bool | None = Field(None, alias="flipImage")


class AlgorithmSettings(BaseApiModel):
    active: str | None = None
    options: list[str] | None = None  # read-only: returned on read, ignored on write


class CalculationSettings(BaseApiModel):
    DENSITY_MIN: ClassVar[float] = 0.0
    DENSITY_MAX: ClassVar[float] = 20.0
    FIXED_THRESHOLD_MIN: ClassVar[int] = 0
    FIXED_THRESHOLD_MAX: ClassVar[int] = 255
    DISPENSING_GAP_MIN: ClassVar[float] = 0.0
    DISPENSING_GAP_MAX: ClassVar[float] = 1_000_000.0

    include_partial_drops: bool | None = Field(None, alias="includePartialDrops")
    background_correction: bool | None = Field(None, alias="backgroundCorrection")
    density: float | None = Field(None, ge=DENSITY_MIN, le=DENSITY_MAX)
    fixed_threshold: int | None = Field(None, ge=FIXED_THRESHOLD_MIN, le=FIXED_THRESHOLD_MAX, alias="fixedThreshold")
    dispensing_gap: float | None = Field(None, ge=DISPENSING_GAP_MIN, le=DISPENSING_GAP_MAX, alias="dispensingGap")
    algorithms: AlgorithmSettings | None = None


class ExtraInfoSettings(BaseApiModel):
    contours: bool | None = None
    drop_markings: bool | None = Field(None, alias="dropMarkings")
    measurement_information: bool | None = Field(None, alias="measurementInformation")
    reference_flight_axis: bool | None = Field(None, alias="referenceFlightAxis")
    ruler: bool | None = None


class ExportSettings(BaseApiModel):
    extra_info: ExtraInfoSettings | None = Field(None, alias="extraInfo")
    save_warning_image: bool | None = Field(None, alias="saveWarningImage")
    save_limit_image: bool | None = Field(None, alias="saveLimitImage")


class MeasurementParameterSettings(BaseApiModel):
    parameter1: str | None = None
    parameter2: str | None = None
    parameter3: str | None = None


class ActionSettings(BaseApiModel):
    FLASH_DELAY_MIN: ClassVar[int] = 20
    FLASH_DELAY_MAX: ClassVar[int] = 8100
    FLASH_DELAY2_MIN: ClassVar[int] = 30
    FLASH_DELAY2_MAX: ClassVar[int] = 8110
    START_TIME_MIN: ClassVar[int] = 20
    START_TIME_MAX: ClassVar[int] = 8100
    END_TIME_MIN: ClassVar[int] = 21
    END_TIME_MAX: ClassVar[int] = 8100
    TIME_INCREMENT_MIN: ClassVar[int] = 1
    TIME_INCREMENT_MAX: ClassVar[int] = 1000
    EXIT_DELAY_MIN: ClassVar[int] = 0
    EXIT_DELAY_MAX: ClassVar[int] = 8100
    IMAGE_COUNT_MIN: ClassVar[int] = 2
    IMAGE_COUNT_MAX: ClassVar[int] = 8081
    STITCH_COUNT_MIN: ClassVar[int] = 2
    STITCH_COUNT_MAX: ClassVar[int] = 30
    TRIGGER_COUNT_MIN: ClassVar[int] = 2
    TRIGGER_COUNT_MAX: ClassVar[int] = 10_000_000
    ANALOG_VOLTAGE_MIN: ClassVar[float] = 0.0
    ANALOG_VOLTAGE_MAX: ClassVar[float] = 4.0
    FPS_MIN: ClassVar[int] = 1
    FPS_MAX: ClassVar[int] = 120
    FREQUENCY_MIN: ClassVar[float] = 0.1
    FREQUENCY_MAX: ClassVar[float] = 2000.0
    PWL_MAX_LENGTH: ClassVar[int] = 255

    use_external_trigger: bool | None = Field(None, alias="useExternalTrigger")
    output_trigger_signal: bool | None = Field(None, alias="outputTriggerSignal")
    use_constant_mode: bool | None = Field(None, alias="useConstantMode")
    capture_mode_on: bool | None = Field(None, alias="captureModeOn")
    save_all_images: bool | None = Field(None, alias="saveAllImages")
    double_snap: bool | None = Field(None, alias="doubleSnap")
    flash_delay: int | None = Field(None, ge=FLASH_DELAY_MIN, le=FLASH_DELAY_MAX, alias="flashDelay")
    flash_delay2: int | None = Field(None, ge=FLASH_DELAY2_MIN, le=FLASH_DELAY2_MAX, alias="flashDelay2")
    start_time: int | None = Field(None, ge=START_TIME_MIN, le=START_TIME_MAX, alias="startTime")
    end_time: int | None = Field(None, ge=END_TIME_MIN, le=END_TIME_MAX, alias="endTime")
    time_increment: int | None = Field(None, ge=TIME_INCREMENT_MIN, le=TIME_INCREMENT_MAX, alias="timeIncrement")
    exit_delay: int | None = Field(None, ge=EXIT_DELAY_MIN, le=EXIT_DELAY_MAX, alias="exitDelay")
    image_count: int | None = Field(None, ge=IMAGE_COUNT_MIN, le=IMAGE_COUNT_MAX, alias="imageCount")
    stitch_count: int | None = Field(None, ge=STITCH_COUNT_MIN, le=STITCH_COUNT_MAX, alias="stitchCount")
    trigger_count: int | None = Field(None, ge=TRIGGER_COUNT_MIN, le=TRIGGER_COUNT_MAX, alias="triggerCount")
    a0: float | None = Field(None, ge=ANALOG_VOLTAGE_MIN, le=ANALOG_VOLTAGE_MAX)
    fps: int | None = Field(None, ge=FPS_MIN, le=FPS_MAX)
    frequency: float | None = Field(None, ge=FREQUENCY_MIN, le=FREQUENCY_MAX)
    pwl: str | None = Field(None, max_length=PWL_MAX_LENGTH)
    parameters: MeasurementParameterSettings | None = None


class GpiSetting(BaseApiModel):
    function: str | None = None
    inverted: bool | None = None


class GpoSetting(BaseApiModel):
    function: str | None = None
    inverted: bool | None = None
    features: dict[int, Any] | None = None


class GPISettings(BaseApiModel):
    options: list[str] | None = None  # read-only: returned on read, ignored on write
    gpis: dict[str, GpiSetting] | None = None


class GPOSettings(BaseApiModel):
    options: list[str] | None = None  # read-only: returned on read, ignored on write
    gpos: dict[str, GpoSetting] | None = None


class GeneralSettings(BaseApiModel):
    """The ``machine`` settings group."""

    gpi: GPISettings | None = None
    gpo: GPOSettings | None = None
    output_trigger_edge: TriggerEdge | None = Field(None, alias="outputTriggerEdge")
    input_trigger_edge: TriggerEdge | None = Field(None, alias="inputTriggerEdge")


class Limits(BaseApiModel):
    error_minus: float | None = Field(None, ge=0, alias="errorMinus")
    warning_minus: float | None = Field(None, ge=0, alias="warningMinus")
    nominal: float | None = Field(None, ge=0)
    warning_plus: float | None = Field(None, ge=0, alias="warningPlus")
    error_plus: float | None = Field(None, ge=0, alias="errorPlus")


class FeatureSettings(BaseApiModel):
    """A feature's settings (item of the ``features`` map). ``enabled``/``use_limits``/``limits``
    are writable; the remaining fields are read-only meta the machine emits (round-tripped on
    write, where the machine strips the non-writable ones)."""

    enabled: bool | None = None
    use_limits: bool | None = Field(None, alias="useLimits")
    limits: Limits | None = None
    # Read-only meta (id → the map key; name/unit/…); populated on read, ignored by the machine on write.
    id: int | None = None
    name: str | None = None
    unit: str | None = None
    aggregation_type: str | None = Field(None, alias="aggregationType")  # none | sum | avg
    entity_type: str | None = Field(None, alias="entityType")  # none | drop | roi
    value_type: str | None = Field(None, alias="valueType")  # none | float | integer
    min: float | None = None
    max: float | None = None
    step: float | None = None
    group: str | None = None


class AllSettings(BaseApiModel):
    """The full settings payload (``GET``/``PATCH /settings``).

    ``rois`` and ``features`` are 1-based maps (the key is the identity)."""

    camera: CameraSettings | None = None
    calculation: CalculationSettings | None = None
    export: ExportSettings | None = None
    action: ActionSettings | None = None
    machine: GeneralSettings | None = None
    rois: dict[int, RoiSet] | None = None
    features: dict[int, FeatureSettings] | None = None

    @classmethod
    def default(cls) -> AllSettings:
        return cls(
            camera=CameraSettings(exposure_time=ExposureSettings(uz=1.0), cropping=CroppingSettings(hsize=800, vsize1=700, vstart1=0), flip_image=False),
            calculation=CalculationSettings(include_partial_drops=False, background_correction=True, density=1.2, fixed_threshold=127, dispensing_gap=12.3),
            export=ExportSettings(
                extra_info=ExtraInfoSettings(contours=False, drop_markings=False, measurement_information=False, reference_flight_axis=False, ruler=False),
                save_warning_image=False,
                save_limit_image=False,
            ),
            action=ActionSettings(use_external_trigger=False, output_trigger_signal=False, use_constant_mode=False, capture_mode_on=False, save_all_images=False, double_snap=False),
            machine=GeneralSettings(output_trigger_edge=TriggerEdge.FALLING_EDGE, input_trigger_edge=TriggerEdge.RISING_EDGE),
            rois={1: RoiSet.default()},
            features={1: FeatureSettings(enabled=True, use_limits=False, limits=Limits(error_minus=0, warning_minus=1, nominal=5, warning_plus=9, error_plus=10))},
        )


# =============================================================================
# Resources — measurements / frames / exports / presets
# =============================================================================


class MeasurementParameter(BaseApiModel):
    key: str
    value: Any
    postfix: str | None = None


class Attachment(BaseApiModel):
    """A downloadable measurement attachment (stitched image, video, export).

    ``download_url`` is a full ``/api/v2`` attachment link — fetch it with
    :meth:`dropticalAPIClient.download_attachment`.
    """

    id: int
    download_url: str | None = None


class MeasurementAttachments(BaseApiModel):
    """Attachments block of a measurement (only populated by ``GET /measurements/{id}``,
    and only once the measurement has finished producing them)."""

    video: Attachment | None = None
    stitched_image: Attachment | None = None
    csv_export: Attachment | None = None
    json_export: Attachment | None = None


class MeasurementPreset(BaseApiModel):
    """The preset a measurement was taken with (embedded in :class:`Measurement`; only the
    id + display name, distinct from the full :class:`Preset` resource)."""

    id: int | None = None
    name: str | None = None


class FramesMeta(BaseApiModel):
    """Metadata for the bounded frames preview embedded via ``include=frames[.results]``."""

    embedded: int | None = None
    truncated: bool | None = None
    next: str | None = None  # link to the full (paginated) frame set


class Measurement(BaseApiModel):
    id: int
    type: str
    status: str
    progress: int | None = None
    frames_count: int | None = None
    preset: MeasurementPreset | None = None
    parameters: list[MeasurementParameter] | None = None
    attachments: MeasurementAttachments | None = None
    # ISO 8601 timestamps (the device emits snake_case ``created_at``/``updated_at``;
    # there is no single ``timestamp`` field on a measurement).
    created_at: str | None = None
    updated_at: str | None = None
    # Present only when requested via list_measurements(include="frames"[".results"]): a bounded
    # preview of the measurement's frames; frames_meta.next links the full (paginated) set.
    frames: list[MeasurementFrame] | None = None
    frames_meta: FramesMeta | None = None


class FrameResultFeature(BaseApiModel):
    """The feature reference embedded in a :class:`FrameResult` (id → name/unit/value_type)."""

    id: int | None = None
    name: str | None = None
    unit: str | None = None
    value_type: str | None = None  # none | float | integer


class FrameResult(BaseApiModel):
    """A single feature result as returned by the REST frame endpoints
    (``GET /frames/{id}``). Field names are the API's snake_case (e.g. ``feature_id``)."""

    id: int | None = None
    feature_id: int | None = None
    feature: FrameResultFeature | None = None
    value: float | None = None
    status: str | None = None  # ResultStatus api value: disabled|limit_minus|warning_minus|nominal|warning_plus|limit_plus


class FrameDrop(BaseApiModel):
    """A detected drop within a frame ROI (REST frame detail), carrying its own results."""

    id: int | None = None
    index: int | None = None
    results: list[FrameResult] = []


class FrameRoi(BaseApiModel):
    """One ROI of a frame's detail (``GET /frames/{id}``): ROI-level results plus per-drop results."""

    id: int | None = None
    index: int | None = None
    results: list[FrameResult] = []
    drops: list[FrameDrop] = []


class Feature(BaseApiModel):
    """A measurement-feature definition (id → name/unit/type). Resolves the numeric
    ``featureId`` values carried by the value/image streams into human-readable names
    and units. Fetched via :meth:`dropticalAPIClient.get_features`."""

    id: int
    name: str | None = None
    unit: str | None = None
    value_type: str | None = None
    entity_type: str | None = None


class MeasurementFrame(BaseApiModel):
    """A measurement frame resource (from the REST API). Distinct from the TCP
    stream ``ImageFrame`` (a live image), which lives in ``client.py``."""

    id: int
    measurement_id: int | None = None
    index: int | None = None
    url: str | None = None
    timestamp: str | None = None
    # Present only on the per-frame detail (GET /frames/{id} or ?include=rois); the lean list form omits it.
    rois: list[FrameRoi] | None = None


class FrameFilters(BaseModel):
    """Typed filter set for the frame endpoints (``list_frames`` / ``iter_frames`` and the
    frame exports). Field names match the API's snake_case query parameters.

    Unset fields are omitted from the query; ``extra="allow"`` keeps the client
    forward-compatible with server filters added after this release.
    """

    model_config = ConfigDict(extra="allow")

    id: int | None = None
    id_from: int | None = None
    id_to: int | None = None
    measurement_id: int | None = None
    measurement_id_from: int | None = None
    measurement_id_to: int | None = None
    measurement_ids: list[int] | None = None
    frame_ids: list[int] | None = None
    index: int | None = None
    has_image: bool | None = None
    date_from: str | None = None  # "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
    date_to: str | None = None
    feature: int | list[int] | None = None  # feature id(s) a ROI/drop result must match
    status: str | list[str] | None = None  # ResultStatus api value(s), e.g. "nominal", "warning_minus"

    def to_query(self) -> dict[str, Any]:
        """Serialize to snake_case query parameters, omitting unset fields."""
        return self.model_dump(exclude_none=True)


class MeasurementFilters(BaseModel):
    """Typed filter set for ``list_measurements`` / ``iter_measurements``. Field names match
    the API's snake_case query parameters; ``extra="allow"`` keeps it forward-compatible.

    ``type``/``status`` take the lowercase enum *value(s)* (e.g. ``"video"``, ``"done"`` — or
    ``MeasurementType.VIDEO.value``); ``preset`` takes preset id(s).
    """

    model_config = ConfigDict(extra="allow")

    id: int | None = None
    id_from: int | None = None
    id_to: int | None = None
    type: str | list[str] | None = None
    status: str | list[str] | None = None
    min_frames: int | None = None
    max_frames: int | None = None
    date: str | None = None  # legacy single-day filter; prefer date_from/date_to
    date_from: str | None = None
    date_to: str | None = None
    preset: int | list[int] | None = None
    parameter_filters: list[dict[str, Any]] | None = None

    def to_query(self) -> dict[str, Any]:
        """Serialize to snake_case query parameters, omitting unset fields."""
        return self.model_dump(exclude_none=True)


class ExportJob(BaseApiModel):
    id: int
    measurement_id: int | None = None
    format: str | None = None
    filters: dict[str, Any] | None = None
    status: str | None = None
    progress: int | None = None
    time_remaining: str | None = None
    download_url: str | None = None
    started_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class Preset(BaseApiModel):
    id: int
    gid: int
    name: str
    comment: str | None = None
    version: int
    compatibility: Any | None = None
    camera_snr: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


# =============================================================================
# Resources — infos / gpio
# =============================================================================


class GpioLevels(BaseApiModel):
    gpi: dict[str, bool] | None = None
    gpo: dict[str, bool] | None = None


class StreamingStatus(str, Enum):
    """Connection status of a TCP streaming interface (``GET /infos`` → interfaces.tcp)."""

    NONE = "none"
    IDLE = "idle"
    CONNECTED = "connected"


class SystemTemperatures(BaseApiModel):
    cpu: float | None = None
    ssd: float | None = None


class AnalysisUnitTemperatures(BaseApiModel):
    cpu: float | None = None
    pcb: float | None = None


class CameraUnitTemperatures(BaseApiModel):
    cpu: float | None = None
    pcb: float | None = None
    sensor: float | None = None


class SystemInfo(BaseApiModel):
    status: str | None = None
    mode: str | None = None
    action_type: str | None = Field(None, alias="actionType")
    uptime: int | None = None
    bundle_version: str | None = Field(None, alias="bundleVersion")
    software_version: str | None = Field(None, validation_alias=AliasChoices("softwareVersion", "sw"))
    gui_version: str | None = Field(None, alias="guiVersion")
    temperatures: SystemTemperatures | None = None
    # Pending machine errors / dismissible info-warning notifications. The spec models the
    # items as free-form objects (no fixed schema), so they stay as raw dicts here.
    errors: list[dict[str, Any]] | None = None
    messages: list[dict[str, Any]] | None = None


class AnalysisUnitInfo(BaseApiModel):
    """Analysis-unit identity. Field aliases follow the device (``hardwareVersion`` etc.);
    the older short names (``hw``/``snr``/``fw``/``sw``) are still accepted on read for
    backward compatibility (``Infos`` is never serialized back to the device)."""

    hardware_version: str | None = Field(None, validation_alias=AliasChoices("hardwareVersion", "hw"))
    order_number: str | None = Field(None, validation_alias=AliasChoices("orderNumber"))
    serial_number: str | None = Field(None, validation_alias=AliasChoices("serialNumber", "snr"))
    manufacturing_date: str | None = Field(None, validation_alias=AliasChoices("manufacturingDate"))
    firmware_version: str | None = Field(None, validation_alias=AliasChoices("firmwareVersion", "fw"))
    type: str | None = None
    status: str | None = None
    temperatures: AnalysisUnitTemperatures | None = None


class CameraUnitInfo(BaseApiModel):
    """Camera-unit identity/state. Like :class:`AnalysisUnitInfo`, the device emits
    ``hardwareVersion``/``serialNumber``/``firmwareVersion``; the short names are tolerated
    on read. Powered-on state is read from ``status`` (``powered_on`` / ``powered_off`` /
    ``overcurrent`` / ``none``) — the device does not send a separate boolean flag."""

    hardware_version: str | None = Field(None, validation_alias=AliasChoices("hardwareVersion", "hw"))
    firmware_version: str | None = Field(None, validation_alias=AliasChoices("firmwareVersion", "fw"))
    serial_number: str | None = Field(None, validation_alias=AliasChoices("serialNumber", "snr"))
    order_number: str | None = Field(None, validation_alias=AliasChoices("orderNumber"))
    manufacturing_date: str | None = Field(None, validation_alias=AliasChoices("manufacturingDate"))
    type: str | None = None
    status: str | None = None
    max_fps: int | None = Field(None, validation_alias=AliasChoices("maxFps"))
    path_to_reference_image: str | None = Field(None, validation_alias=AliasChoices("pathToReferenceImage"))
    temperatures: CameraUnitTemperatures | None = None


class StorageInfo(BaseApiModel):
    size: int | None = None
    free: int | None = None
    used: int | None = None


class NetworkEth(BaseApiModel):
    ip: str | None = None
    connected: bool | None = None


class NetworkInfo(BaseApiModel):
    hostname: str | None = None
    eth: NetworkEth | None = None


class ActivePresetInfo(BaseApiModel):
    """The currently-active preset block of ``GET /infos`` (distinct from the :class:`Preset`
    resource and the :class:`MeasurementPreset` embed)."""

    gid: int | None = None
    version: int | None = None
    unsaved_changes: bool | None = Field(None, alias="unsavedChanges")


class CalibrationUz(BaseApiModel):
    factor: float | None = None
    angle: float | None = None


class CalibrationVz(BaseApiModel):
    factor: float | None = None
    angle: float | None = None
    height: float | None = None


class CalibrationValues(BaseApiModel):
    uz: CalibrationUz | None = None
    vz: CalibrationVz | None = None


class CalibrationInfo(BaseApiModel):
    reference: int | None = None
    last_calibration: str | None = Field(None, alias="lastCalibration")  # ISO 8601 or None if never calibrated
    image_a: str | None = Field(None, alias="imageA")
    image_b: str | None = Field(None, alias="imageB")
    calibration_values: CalibrationValues | None = Field(None, alias="calibrationValues")


class TcpConnectionInfo(BaseApiModel):
    value: StreamingStatus | None = None  # value stream
    image: StreamingStatus | None = None  # image stream


class InterfacesInfo(BaseApiModel):
    tcp: TcpConnectionInfo | None = None


class Infos(BaseApiModel):
    """Response of ``GET /infos``. Every documented group is a typed model; only requested
    groups are populated when the ``groups`` query parameter is used."""

    system: SystemInfo | None = None
    analysisunit: AnalysisUnitInfo | None = None
    cameraunit: CameraUnitInfo | None = None
    storage: StorageInfo | None = None
    network: NetworkInfo | None = None
    preset: ActivePresetInfo | None = None
    calibration: CalibrationInfo | None = None
    interfaces: InterfacesInfo | None = None


# =============================================================================
# GUI settings (WebGUI-local; not synced to the machine)
# =============================================================================


class FormattingSettings(BaseApiModel):
    date_format: str | None = None
    decimal_separator: str | None = None
    thousands_separator: str | None = None
    decimal_places: int | None = None
    theme: str | None = None
    timezone: str | None = None


class ValveTypeSettings(BaseApiModel):
    valve_type: str | None = None
    available: list[str] | None = None


class TriggerAdapterSettings(BaseApiModel):
    trigger_adapter: str | None = None
    trigger_topology: str | None = None


# --- CSV export config (WebGUI-local) ---------------------------------------
# The hardcoded presets are read-only; only the "custom" config is writable via
# PATCH /gui-settings/csv-export-config (the server forces config_name to "custom").


class CsvFormatConfig(BaseApiModel):
    delimiter: str | None = None
    decimal_separator: str | None = None
    quote_character: str | None = None
    quote_rule: str | None = None  # ALL | STRINGS_ONLY | NONE
    encoding: str | None = None  # UTF-8 | UTF-16 | ISO-8859-1 | ASCII
    include_bom: bool | None = Field(None, alias="includeBOM")
    line_ending: str | None = None  # CRLF | LF


class CsvTimeConfig(BaseApiModel):
    format: str | None = None  # ISO8601 | UNIX_SEC | UNIX_MS | CUSTOM_STRING
    custom_format_string: str | None = None
    timezone: str | None = None
    split_date_and_time: bool | None = None


class CsvDataConfig(BaseApiModel):
    layout: str | None = None  # e.g. wide_feature_piped (row/column arrangement of the exported data)
    include_header: bool | None = None
    include_units_in_header: bool | None = None
    include_metadata_block: bool | None = None
    metadata_prefix: str | None = None
    null_value_strategy: str | None = None  # EMPTY | NAN | NULL | CUSTOM_VALUE
    custom_null_value: str | None = None


class CsvOutputConfig(BaseApiModel):
    max_rows_per_file: int | None = None
    decimal_places: int | None = None


class CsvExportConfig(BaseApiModel):
    """A full CSV export configuration snapshot (hardcoded preset or the custom config)."""

    config_name: str | None = Field(None, alias="config_name")  # excel_dach | excel_global | python_pandas | custom
    format: CsvFormatConfig | None = None
    time: CsvTimeConfig | None = None
    data: CsvDataConfig | None = None
    output: CsvOutputConfig | None = None


class CsvExportConfigCollection(BaseApiModel):
    """Response of ``GET /gui-settings/csv-export-config``: the read-only hardcoded
    presets (keyed by lowercase name) plus the user-editable ``custom_config`` (or None)."""

    hardcoded_configs: dict[str, CsvExportConfig] | None = None
    custom_config: CsvExportConfig | None = None


# =============================================================================
# Value stream — live measurement results
# =============================================================================
#
# Shared schema for the value stream (TCP port 51223, raw JSON) and the image
# stream's per-frame metadata field. snake_case python names map to camelCase on
# the wire via the BaseApiModel alias generator (feature_id -> featureId,
# frame_count -> frameCount).


class FeatureValue(BaseApiModel):
    """A single feature reading (one measured value plus its result status)."""

    model_config = ConfigDict(alias_generator=to_camel, extra="ignore", populate_by_name=True)

    feature_id: int | None = None
    value: float | None = None
    status: int | None = None


class Drop(BaseApiModel):
    """A detected drop within a ROI, carrying its own feature readings."""

    model_config = ConfigDict(alias_generator=to_camel, extra="ignore", populate_by_name=True)

    index: int | None = None
    results: list[FeatureValue] = []


class Roi(BaseApiModel):
    """A region-of-interest result: ROI-level readings plus any per-drop readings."""

    model_config = ConfigDict(alias_generator=to_camel, extra="ignore", populate_by_name=True)

    index: int | None = None
    results: list[FeatureValue] = []
    drops: list[Drop] = []


class StreamFrame(BaseApiModel):
    """One frame of a value message: its ROI results at a given timestamp."""

    model_config = ConfigDict(alias_generator=to_camel, extra="ignore", populate_by_name=True)

    index: int | None = None
    timestamp: int | None = None
    rois: list[Roi] = []


class ValueMessage(BaseApiModel):
    """A complete measurement value document (value stream / image metadata)."""

    # The value stream can carry more than the lean per-frame results: on a shot completed
    # while streaming (lab mode) the device pushes a fuller measurement document with extra
    # top-level keys (progress/attachments/preset/error) and a per-frame image path. Tolerate
    # those (extra="ignore") so one such message can't kill the value-listener thread. The whole
    # value-stream chain (FeatureValue/Drop/Roi/StreamFrame/ValueMessage) is tolerant for the
    # same reason. TEMPORARY pending a decision on how to model these fields properly.
    model_config = ConfigDict(alias_generator=to_camel, extra="ignore", populate_by_name=True)

    id: int | None = None
    type: int | None = None
    status: int | None = None
    frame_count: int | None = None
    timestamp: int | None = None
    frames: list[StreamFrame] = []


# =============================================================================
# Pagination
# =============================================================================

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """A single cursor-paginated page. Use ``next_cursor`` to fetch the next page
    (or the client's ``iter_*`` helpers to walk all pages automatically)."""

    model_config = ConfigDict(extra="ignore")

    data: list[T]
    next_cursor: str | None = None
    prev_cursor: str | None = None
    per_page: int | None = None

    def __iter__(self):  # type: ignore[override]
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)


# =============================================================================
# Realtime broadcast events (customer-facing Reverb app)
# =============================================================================
#
# These are the payloads pushed over the WebSocket event channel (see
# ``dropticalAPIClient.event_stream``). Unlike REST responses they use
# ``extra="ignore"``: broadcast events are notifications meant to be
# forward-compatible, so an added field must not break an older client.


class _BroadcastEventModel(BaseApiModel):
    """Base for camelCase broadcast payloads; tolerates unknown keys."""

    model_config = ConfigDict(alias_generator=to_camel, extra="ignore", populate_by_name=True)


class MachineStatusEvent(_BroadcastEventModel):
    """Payload of ``infos`` / ``changed`` — a thin machine-status notification.

    The customer-facing counterpart to the internal full-infos feed: signals a status/mode
    change; fetch full detail from ``GET /infos``.
    """

    status: str | None = None
    mode: str | None = None
    timestamp: str | None = None


class MeasurementUpdateRef(_BroadcastEventModel):
    """The nested ``measurement`` object of :class:`MeasurementUpdatedEvent`."""

    type: str | None = None
    status: str | None = None


class MeasurementUpdatedEvent(_BroadcastEventModel):
    """Payload of ``measurement`` / ``updated`` — a measurement was created/changed or frames were inserted."""

    measurement_id: int | None = None
    status_changed: bool | None = None
    frames_inserted_count: int | None = None
    from_frame_id: int | None = None
    to_frame_id: int | None = None
    measurement: MeasurementUpdateRef | None = None


class ExportProgressEvent(BaseApiModel):
    """Payload of ``exports`` / ``updated``.

    Identical in shape and casing to the Jobs REST resource (``GET /jobs/exports/{job}``)
    — ``snake_case`` on the wire (no camelCase aliasing), unlike the other broadcast
    events. ``download_url`` is set once the job is complete.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int | None = None
    measurement_id: int | None = None
    format: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    status: str | None = None
    progress: int | None = None
    time_remaining: int | None = None
    download_url: str | None = None
    started_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class PresetsChangedEvent(_BroadcastEventModel):
    """Payload of ``presets`` / ``changed``.

    ``action`` is one of ``created``, ``updated``, ``deleted``, ``version_created``,
    ``loaded`` (kept as a plain string for forward-compatibility).
    """

    action: str | None = None
    preset_id: int | None = None
    name: str | None = None
    version: int | None = None
    timestamp: str | None = None


class SettingsUpdatedEvent(_BroadcastEventModel):
    """Payload of ``settings`` / ``updated`` — a notification of which machine settings changed.

    Carries only the change set (``changed_groups`` / ``changed_keys``); read the values back
    from ``GET /settings`` (optionally narrowed to the changed groups).
    """

    changed_groups: list[str] = Field(default_factory=list)
    changed_keys: list[str] = Field(default_factory=list)
    timestamp: str | None = None
