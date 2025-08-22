from __future__ import annotations

from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

# =============================================================================
# Base and Shared Utilities
# =============================================================================


class BaseApiModel(BaseModel):
    """
    A base model for all API data classes.

    This model provides automatic camelCase alias conversion for field names
    and allows object instantiation using both the Pythonic field name and
    the camelCase alias.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="ignore",
        populate_by_name=True,
    )

    def to_dict(self, **kwargs: Any) -> dict[str, Any]:
        """Helper to serialize the model to a dictionary using camelCase aliases."""
        return self.model_dump(by_alias=True, **kwargs)


class TriggerEdge(str, Enum):
    """Enumeration for trigger edge settings, used in MachineSettings."""

    FALLING_EDGE = "FALLING_EDGE"
    RISING_EDGE = "RISING_EDGE"


# =============================================================================
# Core Measurement Settings
# =============================================================================


class SingleShotSettings(BaseApiModel):
    """Settings for a single-shot measurement."""

    FLASH_DELAY_MIN: ClassVar[int] = 20
    FLASH_DELAY_MAX: ClassVar[int] = 8100
    FLASH_DELAY_2_DELTA_MIN: ClassVar[int] = 10
    FLASH_DELAY2_MIN: ClassVar[int] = FLASH_DELAY_MIN + FLASH_DELAY_2_DELTA_MIN
    FLASH_DELAY2_MAX: ClassVar[int] = FLASH_DELAY_MAX
    POWER_FACTOR_MIN: ClassVar[float] = 0.0
    POWER_FACTOR_MAX: ClassVar[float] = 100.0

    use_external_trigger: bool = Field(..., alias="useExternalTrigger")
    double_flash_active: bool = Field(..., alias="doubleFlashActive")
    flash_delay: int | None = Field(None, ge=FLASH_DELAY_MIN, le=FLASH_DELAY_MAX, alias="flashDelay")
    flash_delay2: int | None = Field(None, ge=FLASH_DELAY2_MIN, le=FLASH_DELAY2_MAX, alias="flashDelay2")
    power_factor: float | None = Field(None, ge=POWER_FACTOR_MIN, le=POWER_FACTOR_MAX, alias="powerFactor")

    @classmethod
    def default(cls) -> SingleShotSettings:
        """Creates a default instance of the settings."""
        return cls(
            useExternalTrigger=False,
            doubleFlashActive=False,
            flashDelay=cls.FLASH_DELAY_MIN,
            flashDelay2=cls.FLASH_DELAY2_MIN,
            powerFactor=cls.POWER_FACTOR_MIN,
        )


class MultiShotSettings(BaseApiModel):
    """Settings for a multi-shot measurement."""

    FLASH_DELAY_MIN: ClassVar[int] = 20
    FLASH_DELAY_MAX: ClassVar[int] = 8100
    FLASH_DELAY_2_DELTA_MIN: ClassVar[int] = 10
    FLASH_DELAY2_MIN: ClassVar[int] = FLASH_DELAY_MIN + FLASH_DELAY_2_DELTA_MIN
    FLASH_DELAY2_MAX: ClassVar[int] = FLASH_DELAY_MAX
    POWER_FACTOR_MIN: ClassVar[float] = 0.0
    POWER_FACTOR_MAX: ClassVar[float] = 100.0
    TRIGGER_COUNT_MIN: ClassVar[int] = 2
    TRIGGER_COUNT_MAX: ClassVar[int] = 7500
    FREQUENCY_MIN: ClassVar[float] = 0.1
    FREQUENCY_MAX: ClassVar[int] = 1000

    use_external_trigger: bool = Field(..., alias="useExternalTrigger")
    save_all_images: bool = Field(..., alias="saveAllImages")
    capture_mode_on: bool = Field(..., alias="captureModeOn")
    double_flash_active: bool = Field(..., alias="doubleFlashActive")
    flash_delay: int | None = Field(None, ge=FLASH_DELAY_MIN, le=FLASH_DELAY_MAX, alias="flashDelay")
    flash_delay2: int | None = Field(None, ge=FLASH_DELAY2_MIN, le=FLASH_DELAY2_MAX, alias="flashDelay2")
    power_factor: float | None = Field(None, ge=POWER_FACTOR_MIN, le=POWER_FACTOR_MAX, alias="powerFactor")
    trigger_count: int | None = Field(None, ge=TRIGGER_COUNT_MIN, le=TRIGGER_COUNT_MAX, alias="triggerCount")
    frequency: float | None = Field(None, ge=FREQUENCY_MIN, le=FREQUENCY_MAX)

    @classmethod
    def default(cls) -> MultiShotSettings:
        """Creates a default instance of the settings."""
        return cls(
            useExternalTrigger=False,
            saveAllImages=False,
            captureModeOn=False,
            doubleFlashActive=False,
            flashDelay=cls.FLASH_DELAY_MIN,
            flashDelay2=cls.FLASH_DELAY2_MIN,
            powerFactor=cls.POWER_FACTOR_MIN,
            triggerCount=cls.TRIGGER_COUNT_MIN,
            frequency=cls.FREQUENCY_MIN,
        )


class VideoSettings(BaseApiModel):
    """Settings for a video recording."""

    FLASH_DELAY_MIN: ClassVar[int] = 20
    FLASH_DELAY_MAX: ClassVar[int] = 8100
    FLASH_DELAY_2_DELTA_MIN: ClassVar[int] = 10
    FLASH_DELAY2_MIN: ClassVar[int] = FLASH_DELAY_MIN + FLASH_DELAY_2_DELTA_MIN
    FLASH_DELAY2_MAX: ClassVar[int] = FLASH_DELAY_MAX
    START_TIME_MIN: ClassVar[int] = 20
    START_TIME_MAX: ClassVar[int] = 8100
    TIME_INCREMENT_MIN: ClassVar[int] = 1
    END_TIME_MIN: ClassVar[int] = START_TIME_MIN + TIME_INCREMENT_MIN
    END_TIME_MAX: ClassVar[int] = 8100
    IMAGE_COUNT_MIN: ClassVar[int] = 2
    IMAGE_COUNT_MAX: ClassVar[int] = 7500
    STITCH_COUNT_MIN: ClassVar[int] = 2
    STITCH_COUNT_MAX: ClassVar[int] = 30
    POWER_FACTOR_MIN: ClassVar[float] = 0.0
    POWER_FACTOR_MAX: ClassVar[float] = 100.0
    FREQUENCY_MIN: ClassVar[float] = 0.1
    FREQUENCY_MAX: ClassVar[float] = 1000.0
    FPS_MIN: ClassVar[int] = 1
    FPS_MAX: ClassVar[int] = 120

    use_external_trigger: bool = Field(..., alias="useExternalTrigger")
    use_constant_mode: bool = Field(..., alias="useConstantMode")
    double_flash_active: bool = Field(..., alias="doubleFlashActive")
    flash_delay: int | None = Field(None, ge=FLASH_DELAY_MIN, le=FLASH_DELAY_MAX, alias="flashDelay")
    flash_delay2: int | None = Field(None, ge=FLASH_DELAY2_MIN, le=FLASH_DELAY2_MAX, alias="flashDelay2")
    start_time: int | None = Field(None, ge=START_TIME_MIN, le=START_TIME_MAX, alias="startTime")
    end_time: int | None = Field(None, ge=END_TIME_MIN, le=END_TIME_MAX, alias="endTime")
    time_increment: int | None = Field(None, ge=TIME_INCREMENT_MIN, alias="timeIncrement")
    image_count: int | None = Field(None, ge=IMAGE_COUNT_MIN, le=IMAGE_COUNT_MAX, alias="imageCount")
    stitch_count: int | None = Field(None, ge=2, le=30, alias="stitchCount")
    power_factor: float | None = Field(None, ge=POWER_FACTOR_MIN, le=POWER_FACTOR_MAX, alias="powerFactor")
    fps: int | None = Field(None, ge=1, le=120)
    frequency: float | None = Field(None, ge=0.1, le=1000)

    @model_validator(mode="after")
    def check_start_end_time(self) -> VideoSettings:
        """Ensures that endTime is not less than startTime."""
        if self.start_time is not None and self.end_time is not None:
            if self.end_time < self.start_time:
                raise ValueError("endTime must not be less than startTime")
        return self

    @classmethod
    def default(cls) -> VideoSettings:
        """Creates a default instance of the settings."""
        return cls(
            useExternalTrigger=False,
            useConstantMode=False,
            doubleFlashActive=False,
            flashDelay=cls.FLASH_DELAY_MIN,
            flashDelay2=cls.FLASH_DELAY2_MIN,
            startTime=cls.START_TIME_MIN,
            endTime=cls.END_TIME_MIN,
            timeIncrement=cls.TIME_INCREMENT_MIN,
            imageCount=cls.IMAGE_COUNT_MIN,
            stitchCount=2,
            powerFactor=cls.POWER_FACTOR_MIN,
            fps=1,
            frequency=0.1,
        )


# =============================================================================
# Detailed Device Configuration Models
# =============================================================================


class Limits(BaseApiModel):
    """Defines the error, warning, and nominal value limits for a feature."""

    error_minus: float | None = Field(None, ge=0.0, alias="errorMinus")
    warning_minus: float | None = Field(None, ge=0.0, alias="warningMinus")
    nominal: float | None = Field(None, ge=0.0)
    warning_plus: float | None = Field(None, ge=0.0, alias="warningPlus")
    error_plus: float | None = Field(None, ge=0.0, alias="errorPlus")

    @classmethod
    def default(cls) -> Limits:
        """Creates a default instance of the limits."""
        return cls(errorMinus=0.0, warningMinus=0.0, nominal=0.0, warningPlus=0.0, errorPlus=0.0)


class FeatureLimitSettings(BaseApiModel):
    """Settings for a single calculated feature (e.g., Volume)."""

    name: str
    unit: str
    enabled: bool
    use_limits: bool = Field(..., alias="useLimits")
    limits: Limits | None = None

    @classmethod
    def default(cls) -> FeatureLimitSettings:
        """Creates a default instance of the settings."""
        return cls(name="Volume", unit="nl", enabled=True, useLimits=False, limits=Limits.default())


class RoiUzDimension(BaseApiModel):
    """Defines the dimensions of a Region of Interest in U/Z coordinates."""

    ROI_START_MIN: ClassVar[float] = 0.0
    ROI_START_MAX: ClassVar[float] = 99.9
    ROI_SIZE_MIN: ClassVar[float] = 1.0
    ROI_SIZE_MAX: ClassVar[float] = 100.0

    start_u: float | None = Field(None, ge=ROI_START_MIN, le=ROI_START_MAX, alias="startU")
    start_z: float | None = Field(None, ge=ROI_START_MIN, le=ROI_START_MAX, alias="startZ")
    width: float | None = Field(None, ge=ROI_SIZE_MIN, le=ROI_SIZE_MAX)
    height: float | None = Field(None, ge=ROI_SIZE_MIN, le=ROI_SIZE_MAX)

    @classmethod
    def default(cls) -> RoiUzDimension:
        """Creates a default instance of the dimensions."""
        return cls(startU=0.0, startZ=0.0, width=1.0, height=1.0)


class RoiVzDimension(BaseApiModel):
    """Defines the dimensions of a Region of Interest in V/Z coordinates."""

    ROI_START_MIN: ClassVar[float] = 0.0
    ROI_START_MAX: ClassVar[float] = 99.9
    ROI_SIZE_MIN: ClassVar[float] = 1.0
    ROI_SIZE_MAX: ClassVar[float] = 100.0

    start_v: float | None = Field(None, ge=ROI_START_MIN, le=ROI_START_MAX, alias="startV")
    start_z: float | None = Field(None, ge=ROI_START_MIN, le=ROI_START_MAX, alias="startZ")
    width: float | None = Field(None, ge=ROI_SIZE_MIN, le=ROI_SIZE_MAX)
    height: float | None = Field(None, ge=ROI_SIZE_MIN, le=ROI_SIZE_MAX)

    @classmethod
    def default(cls) -> RoiVzDimension:
        """Creates a default instance of the dimensions."""
        return cls(startV=0.0, startZ=0.0, width=1.0, height=1.0)


class RoiSettings(BaseApiModel):
    """Defines a specific ROI, combining U/Z and V/Z dimensions."""

    uz: RoiUzDimension | None = None
    vz: RoiVzDimension | None = None
    enabled: bool = True

    @classmethod
    def default(cls) -> RoiSettings:
        """Creates a default instance of the ROI settings."""
        return cls(uz=RoiUzDimension.default(), vz=RoiVzDimension.default(), enabled=True)


class RoiSettingsCollection(BaseApiModel):
    """A collection of all ROI types (processing, nozzle, exclusion)."""

    sync_axes: bool = Field(..., alias="syncAxes")
    processing: RoiSettings | None = None
    nozzle: RoiSettings | None = None
    exclusion: RoiSettings | None = None

    @classmethod
    def default(cls) -> RoiSettingsCollection:
        """Creates a default instance of the collection."""
        return cls(syncAxes=False, processing=RoiSettings.default(), nozzle=RoiSettings.default(), exclusion=RoiSettings.default())


class NozzleTipUz(BaseApiModel):
    """Nozzle tip position in U/Z pixel coordinates."""

    MIN: ClassVar[int] = 0
    MAX: ClassVar[int] = 1400
    u: int | None = Field(None, ge=MIN, le=MAX)
    z: int | None = Field(None, ge=MIN, le=MAX)

    @classmethod
    def default(cls) -> NozzleTipUz:
        """Creates a default instance of the coordinates."""
        return cls(u=0, z=0)


class NozzleTipVz(BaseApiModel):
    """Nozzle tip position in V/Z pixel coordinates."""

    MIN: ClassVar[int] = 0
    MAX: ClassVar[int] = 1400
    v: int | None = Field(None, ge=MIN, le=MAX)
    z: int | None = Field(None, ge=MIN, le=MAX)

    @classmethod
    def default(cls) -> NozzleTipVz:
        """Creates a default instance of the coordinates."""
        return cls(v=0, z=0)


class NozzleTipSettings(BaseApiModel):
    """Container for both U/Z and V/Z nozzle tip coordinates."""

    uz: NozzleTipUz | None = None
    vz: NozzleTipVz | None = None

    @classmethod
    def default(cls) -> NozzleTipSettings:
        """Creates a default instance of the settings."""
        return cls(uz=NozzleTipUz.default(), vz=NozzleTipVz.default())


class CustomerSpaceSettings(BaseApiModel):
    """Custom text lines for display or reporting."""

    line1: str | None = Field(None, max_length=50)
    line2: str | None = Field(None, max_length=50)
    line3: str | None = Field(None, max_length=50)

    @classmethod
    def default(cls) -> CustomerSpaceSettings:
        """Creates a default instance of the settings."""
        return cls(line1="", line2="", line3="")


class AlgorithmSettings(BaseApiModel):
    """Placeholder for settings related to image processing algorithms."""

    # TODO: Add specific algorithm fields here when they are known.
    @classmethod
    def default(cls) -> AlgorithmSettings:
        return cls()


class CalculatorySettings(BaseApiModel):
    """Main container for all settings related to how measurements are calculated."""

    DENSITY_MIN: ClassVar[float] = 0.0000
    DENSITY_MAX: ClassVar[float] = 20.0000
    FIXED_THRESHOLD_MIN: ClassVar[int] = 0
    FIXED_THRESHOLD_MAX: ClassVar[int] = 255
    GAUSS_KERNEL_SIZE_MIN: ClassVar[int] = 0
    GAUSS_KERNEL_SIZE_MAX: ClassVar[int] = 255
    GAUSS_SIGMA_X_MIN: ClassVar[float] = 0.1
    GAUSS_SIGMA_X_MAX: ClassVar[float] = 5.0

    force_calculation: bool = Field(..., alias="forceCalculation")
    extra_info: bool = Field(..., alias="extraInfo")
    background_cancelation: bool = Field(..., alias="backgroundCancelation")
    save_warning_image: bool = Field(..., alias="saveWarningImage")
    save_limit_image: bool = Field(..., alias="saveLimitImage")
    save_with_contours: bool = Field(..., alias="saveWithContours")
    mass_calculation: bool = Field(..., alias="massCalculation")
    density: float | None = Field(None, ge=DENSITY_MIN, le=DENSITY_MAX)
    fixed_threshold: int | None = Field(None, ge=FIXED_THRESHOLD_MIN, le=FIXED_THRESHOLD_MAX, alias="fixedThreshold")
    gauss_kernel_size: int | None = Field(None, ge=GAUSS_KERNEL_SIZE_MIN, le=GAUSS_KERNEL_SIZE_MAX, alias="gaussKernelSize")
    gauss_sigma_x: float | None = Field(None, ge=GAUSS_SIGMA_X_MIN, le=GAUSS_SIGMA_X_MAX, alias="gaussSigmaX")
    path_to_ref_img: str = Field(..., alias="pathToRefImg")
    customer_space: CustomerSpaceSettings | None = Field(None, alias="customerSpace")
    algorithms: AlgorithmSettings | None = None
    roi: RoiSettingsCollection | None = None
    nozzle_tip: NozzleTipSettings | None = Field(None, alias="nozzleTip")
    features: dict[int, FeatureLimitSettings]

    @classmethod
    def default(cls) -> CalculatorySettings:
        """Creates a default instance of the settings."""
        return cls(
            forceCalculation=False,
            extraInfo=False,
            backgroundCancelation=False,
            saveWarningImage=False,
            saveLimitImage=False,
            saveWithContours=False,
            massCalculation=False,
            density=0.0,
            fixedThreshold=128,
            gaussKernelSize=0,
            gaussSigmaX=0.8,
            pathToRefImg="",
            customerSpace=CustomerSpaceSettings.default(),
            algorithms=AlgorithmSettings.default(),
            roi=RoiSettingsCollection.default(),
            nozzleTip=NozzleTipSettings.default(),
            features={1: FeatureLimitSettings.default()},
        )


class ExposureSettings(BaseApiModel):
    """Defines the exposure time for the UZ and VZ cameras."""

    EXPOSURE_TIME_MIN: ClassVar[float] = 0.3125
    EXPOSURE_TIME_MAX: ClassVar[float] = 5.0

    uz: float | None = Field(None, ge=EXPOSURE_TIME_MIN, le=EXPOSURE_TIME_MAX)
    vz: float | None = Field(None, ge=EXPOSURE_TIME_MIN, le=EXPOSURE_TIME_MAX)

    @classmethod
    def default(cls) -> ExposureSettings:
        """Creates a default instance of the settings."""
        return cls(uz=cls.EXPOSURE_TIME_MIN, vz=cls.EXPOSURE_TIME_MIN)


class CroppingSettings(BaseApiModel):
    """Defines the camera sensor cropping/windowing settings."""

    H_SIZE_MIN: ClassVar[int] = 120
    H_SIZE_MAX: ClassVar[int] = 800
    V_SIZE_MIN: ClassVar[int] = 150
    V_SIZE_MAX: ClassVar[int] = 1400
    V_START_MIN: ClassVar[int] = 0
    V_START_MAX: ClassVar[int] = 1400
    V_START2_DEFAULT: ClassVar[int] = 700

    hsize: int | None = Field(None, ge=H_SIZE_MIN, le=H_SIZE_MAX)
    vsize1: int | None = Field(None, ge=V_SIZE_MIN, le=V_SIZE_MAX)
    vsize2: int | None = Field(None, ge=V_SIZE_MIN, le=V_SIZE_MAX)
    vstart1: int | None = Field(None, ge=V_START_MIN, le=V_START_MAX)
    vstart2: int | None = Field(None, ge=V_START_MIN, le=V_START_MAX)

    @classmethod
    def default(cls) -> CroppingSettings:
        """Creates a default instance of the settings."""
        return cls(hsize=cls.H_SIZE_MAX, vsize1=700, vsize2=700, vstart1=cls.V_START_MIN, vstart2=cls.V_START2_DEFAULT)


class CameraSettings(BaseApiModel):
    """Groups all camera-related hardware settings."""

    exposure_time: ExposureSettings | None = Field(None, alias="exposureTime")
    cropping: CroppingSettings | None = None
    max_fps: int | None = Field(None, alias="maxFPS")
    flip_image: bool = Field(..., alias="flipImage")

    @classmethod
    def default(cls) -> CameraSettings:
        """Creates a default instance of the settings."""
        return cls(exposureTime=ExposureSettings.default(), cropping=CroppingSettings.default(), maxFPS=1, flipImage=False)


class GPISettings(BaseApiModel):
    """Defines the settings for General Purpose Inputs (GPI)."""

    options: list[str]
    available: list[str]
    settings: dict[str, str]
    inverted: dict[str, bool]

    @model_validator(mode="after")
    def validate_gpi_consistency(self) -> GPISettings:
        """Validates that GPI settings use available pins and valid options."""
        available_set = set(self.available)
        options_set = set(self.options)
        for key in self.settings:
            if key not in available_set:
                raise ValueError(f"GPI settings key '{key}' not in available list: {self.available}")
        for key in self.inverted:
            if key not in available_set:
                raise ValueError(f"GPI inverted key '{key}' not in available list: {self.available}")
        for value in self.settings.values():
            if value not in options_set:
                raise ValueError(f"GPI settings value '{value}' not in options list: {self.options}")
        return self

    @classmethod
    def default(cls) -> GPISettings:
        """Creates a default instance of the settings."""
        return cls(options=[], available=[], settings={}, inverted={})


class GPOSettings(BaseApiModel):
    """Defines the settings for General Purpose Outputs (GPO)."""

    GPO_EXTRA_OPTIONS: ClassVar[set] = {"Error", "Idle"}

    options: list[str]
    available: list[str]
    settings: dict[str, str]
    inverted: dict[str, bool]

    @model_validator(mode="after")
    def validate_gpo_consistency(self) -> GPOSettings:
        """Validates that GPO settings use available pins and valid options."""
        available_set = set(self.available)
        valid_options_set = set(self.options).union(self.GPO_EXTRA_OPTIONS)
        for key in self.settings:
            if key not in available_set:
                raise ValueError(f"GPO settings key '{key}' not in available list: {self.available}")
        for key in self.inverted:
            if key not in available_set:
                raise ValueError(f"GPO inverted key '{key}' not in available list: {self.available}")
        for value in self.settings.values():
            if value not in valid_options_set:
                raise ValueError(f"GPO value '{value}' not in valid options: {list(valid_options_set)}")
        return self

    @classmethod
    def default(cls) -> GPOSettings:
        """Creates a default instance of the settings."""
        return cls(options=[], available=[], settings={}, inverted={})


class MachineSettings(BaseApiModel):
    """Groups general machine settings, e.g., for GPIO and trigger behavior."""

    gpi: GPISettings | None = None
    gpo: GPOSettings | None = None
    output_trigger_edge: TriggerEdge = Field(..., alias="outputTriggerEdge")
    input_trigger_edge: TriggerEdge = Field(..., alias="inputTriggerEdge")

    @classmethod
    def default(cls) -> MachineSettings:
        """Creates a default instance of the settings."""
        return cls(gpi=GPISettings.default(), gpo=GPOSettings.default(), outputTriggerEdge=TriggerEdge.RISING_EDGE, inputTriggerEdge=TriggerEdge.RISING_EDGE)


# =============================================================================
# Informational and Composite Models
# =============================================================================


class AnalysisUnitInfos(BaseApiModel):
    """Information about the main analysis unit (the computer)."""

    hw: str
    type: str
    snr: str
    mfd: str
    fw: str
    sw: str
    bundle: str
    status: str
    production_mode: bool = Field(..., alias="productionMode")
    streaming_mode: bool = Field(..., alias="streamingMode")

    @property
    def has_errors(self) -> bool:
        """Returns True if the analysis unit is in an error state."""
        return self.status.lower() == "error"

    @classmethod
    def default(cls) -> AnalysisUnitInfos:
        """Creates a default instance of the information."""
        return cls(
            hw="not given", type="not given", snr="not given", mfd="not given", fw="not given", sw="not given", bundle="not given", status="not given", productionMode=False, streamingMode=False
        )


class CameraUnitInfos(BaseApiModel):
    """Information about the connected camera unit."""

    hw: str
    snr: str
    mfd: str
    fw: str
    status: str
    type: str
    power: bool
    is_ultistrobe: bool = Field(..., alias="isUltistrobe")

    @classmethod
    def default(cls) -> CameraUnitInfos:
        """Creates a default instance of the information."""
        return cls(hw="not given", snr="not given", mfd="not given", fw="not given", status="not given", type="not given", power=False, isUltistrobe=False)


class NetworkInterface(BaseApiModel):
    """Details of a single network interface."""

    ip: str
    connected: bool

    @classmethod
    def default(cls) -> NetworkInterface:
        """Creates a default instance of the interface details."""
        return cls(ip="", connected=False)


class NetworkResponseData(BaseApiModel):
    """Aggregated network configuration details."""

    hostname: str
    eth: NetworkInterface | None = None

    @classmethod
    def default(cls) -> NetworkResponseData:
        """Creates a default instance of the network details."""
        return cls(hostname="", eth=NetworkInterface.default())


class StorageResponseData(BaseApiModel):
    """Information about the device's storage capacity."""

    size: int = Field(..., ge=0)
    free: int = Field(..., ge=0)
    used: int = Field(..., ge=0)

    @classmethod
    def default(cls) -> StorageResponseData:
        """Creates a default instance of the storage details."""
        return cls(size=1000, free=1000, used=0)


