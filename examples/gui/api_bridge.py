import logging
import time

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from droptical_api_client import (
    AllSettings,
    ApiError,
    BitDepth,
    ColorMode,
    CompressionAlgorithm,
    DeviceError,
    ImageFrame,
    Infos,
    Measurement,
    MeasurementFrame,
    MeasurementStatus,
    MeasurementType,
    dropticalAPIClient,
)

logger = logging.getLogger("GuiApiBridge")


class GuiApiBridge(QObject):
    """Bridge between the v2 ``dropticalAPIClient`` and the PyQt GUI.

    Long-running API calls run in a worker QThread and results are delivered as
    Qt signals so the GUI event loop stays responsive.
    """

    # Upper bound on frames listed + detail-fetched (with results) after a measurement,
    # to avoid a request storm on very large captures.
    FRAME_DISPLAY_LIMIT = 50

    # Signal emits a thread-safe QImage for display and raw bytes for saving.
    new_frame_signal = Signal(
        QImage,  # image_for_display
        bytes,  # raw_data_for_saving
        int,  # index
        str,  # timestamp
        int,  # width
        int,  # height
        CompressionAlgorithm,
        ColorMode,
        BitDepth,
        object,  # frame.metadata: a ValueMessage with per-frame results, or None
    )
    fps_update_signal = Signal(float)
    production_mode_conflict = Signal()

    # v2: a trigger returns a Measurement (id/status) rather than inline drops.
    # We emit (action_type, Measurement, list[MeasurementFrame]) — the frames are
    # fetched after the measurement completes so the UI can show images/results.
    control_action_finished_signal = Signal(str, object, object)

    status_update_signal = Signal(str)
    finished_signal = Signal()
    critical_error_signal = Signal(str, str)
    connection_successful_signal = Signal(Infos, AllSettings, object)  # object = list[Feature]
    handshake_finished_signal = Signal()

    def __init__(self, ip_address: str, api_port: int = 80):
        super().__init__()
        self.api = dropticalAPIClient()
        self.api.connect(ip_address, api_port=api_port)
        self._ip_address = ip_address
        logger.info(f"GuiApiBridge initialized for {ip_address}:{api_port}.")

        self._is_cancelled = False
        self._frame_counter = 0
        self._fps_last_time = 0.0
        self.FPS_UPDATE_INTERVAL_SECONDS = 1.0

    @Slot()
    def cancel_action(self) -> None:
        """Sets the cancellation flag to stop any ongoing API operation."""
        logger.info("Cancellation requested by user.")
        self._is_cancelled = True
        self.api.stop_image_stream()

    def run_connection_handshake(self) -> None:
        """Fetches initial infos and settings; emits success/failure signals."""
        logger.info("Starting connection handshake in worker thread...")
        self._is_cancelled = False
        try:
            infos = self.api.get_infos()
            try:
                all_settings = self.api.get_settings()
            except (DeviceError, ApiError) as e:
                # Some firmware may not implement the composite settings read yet;
                # fall back to built-in defaults so the UI can still populate.
                logger.warning(f"Could not read settings, using defaults: {e}")
                all_settings = AllSettings.default()
            try:
                features = self.api.get_features()
            except (DeviceError, ApiError) as e:
                # Older firmware may not expose the feature catalogue; the UI then falls
                # back to showing raw featureIds.
                logger.warning(f"Could not read feature catalogue: {e}")
                features = []
            if not self._is_cancelled:
                self.connection_successful_signal.emit(infos, all_settings, features)
        except DeviceError as e:
            logger.error(f"Connection handshake failed: {e}", exc_info=True)
            self.critical_error_signal.emit("Connection Failed", f"Could not retrieve initial device data.\n\nDetails: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred during connection handshake: {e}", exc_info=True)
            self.critical_error_signal.emit("Unexpected Error", f"An unexpected error occurred during connection.\n\nDetails: {e}")
        finally:
            self.handshake_finished_signal.emit()
            self.finished_signal.emit()

    def start_raw_stream_sequence(self) -> None:
        """Starts streaming, first checking whether the unit is in production mode."""
        logger.info("Starting stream sequence in worker thread...")
        self._is_cancelled = False
        try:
            infos = self.api.get_infos()
            if self._is_cancelled:
                self.finished_signal.emit()
                return

            in_production = bool(infos.system and infos.system.mode == "production")
            if in_production:
                self.production_mode_conflict.emit()
            else:
                self.resolve_conflict_and_continue(deactivate_production=False)

        except Exception as e:
            logger.error(f"Failed to start stream sequence: {e}", exc_info=True)
            self.critical_error_signal.emit("Connection Error", str(e))
            self.finished_signal.emit()
            self.handshake_finished_signal.emit()

    def resolve_conflict_and_continue(self, deactivate_production: bool) -> None:
        """Main worker loop for the raw video stream."""
        logger.info(f"Resolving stream conflict. Deactivating production: {deactivate_production}")
        try:
            if deactivate_production:
                self.api.set_production_mode(False)

            self._frame_counter = 0
            self._fps_last_time = time.time()
            self.status_update_signal.emit(f"Connecting to stream at {self._ip_address}...")

            with self.api.image_stream_session() as frame_stream:
                self.status_update_signal.emit("Stream connected successfully.")
                self.handshake_finished_signal.emit()
                for frame in frame_stream:
                    if self._is_cancelled:
                        logger.info("Stream loop cancelled.")
                        break
                    self._frame_handler(frame)

        except DeviceError as e:
            if not self._is_cancelled:
                logger.error(f"A device error occurred during streaming: {e}", exc_info=True)
                self.critical_error_signal.emit("Stream Error", str(e))
            self.handshake_finished_signal.emit()
        except Exception as e:
            if not self._is_cancelled:
                logger.error(f"An unexpected error occurred during streaming: {e}", exc_info=True)
                self.critical_error_signal.emit("Unexpected Stream Error", str(e))
            self.handshake_finished_signal.emit()
        finally:
            logger.info("Streaming loop finished.")
            self.finished_signal.emit()

    def stop_raw_stream_sequence(self) -> None:
        """Requests the raw video stream to stop."""
        self.cancel_action()

    def _frame_handler(self, frame: ImageFrame) -> None:
        """Turns a stream ImageFrame into a QImage and emits it (runs in the worker thread)."""
        q_image_format = QImage.Format.Format_Grayscale8 if frame.color_mode == ColorMode.GRAYSCALE else QImage.Format.Format_RGB888

        bytes_per_pixel = 1 if frame.color_mode == ColorMode.GRAYSCALE else 3
        unpadded_row_size = frame.width * bytes_per_pixel
        bytes_per_line = unpadded_row_size

        actual_data_size = len(frame.raw_data)
        expected_unpadded_size = unpadded_row_size * frame.height
        if actual_data_size > expected_unpadded_size and actual_data_size % frame.height == 0:
            bytes_per_line = actual_data_size // frame.height

        image_for_display = QImage(frame.raw_data, frame.width, frame.height, bytes_per_line, q_image_format).copy()

        self.new_frame_signal.emit(
            image_for_display,
            frame.raw_data,
            frame.index,
            frame.server_timestamp.isoformat(),
            frame.width,
            frame.height,
            frame.compression,
            frame.color_mode,
            frame.bit_depth,
            frame.metadata,
        )

        self._frame_counter += 1
        now = time.time()
        elapsed = now - self._fps_last_time
        if elapsed >= self.FPS_UPDATE_INTERVAL_SECONDS:
            fps = self._frame_counter / elapsed
            self.fps_update_signal.emit(fps)
            self._frame_counter, self._fps_last_time = 0, now

    # --- Measurement triggers (v2) --------------------------------------
    #
    # v2 measurements are ALWAYS asynchronous: creating one returns immediately
    # (HTTP 202) with a non-terminal status, and the device fills in frames and
    # attachments (stitched image / video) only once it finishes. The flow is
    # therefore: PATCH the (action) settings → create the measurement (async) →
    # poll until it reaches a terminal status → re-fetch it so the attachments
    # block is populated → read the resulting frames. v2 always persists the
    # measurement as a record, so there is no "save to database" option.

    def _emit_measurement_progress(self, measurement: Measurement) -> None:
        """Poll callback → surface live status/progress on the status bar."""
        pct = f" ({measurement.progress}%)" if measurement.progress is not None else ""
        self.status_update_signal.emit(f"Measurement #{measurement.id}: {measurement.status}{pct}")

    def _run_measurement(self, action_type: str, mtype: MeasurementType, settings: AllSettings, sync: bool = False) -> None:
        self._is_cancelled = False
        try:
            self.api.update_settings(settings)

            # sync=True blocks the create call until the measurement is terminal (used for an
            # internal-trigger single shot, which fires immediately); async returns at once and
            # we poll below (needed for an external trigger that may wait for its signal).
            measurement = self.api.create_measurement(mtype, sync=sync)
            self.status_update_signal.emit(f"Measurement #{measurement.id} started ({mtype.value})…")

            if not sync:
                # Block this worker thread until the measurement is terminal. timeout=None
                # (video can run long); the user can Cancel, which trips should_abort.
                measurement = self.api.wait_for_measurement(
                    measurement.id,
                    timeout=None,
                    poll_interval=0.4,
                    on_poll=self._emit_measurement_progress,
                    should_abort=lambda: self._is_cancelled,
                )

            if self._is_cancelled:
                logger.info("Measurement cancelled by user; aborting on device.")
                try:
                    self.api.abort()
                except DeviceError as e:
                    logger.warning(f"Could not abort measurement {measurement.id}: {e}")
                return

            # Re-fetch via GET /measurements/{id}: only that endpoint loads the
            # attachments block (stitched image / video download URLs).
            measurement = self.api.get_measurement(measurement.id)

            # A sync call can return before the measurement is terminal (the server-side wait
            # elapsed → HTTP 202): the machine is still running or awaiting its trigger, it does
            # not give up. Treat that as "still running" — surface any frames captured so far and
            # report the state, rather than raising it as a failure.
            status = measurement.status
            still_running = status in (
                MeasurementStatus.WAITING.value,
                MeasurementStatus.IN_PROGRESS.value,
                MeasurementStatus.NO_TRIGGER_RECEIVED.value,
            )

            frames: list[MeasurementFrame] = []
            if status == MeasurementStatus.DONE.value or still_running:
                try:
                    listed = self.api.list_measurement_frames(measurement.id, per_page=self.FRAME_DISPLAY_LIMIT).data
                except DeviceError as e:
                    logger.warning(f"Measurement {measurement.id} frames could not be read: {e}")
                    listed = []
                # The frame LIST omits per-frame results (rois); only the per-frame detail
                # endpoint loads them. Fetch each frame's detail so the UI can show results
                # (even for frames without a stored image). Bounded by FRAME_DISPLAY_LIMIT.
                if listed:
                    self.status_update_signal.emit(f"Loading results for {len(listed)} frame(s)…")
                for f in listed:
                    try:
                        frames.append(self.api.get_measurement_frame(measurement.id, f.id))
                    except DeviceError:
                        frames.append(f)  # fall back to the list entry (image only, no results)

            if still_running:
                self.status_update_signal.emit(
                    f"Measurement #{measurement.id} still running ({status}); "
                    f"{len(frames)} frame(s) so far — it keeps running on the device (poll or cancel to stop)."
                )
            elif status != MeasurementStatus.DONE.value:
                logger.warning(f"Measurement {measurement.id} ended non-successfully: {status}")

            self.control_action_finished_signal.emit(action_type, measurement, frames)
        except ApiError as e:
            logger.error(f"{action_type} failed: {e}", exc_info=True)
            self.critical_error_signal.emit(f"{action_type.replace('_', ' ').title()} Error", str(e))
        except DeviceError as e:
            logger.error(f"{action_type} failed: {e}", exc_info=True)
            self.critical_error_signal.emit(f"{action_type.replace('_', ' ').title()} Error", str(e))
        except Exception as e:
            logger.error(f"Unexpected error during {action_type}: {e}", exc_info=True)
            self.critical_error_signal.emit("Unexpected Error", str(e))
        finally:
            self.finished_signal.emit()

    def run_single_shot(self, settings: AllSettings, sync: bool = False) -> None:
        logger.info("Executing single shot in worker thread...")
        self._run_measurement("single_shot", MeasurementType.SINGLESHOT, settings, sync=sync)

    def run_multi_shot(self, settings: AllSettings, sync: bool = False) -> None:
        logger.info("Executing multi shot in worker thread...")
        self._run_measurement("multi_shot", MeasurementType.MULTISHOT, settings, sync=sync)

    def run_video(self, settings: AllSettings, sync: bool = False) -> None:
        logger.info("Executing video capture in worker thread...")
        self._run_measurement("video", MeasurementType.VIDEO, settings, sync=sync)
