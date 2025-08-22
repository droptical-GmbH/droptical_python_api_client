import logging
import time

from pydantic import ValidationError
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage

from droptical_api_client import (
    AllSettings,
    BaseApiModel,
    BitDepth,
    ColorMode,
    CompressionAlgorithm,
    DeviceError,
    Frame,
    MachineInfo,
    MultiShotSettings,
    SingleShotSettings,
    VideoSettings,
    dropticalAPIClient,
)

logger = logging.getLogger("GuiApiBridge")


class GuiApiBridge(QObject):
    """
    A bridge between the dropticalAPIClient and the PyQt GUI.

    This class handles communication between the device API, which may perform
    long-running tasks, and the GUI's event loop. It translates API responses
    and streaming data into Qt signals, allowing it to run safely in a
    separate QThread without blocking the user interface.
    """

    # Signal emits a thread-safe QImage for display and raw bytes for saving.
    new_frame_signal = pyqtSignal(
        QImage,  # image_for_display
        bytes,  # raw_data_for_saving
        int,  # id1
        int,  # id2
        int,  # id3
        str,  # timestamp
        int,  # width
        int,  # height
        CompressionAlgorithm,
        ColorMode,
        BitDepth,
    )
    fps_update_signal = pyqtSignal(float)
    production_mode_conflict = pyqtSignal()

    control_action_finished_signal = pyqtSignal(str, BaseApiModel)

    status_update_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    critical_error_signal = pyqtSignal(str, str)
    connection_successful_signal = pyqtSignal(MachineInfo, AllSettings)
    handshake_finished_signal = pyqtSignal()

    def __init__(self, ip_address: str):
        super().__init__()
        self.api = dropticalAPIClient()
        self.api.connect(ip_address)
        logger.info(f"GuiApiBridge initialized for IP {ip_address}.")

        self._is_cancelled = False
        self._frame_counter = 0
        self._fps_last_time = 0.0
        self.FPS_UPDATE_INTERVAL_SECONDS = 1.0

    @pyqtSlot()
    def cancel_action(self) -> None:
        """Sets the cancellation flag to stop any ongoing API operation."""
        logger.info("Cancellation requested by user.")
        self._is_cancelled = True
        self.api.stop_stream()

    def run_connection_handshake(self) -> None:
        """
        Connects to the device, fetches initial info and all settings.
        Emits signals based on success or failure.
        """
        logger.info("Starting connection handshake in worker thread...")
        self._is_cancelled = False
        try:
            machine_info = self.api.get_machine_info()
            # all_settings = self.api.get_all_settings() TODO: Needs to be implemented in cpp-backend
            all_settings = AllSettings.default()
            if not self._is_cancelled:
                self.connection_successful_signal.emit(machine_info, all_settings)
        except (DeviceError, ValidationError) as e:
            logger.error(f"Connection handshake failed: {e}", exc_info=True)
            self.critical_error_signal.emit("Connection Failed", f"Could not retrieve initial device data. The device response might be invalid or incomplete.\n\nDetails: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred during connection handshake: {e}", exc_info=True)
            self.critical_error_signal.emit("Unexpected Error", f"An unexpected error occurred during connection.\n\nDetails: {e}")
        finally:
            self.handshake_finished_signal.emit()
            self.finished_signal.emit()

    def start_raw_stream_sequence(self) -> None:
        """
        Initiates the streaming sequence and checks for production mode.

        This method performs an initial handshake with the device to determine if
        it's in production mode, which may conflict with streaming. It then
        calls `resolve_conflict_and_continue` to handle the streaming loop.
        """
        logger.info("Starting stream sequence in worker thread...")
        self._is_cancelled = False
        try:
            info = self.api.get_machine_info()
            if self._is_cancelled:
                self.finished_signal.emit()
                return

            if info.analysisunit.production_mode:
                self.production_mode_conflict.emit()
            else:
                self.resolve_conflict_and_continue(deactivate_production=False)

        except Exception as e:
            logger.error(f"Failed to start stream sequence: {e}", exc_info=True)
            self.critical_error_signal.emit("Connection Error", str(e))
            self.finished_signal.emit()
            self.handshake_finished_signal.emit()

    def resolve_conflict_and_continue(self, deactivate_production: bool) -> None:
        """
        The main worker loop for processing a raw video stream.

        This method connects to the stream, processes incoming frames, and
        emits signals for each new frame and for FPS updates.
        """
        logger.info(f"Resolving stream conflict. Deactivating production: {deactivate_production}")
        try:
            if deactivate_production:
                self.api.set_production_mode(False)

            self._frame_counter = 0
            self._fps_last_time = time.time()
            self.status_update_signal.emit(f"Connecting to stream at {self.api._ip_address}...")

            with self.api.streaming_session() as frame_stream:
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
        """
        Requests the raw video stream to stop.

        This method is a wrapper around `cancel_action` and is primarily
        used to halt an active stream.
        """
        self.cancel_action()

    def _frame_handler(self, frame: Frame) -> None:
        """
        Processes a single frame, creates a QImage, calculates FPS, and emits the data.

        This method is called for each frame received from the stream generator.
        It creates a QImage in this worker thread to offload the GUI thread.
        It emits `new_frame_signal` with both the QImage and the original raw
        data, and periodically emits `fps_update_signal`.
        """
        q_image_format = QImage.Format.Format_Grayscale8 if frame.color_mode == ColorMode.GRAYSCALE else QImage.Format.Format_RGB888

        bytes_per_pixel = 1 if frame.color_mode == ColorMode.GRAYSCALE else 3
        unpadded_row_size = frame.width * bytes_per_pixel

        bytes_per_line = unpadded_row_size

        actual_data_size = len(frame.raw_data)
        expected_unpadded_size = unpadded_row_size * frame.height
        if actual_data_size > expected_unpadded_size and actual_data_size % frame.height == 0:
            bytes_per_line = actual_data_size // frame.height

        # The QImage constructor that takes a `bytes` object is smart enough to
        # manage the memory, but to be explicitly thread-safe, we create a copy.
        # This ensures the image data is independent of the network buffer.
        image_for_display = QImage(frame.raw_data, frame.width, frame.height, bytes_per_line, q_image_format).copy()

        self.new_frame_signal.emit(
            image_for_display,
            frame.raw_data,
            frame.id1,
            frame.id2,
            frame.id3,
            frame.server_timestamp.isoformat(),
            frame.width,
            frame.height,
            frame.compression,
            frame.color_mode,
            frame.bit_depth,
        )

        self._frame_counter += 1
        now = time.time()
        elapsed = now - self._fps_last_time
        if elapsed >= self.FPS_UPDATE_INTERVAL_SECONDS:
            fps = self._frame_counter / elapsed
            self.fps_update_signal.emit(fps)
            self._frame_counter, self._fps_last_time = 0, now

    def run_single_shot(self, settings: SingleShotSettings, save_to_db: bool) -> None:
        """
        Worker method to execute a single shot action.

        It triggers a single shot using the API and emits a signal upon
        completion with the result.
        """
        logger.info("Executing single shot in worker thread...")
        self._is_cancelled = False
        try:
            response = self.api.trigger_single_shot(settings, save_to_database=save_to_db)
            if not self._is_cancelled:
                self.control_action_finished_signal.emit("single_shot", response)
        except DeviceError as e:
            logger.error(f"Single shot failed: {e}", exc_info=True)
            self.critical_error_signal.emit("Single Shot Error", str(e))
        except Exception as e:
            logger.error(f"An unexpected error occurred during single shot: {e}", exc_info=True)
            self.critical_error_signal.emit("Unexpected Error", str(e))
        finally:
            self.finished_signal.emit()

    def run_multi_shot(self, settings: MultiShotSettings, save_to_database: bool) -> None:
        """
        Worker method to execute a multi-shot action.

        It triggers a multi shot using the API and emits a signal upon
        completion with the result.
        """
        logger.info("Executing multi shot in worker thread...")
        self._is_cancelled = False
        try:
            response = self.api.trigger_multi_shot(settings, save_to_database=save_to_database)
            if not self._is_cancelled:
                self.control_action_finished_signal.emit("multi_shot", response)
        except DeviceError as e:
            logger.error(f"Multi shot failed: {e}", exc_info=True)
            self.critical_error_signal.emit("Multi Shot Error", str(e))
        except Exception as e:
            logger.error(f"An unexpected error occurred during multi shot: {e}", exc_info=True)
            self.critical_error_signal.emit("Unexpected Error", str(e))
        finally:
            self.finished_signal.emit()

    def run_video(self, settings: VideoSettings, save_to_database: bool) -> None:
        """
        Worker method to execute a video capture action.

        It triggers a video capture using the API and emits a signal upon
        completion with the result.
        """
        logger.info("Executing video capture in worker thread...")
        self._is_cancelled = False
        try:
            response = self.api.trigger_video(settings, save_to_database=save_to_database)
            if not self._is_cancelled:
                self.control_action_finished_signal.emit("video", response)
        except DeviceError as e:
            logger.error(f"Video capture failed: {e}", exc_info=True)
            self.critical_error_signal.emit("Video Error", str(e))
        except Exception as e:
            logger.error(f"An unexpected error occurred during video capture: {e}", exc_info=True)
            self.critical_error_signal.emit("Unexpected Error", str(e))
        finally:
            self.finished_signal.emit()