class MachineInfo(BaseApiModel):
    """A comprehensive container for all hardware, software, and status info."""

    analysisunit: AnalysisUnitInfos
    cameraunit: CameraUnitInfos
    network: NetworkResponseData | None = None
    storage: StorageResponseData | None = None

    @classmethod
    def default(cls) -> MachineInfo:
        """Creates a default instance of the machine info."""
        return cls(analysisunit=AnalysisUnitInfos.default(), cameraunit=CameraUnitInfos.default(), network=NetworkResponseData.default(), storage=StorageResponseData.default())


class AllSettings(BaseApiModel):
    """A composite object that holds all configurable settings models."""

    single_shot_settings: SingleShotSettings = Field(..., alias="singleShot")
    multi_shot_settings: MultiShotSettings = Field(..., alias="multiShot")
    video_settings: VideoSettings = Field(..., alias="video")
    calculatory_settings: CalculatorySettings = Field(..., alias="calculatory")
    camera_settings: CameraSettings = Field(..., alias="camera")
    machine_settings: MachineSettings = Field(..., alias="machine")

    @classmethod
    def default(cls) -> AllSettings:
        """Creates a default instance of all settings."""
        return cls(
            singleShot=SingleShotSettings.default(),
            multiShot=MultiShotSettings.default(),
            video=VideoSettings.default(),
            calculatory=CalculatorySettings.default(),
            camera=CameraSettings.default(),
            machine=MachineSettings.default(),
        )


class PresetInfo(BaseApiModel):
    """Information about the currently loaded preset."""

    gid: int
    version: int


class GpioLevels(BaseApiModel):
    """Represents the current state of GPIO pins."""

    # TODO: Add specific algorithm fields here when they are known.
    @classmethod
    def default(cls) -> GpioLevels:
        return cls()


# =============================================================================
# Preset and Payload Models
# =============================================================================


class Preset(BaseApiModel):
    """Represents a single preset entry in a list from the device."""

    id: int
    gid: int
    name: str
    comment: str | None = None
    version: int
    is_deleted: bool = Field(..., alias="isDeleted")
    created_at: str = Field(..., alias="createdAt")
    updated_at: str = Field(..., alias="updatedAt")


class ProductionModePayload(BaseApiModel):
    """Payload for enabling or disabling production mode."""

    active: bool


class StreamingModePayload(BaseApiModel):
    """Payload for enabling or disabling streaming mode."""

    active: bool


class PresetLoadPayload(BaseApiModel):
    """Payload for loading a specific preset by GID and version."""

    gid: int
    version: int


class PresetCreatePayload(BaseApiModel):
    """Payload for creating a new preset."""

    name: str
    comment: str | None = None


class PresetCreateVersionPayload(BaseApiModel):
    """Payload for creating a new version of an existing preset."""

    gid: int
    comment: str | None = None


class PresetEditPayload(BaseApiModel):
    """Payload for editing the metadata of a preset."""

    id: int
    name: str
    comment: str | None = None


class PresetDeletePayload(BaseApiModel):
    """Payload for deleting a preset."""

    id: int


# =============================================================================
# Action Response Models
# =============================================================================


class SingleDropData(BaseApiModel):
    """
    Represents the detailed metrics for a single measured drop.
    Uses aliases to map short JSON keys to descriptive names.
    """

    v: float = Field(..., alias="value", ge=0)
    n: int = Field(..., alias="number_of_drops", ge=0)
    sV: float = Field(..., alias="value_of_satellites", ge=0)
    sN: int = Field(..., alias="number_of_satellites", ge=0)
    ts: int | None = Field(..., alias="timestamp_ms")
    p: str | None = Field(None, alias="path_to_png_image")

    @classmethod
    def default(cls) -> SingleDropData:
        """Creates a default instance of single drop data."""
        return cls(
            value=0.0,
            number_of_drops=0,
            value_of_satellites=0.0,
            number_of_satellites=0,
            timestamp_ms=0,
            path_to_png_image="",
        )


class SingleShotResponse(BaseApiModel):
    """The response returned after a successful 'single-shot' command."""

    value_name: str = Field(..., alias="valueName")
    value_unit: str = Field(..., alias="valueUnit")
    use_external_trigger: bool = Field(..., alias="useExternalTrigger")
    preset: PresetInfo
    single_drops: list[SingleDropData] = Field(..., alias="singleDrops")

    @classmethod
    def default(cls) -> SingleShotResponse:
        """Creates a default response instance for a single shot."""
        default_preset = PresetInfo(gid=0, version=0)
        return cls(valueName="Default Value", valueUnit="unit", useExternalTrigger=False, preset=default_preset, singleDrops=[SingleDropData.default()])


class MultiShotResponse(BaseApiModel):
    """The response returned after a successful 'multi-shot' command."""

    use_external_trigger: bool = Field(..., alias="useExternalTrigger")
    value_name: str = Field(..., alias="valueName")
    value_unit: str = Field(..., alias="valueUnit")
    csv_path: str = Field(..., alias="csvPath")
    preset: PresetInfo
    single_drops: list[SingleDropData] = Field(..., alias="singleDrops")

    @classmethod
    def default(cls) -> MultiShotResponse:
        """Creates a default response instance for a multi shot."""
        default_preset = PresetInfo(gid=0, version=0)
        return cls(valueName="Default Value", valueUnit="unit", useExternalTrigger=False, csvPath="", preset=default_preset, singleDrops=[SingleDropData.default(), SingleDropData.default()])


class VideoResponse(BaseApiModel):
    """The response returned after a successful 'video' command."""

    path_to_video: str = Field(..., alias="pathToVideo")
    path_to_image: str | None = Field(..., alias="pathToImage")
    use_external_trigger: bool = Field(..., alias="useExternalTrigger")
    preset: PresetInfo

    @classmethod
    def default(cls) -> VideoResponse:
        """Creates a default response instance for a video."""
        default_preset = PresetInfo(gid=0, version=0)
        return cls(
            pathToVideo="",
            pathToImage="",
            useExternalTrigger=False,
            preset=default_preset,
        )
