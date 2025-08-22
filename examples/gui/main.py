from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

from pydantic import ValidationError
from PyQt6.QtCore import QByteArray, Qt, QThread, QThreadPool, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QImage, QPixmap
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from droptical_api_client import (
    AllSettings,
    BaseApiModel,
    MachineInfo,
    MultiShotResponse,
    MultiShotSettings,
    SingleShotResponse,
    SingleShotSettings,
    VideoResponse,
    VideoSettings,
)

# This block allows the example to be run without installing the package.
# It adds the project's 'src' directory to the Python path.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(project_root, "src"))

from examples.gui.api_bridge import BitDepth, ColorMode, CompressionAlgorithm, GuiApiBridge  # noqa: E402
from examples.gui.frame_saver import FrameSaver  # noqa: E402
from examples.gui.media_fetcher import MediaFetcher  # noqa: E402

logger = logging.getLogger("ClientGUI")


class MainWindow(QMainWindow):
    """The main application window with integrated media display."""

    _resolve_conflict_signal = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        logger.info("Initializing MainWindow...")
        self.setWindowTitle("droptical API - GUI Example")
        self.setGeometry(100, 100, 950, 850)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        self.worker_thread: QThread | None = None
        self.worker: GuiApiBridge | None = None
        self.current_action_type: str | None = None
        self.progress_dialog: QProgressDialog | None = None
        self.active_workers: list[tuple[QThread, MediaFetcher]] = []
        self.current_pixmap: QPixmap | None = None
        self.latest_image: QImage | None = None

        self.save_options: dict[str, Any] = {}
        self.stream_frame_count = 0
        self.saved_frame_count = 0

        self.ui_frame_counter = 0
        self.ui_fps_last_time = 0.0

        self.save_fps_frame_counter = 0
        self.save_fps_last_time = 0.0

        self.stream_info_text = "Not streaming"
        self.stream_fps_text = "FPS: --"

        self._setup_ui()

        self.display_update_timer = QTimer(self)
        self.display_update_timer.setInterval(33)  # ~30 FPS refresh rate
        self.display_update_timer.timeout.connect(self.refresh_display)

        logger.info("MainWindow initialization complete.")

    def _setup_ui(self) -> None:
        """Sets up the main structure of the application's user interface."""
        top_controls_layout = QHBoxLayout()
        ip_label = QLabel("Device IP / Hostname:")
        self.ip_input = QLineEdit("127.0.0.1")
        self.connect_button = QPushButton("Initialize Device")
        self.disconnect_button = QPushButton("Change Device")
        self.disconnect_button.setEnabled(False)

        top_controls_layout.addWidget(ip_label)
        top_controls_layout.addWidget(self.ip_input)
        top_controls_layout.addWidget(self.connect_button)
        top_controls_layout.addWidget(self.disconnect_button)
        self.main_layout.addLayout(top_controls_layout)

        self.tabs = QTabWidget()
        self.tabs.setEnabled(False)
        self.main_layout.addWidget(self.tabs)

        self.stream_tab = QWidget()
        self.control_tab = QWidget()

        self.tabs.addTab(self.stream_tab, "Live Stream")
        self.tabs.addTab(self.control_tab, "Control")

        self._create_stream_tab()
        self._create_control_tab()
        self._setup_status_bar()

        self.connect_button.clicked.connect(self.connect_to_device)
        self.disconnect_button.clicked.connect(self.disconnect_from_device)

    def _setup_status_bar(self) -> None:
        """Configures the status bar to display real-time information."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.ui_fps_label = QLabel("UI FPS: --")
        self.save_fps_label = QLabel("Save FPS: --")
        self.status_bar.addPermanentWidget(self.ui_fps_label)
        self.status_bar.addPermanentWidget(self.save_fps_label)
        self.status_bar.showMessage("Ready.")

    def _create_stream_tab(self) -> None:
        """Builds the UI elements for the live stream tab."""
        layout = QVBoxLayout(self.stream_tab)
        self.video_display_label = QLabel("No Video Signal")
        self.video_display_label.setMinimumSize(640, 480)
        self.video_display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_display_label.setStyleSheet("QLabel { background-color: #303030; color: #999; border: 1px solid #555; }")
        font = self.video_display_label.font()
        font.setPointSize(16)
        self.video_display_label.setFont(font)

        bottom_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Stream")
        self.stop_button = QPushButton("Stop Stream")
        self.save_button = QPushButton("Save Frame")
        self.stop_button.setEnabled(False)
        self.save_button.setEnabled(False)

        stream_controls_layout = QVBoxLayout()
        stream_controls_layout.addWidget(self.start_button)
        stream_controls_layout.addWidget(self.stop_button)
        stream_controls_layout.addWidget(self.save_button)
        stream_controls_layout.addStretch()

        bottom_layout.addLayout(stream_controls_layout)

        save_groupbox = QGroupBox("Frame Saving")
        save_groupbox.setCheckable(True)
        save_groupbox.setObjectName("save_groupbox")
        save_groupbox.setChecked(False)

        save_layout = QFormLayout()

        self.save_path_input = QLineEdit()
        self.save_path_input.setPlaceholderText("Select a folder to save...")
        self.save_path_button = QPushButton("Browse...")
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.save_path_input)
        path_layout.addWidget(self.save_path_button)

        self.save_mode_combo = QComboBox()
        self.save_mode_combo.addItems(["Save every frame", "Save every Nth frame", "Save a number of frames"])

        self.save_nth_frame_spinbox = QSpinBox()
        self.save_nth_frame_spinbox.setMinimum(2)
        self.save_nth_frame_spinbox.setMaximum(1000)
        self.save_nth_frame_label = QLabel("Every Nth frame:")

        self.save_total_frames_spinbox = QSpinBox()
        self.save_total_frames_spinbox.setMinimum(1)
        self.save_total_frames_spinbox.setMaximum(10000)
        self.save_total_frames_label = QLabel("Number of frames:")

        save_layout.addRow("Save Path:", path_layout)
        save_layout.addRow("Mode:", self.save_mode_combo)
        save_layout.addRow(self.save_nth_frame_label, self.save_nth_frame_spinbox)
        save_layout.addRow(self.save_total_frames_label, self.save_total_frames_spinbox)

        save_groupbox.setLayout(save_layout)
        bottom_layout.addWidget(save_groupbox)
        bottom_layout.addStretch(1)

        layout.addWidget(self.video_display_label, 1)

        self.stream_info_label = QLabel("Not streaming")
        font = self.stream_info_label.font()
        font.setFamily("Monospace")
        self.stream_info_label.setFont(font)
        self.stream_info_label.setStyleSheet("QLabel { background-color: #282828; color: #ddd; padding: 8px; border-radius: 4px; }")
        self.stream_info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.stream_info_label.setWordWrap(True)
        self.stream_info_label.hide()
        layout.addWidget(self.stream_info_label)
        layout.addLayout(bottom_layout)

        self.start_button.clicked.connect(self.start_stream_process)
        self.stop_button.clicked.connect(self.stop_stream_process)
        self.save_button.clicked.connect(self.save_current_frame)
        self.save_path_button.clicked.connect(self._select_save_directory)
        save_groupbox.toggled.connect(self._toggle_save_options)
        self.save_mode_combo.currentIndexChanged.connect(self._update_save_mode_ui)

        self._toggle_save_options(False)
        self._update_save_mode_ui(0)

    def _toggle_save_options(self, checked: bool) -> None:
        """
        Handles the toggling of the save options group box.

        The QGroupBox itself handles enabling/disabling child widgets. This
        slot is primarily needed to update the visibility of mode-specific
        controls (like the 'Nth frame' spinbox). The `checked` parameter is
        not used because the groupbox manages the enabled state automatically.
        """
        self._update_save_mode_ui(self.save_mode_combo.currentIndex())

    def _update_save_mode_ui(self, index: int) -> None:
        """Show/hide spinboxes based on the selected save mode."""
        is_enabled = self.save_mode_combo.isEnabled()
        self.save_nth_frame_label.setVisible(index == 1 and is_enabled)
        self.save_nth_frame_spinbox.setVisible(index == 1 and is_enabled)
        self.save_total_frames_label.setVisible(index == 2 and is_enabled)
        self.save_total_frames_spinbox.setVisible(index == 2 and is_enabled)

    def _select_save_directory(self) -> None:
        """Open a dialog to select a directory for saving frames."""
        path = QFileDialog.getExistingDirectory(self, "Select Save Directory")
        if path:
            self.save_path_input.setText(path)

    def _create_control_tab(self) -> None:
        """Builds the UI elements for the control tab."""
        layout = QVBoxLayout(self.control_tab)
        control_tabs = QTabWidget()
        layout.addWidget(control_tabs)
        single_shot_widget = self._create_single_shot_tab()
        multi_shot_widget = self._create_multi_shot_tab()
        video_widget = self._create_video_tab()
        control_tabs.addTab(single_shot_widget, "Single Shot")
        control_tabs.addTab(multi_shot_widget, "Multi Shot")
        control_tabs.addTab(video_widget, "Video")

    def _create_single_shot_tab(self) -> QWidget:
        """Creates the UI for the single shot control panel."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        form_layout = QFormLayout()
        self.ss_use_ext_trigger = QCheckBox()

        self.ss_flash_delay = QSpinBox()
        self.ss_flash_delay.setMinimum(SingleShotSettings.FLASH_DELAY_MIN)
        self.ss_flash_delay.setMaximum(SingleShotSettings.FLASH_DELAY_MAX)
        self.ss_flash_delay.setSingleStep(1)
        self.ss_flash_delay.setSuffix(" µs")
        self.ss_flash_delay.setValue(SingleShotSettings.FLASH_DELAY_MIN)

        self.ss_flash_delay2_label = QLabel("Flash Delay 2:")
        self.ss_flash_delay2 = QSpinBox()
        self.ss_flash_delay2.setMinimum(SingleShotSettings.FLASH_DELAY2_MIN)
        self.ss_flash_delay2.setMaximum(SingleShotSettings.FLASH_DELAY2_MAX)
        self.ss_flash_delay2.setSingleStep(1)
        self.ss_flash_delay2.setSuffix(" µs")
        self.ss_flash_delay2.setValue(SingleShotSettings.FLASH_DELAY2_MIN)

        self.ss_power_factor = QDoubleSpinBox()
        self.ss_power_factor.setMinimum(SingleShotSettings.POWER_FACTOR_MIN)
        self.ss_power_factor.setMaximum(SingleShotSettings.POWER_FACTOR_MAX)
        self.ss_power_factor.setSingleStep(0.1)
        self.ss_power_factor.setSuffix("%")
        self.ss_power_factor.setValue(50.0)
        self.ss_power_factor.setDecimals(1)

        self.ss_save_to_db = QCheckBox()
        form_layout.addRow("Use External Trigger:", self.ss_use_ext_trigger)
        form_layout.addRow("Flash Delay:", self.ss_flash_delay)
        form_layout.addRow(self.ss_flash_delay2_label, self.ss_flash_delay2)
        form_layout.addRow("Power Factor:", self.ss_power_factor)
        form_layout.addRow("Save to Database:", self.ss_save_to_db)

        self.toggle_ss_flash_delay2(False)

        self.ss_trigger_button = QPushButton("Trigger Single Shot")
        self.ss_trigger_button.clicked.connect(self.run_single_shot)

        self.ss_output = QTextEdit()
        self.ss_output.setReadOnly(True)

        left_layout.addLayout(form_layout)
        left_layout.addWidget(self.ss_trigger_button)
        left_layout.addWidget(self.ss_output)
        left_layout.addStretch()

        self.ss_image_label = QLabel("Image will be displayed here")
        self.ss_image_label.setMinimumSize(400, 300)
        self.ss_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ss_image_label.setStyleSheet("QLabel { background-color: #282828; color: #888; border: 1px solid #444; }")

        layout.addWidget(left_panel, 1)
        layout.addWidget(self.ss_image_label, 1)
        return widget

    def _create_multi_shot_tab(self) -> QWidget:
        """Creates the UI for the multi shot control panel."""
        widget = QWidget()
        layout = QHBoxLayout(widget)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        form_layout = QFormLayout()

        self.ms_use_ext_trigger = QCheckBox()
        self.ms_save_all_images = QCheckBox()

        self.ms_flash_delay = QSpinBox()
        self.ms_flash_delay.setMinimum(MultiShotSettings.FLASH_DELAY_MIN)
        self.ms_flash_delay.setMaximum(MultiShotSettings.FLASH_DELAY_MAX)
        self.ms_flash_delay.setSuffix(" µs")

        self.ms_flash_delay2_label = QLabel("Flash Delay 2:")
        self.ms_flash_delay2 = QSpinBox()
        self.ms_flash_delay2.setMinimum(MultiShotSettings.FLASH_DELAY2_MIN)
        self.ms_flash_delay2.setMaximum(MultiShotSettings.FLASH_DELAY2_MAX)
        self.ms_flash_delay2.setSuffix(" µs")

        self.ms_power_factor = QDoubleSpinBox()
        self.ms_power_factor.setMinimum(MultiShotSettings.POWER_FACTOR_MIN)
        self.ms_power_factor.setMaximum(MultiShotSettings.POWER_FACTOR_MAX)
        self.ms_power_factor.setSingleStep(0.1)
        self.ms_power_factor.setSuffix("%")
        self.ms_power_factor.setDecimals(1)

        self.ms_frequency = QDoubleSpinBox()
        self.ms_frequency.setMinimum(MultiShotSettings.FREQUENCY_MIN)
        self.ms_frequency.setMaximum(MultiShotSettings.FREQUENCY_MAX)
        self.ms_frequency.setSingleStep(0.1)
        self.ms_frequency.setSuffix(" Hz")

        self.ms_mode_select = QComboBox()
        self.ms_mode_select.addItems(["Image count", "Trigger count"])
        self.ms_trigger_count = QSpinBox()
        self.ms_trigger_count.setMinimum(MultiShotSettings.TRIGGER_COUNT_MIN)
        self.ms_trigger_count.setMaximum(MultiShotSettings.TRIGGER_COUNT_MAX)

        count_layout = QHBoxLayout()
        count_layout.addWidget(self.ms_mode_select)
        count_layout.addWidget(self.ms_trigger_count)

        form_layout.addRow("Use External Trigger:", self.ms_use_ext_trigger)
        form_layout.addRow("Save All Images:", self.ms_save_all_images)
        form_layout.addRow("Mode & Count:", count_layout)
        form_layout.addRow(self._create_header_label("Flash Settings"))
        form_layout.addRow("Flash Delay:", self.ms_flash_delay)
        form_layout.addRow(self.ms_flash_delay2_label, self.ms_flash_delay2)
        form_layout.addRow(self._create_header_label("Valve Control"))
        form_layout.addRow("Power Factor:", self.ms_power_factor)
        form_layout.addRow("Frequency:", self.ms_frequency)
        self.toggle_ms_flash_delay2(False)

        self.ms_trigger_button = QPushButton("Trigger Multi Shot")
        self.ms_trigger_button.clicked.connect(self.run_multi_shot)

        self.ms_output = QTextEdit()
        self.ms_output.setReadOnly(True)

        left_layout.addLayout(form_layout)
        left_layout.addWidget(self.ms_trigger_button)
        left_layout.addWidget(self.ms_output)
        left_layout.addStretch()

        self.ms_scroll_area = QScrollArea()
        self.ms_scroll_area.setWidgetResizable(True)
        self.ms_image_container = QWidget()
        self.ms_image_layout = QHBoxLayout(self.ms_image_container)
        self.ms_scroll_area.setWidget(self.ms_image_container)

        layout.addWidget(left_panel, 1)
        layout.addWidget(self.ms_scroll_area, 1)

        return widget

    def _create_video_tab(self) -> QWidget:
        """Creates the UI for the video control panel."""
        widget = QWidget()
        layout = QHBoxLayout(widget)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        form_layout = QFormLayout()

        self.vid_use_ext_trigger = QCheckBox()
        form_layout.addRow("Use External Trigger:", self.vid_use_ext_trigger)

        self.vid_mode_tabs = QTabWidget()
        self.constant_mode_widget = QWidget()
        constant_layout = QFormLayout(self.constant_mode_widget)
        constant_layout.setContentsMargins(0, 0, 0, 0)

        self.vid_const_flash_delay = QSpinBox()
        self.vid_const_flash_delay.setSuffix(" µs")
        self.vid_const_flash_delay.setMinimum(VideoSettings.FLASH_DELAY_MIN)
        self.vid_const_flash_delay.setMaximum(VideoSettings.FLASH_DELAY_MAX)

        self.vid_const_flash_delay2_label = QLabel("Flash Delay 2:")
        self.vid_const_flash_delay2 = QSpinBox()
        self.vid_const_flash_delay2.setSuffix(" µs")
        self.vid_const_flash_delay2.setMinimum(VideoSettings.FLASH_DELAY2_MIN)
        self.vid_const_flash_delay2.setMaximum(VideoSettings.FLASH_DELAY2_MAX)
        self.vid_const_image_count = QSpinBox()

        constant_layout.addRow("Flash Delay:", self.vid_const_flash_delay)
        constant_layout.addRow(self.vid_const_flash_delay2_label, self.vid_const_flash_delay2)
        constant_layout.addRow("Image Count:", self.vid_const_image_count)
        self.vid_mode_tabs.addTab(self.constant_mode_widget, "Constant Mode")

        self.increment_mode_widget = QWidget()
        increment_layout = QFormLayout(self.increment_mode_widget)
        increment_layout.setContentsMargins(0, 0, 0, 0)
        self.vid_inc_start_time = QSpinBox()
        self.vid_inc_start_time.setMinimum(VideoSettings.START_TIME_MIN)
        self.vid_inc_start_time.setMaximum(VideoSettings.START_TIME_MAX)
        self.vid_inc_start_time.setSuffix(" µs")
        self.vid_inc_end_time = QSpinBox()
        self.vid_inc_end_time.setMinimum(VideoSettings.END_TIME_MIN)
        self.vid_inc_end_time.setMaximum(VideoSettings.END_TIME_MAX)
        self.vid_inc_end_time.setSuffix(" µs")
        self.vid_inc_time_increment = QSpinBox()
        self.vid_inc_time_increment.setMinimum(VideoSettings.TIME_INCREMENT_MIN)
        self.vid_inc_time_increment.setSuffix(" µs")
        self.vid_inc_time_increment.setValue(VideoSettings.TIME_INCREMENT_MIN)
        self.vid_inc_image_count = QLineEdit("0")
        self.vid_inc_image_count.setReadOnly(True)
        increment_layout.addRow("Start Time:", self.vid_inc_start_time)
        increment_layout.addRow("End Time:", self.vid_inc_end_time)
        increment_layout.addRow("Time Increment:", self.vid_inc_time_increment)
        increment_layout.addRow("Image Count (calc.):", self.vid_inc_image_count)
        self.vid_mode_tabs.addTab(self.increment_mode_widget, "Increment Mode")
        form_layout.addRow(self.vid_mode_tabs)

        self.vid_inc_start_time.valueChanged.connect(self._update_video_image_count)
        self.vid_inc_end_time.valueChanged.connect(self._update_video_image_count)
        self.vid_inc_time_increment.valueChanged.connect(self._update_video_image_count)

        form_layout.addRow(self._create_header_label("Export"))
        self.vid_stitch_count = QSpinBox()
        self.vid_stitch_count.setMinimum(VideoSettings.STITCH_COUNT_MIN)
        self.vid_stitch_count.setMaximum(VideoSettings.STITCH_COUNT_MAX)
        self.vid_export_fps = QSpinBox()
        self.vid_export_fps.setMinimum(VideoSettings.FPS_MIN)
        self.vid_export_fps.setMaximum(VideoSettings.FPS_MAX)
        form_layout.addRow("Stitch Count:", self.vid_stitch_count)
        form_layout.addRow("Video FPS:", self.vid_export_fps)

        form_layout.addRow(self._create_header_label("Valve Control"))
        self.vid_power_factor = QDoubleSpinBox()
        self.vid_power_factor.setMinimum(VideoSettings.POWER_FACTOR_MIN)
        self.vid_power_factor.setMaximum(VideoSettings.POWER_FACTOR_MAX)
        self.vid_power_factor.setSingleStep(0.1)
        self.vid_frequency = QDoubleSpinBox()
        self.vid_frequency.setMinimum(VideoSettings.FREQUENCY_MIN)
        self.vid_frequency.setMaximum(VideoSettings.FREQUENCY_MAX)
        self.vid_frequency.setSingleStep(0.1)
        self.vid_frequency.setSuffix(" Hz")
        form_layout.addRow("Power Factor:", self.vid_power_factor)
        form_layout.addRow("Trigger Frequency:", self.vid_frequency)
        left_layout.addLayout(form_layout)

        self.vid_trigger_button = QPushButton("Trigger Video")
        self.vid_trigger_button.clicked.connect(self.run_video)
        self.vid_output = QTextEdit()
        self.vid_output.setReadOnly(True)
        left_layout.addWidget(self.vid_trigger_button)
        left_layout.addWidget(self.vid_output)
        left_layout.addStretch()

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.video_player = QMediaPlayer()
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumSize(400, 300)
        self.video_player.setVideoOutput(self.video_widget)
        self.video_player.setLoops(QMediaPlayer.Loops.Infinite)
        video_controls = QHBoxLayout()

        self.vid_image_label = QLabel("Video preview image will be displayed here")
        self.vid_image_label.setMinimumSize(400, 300)
        self.vid_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vid_image_label.setStyleSheet("QLabel { background-color: #282828; color: #888; border: 1px solid #444; }")

        self.vid_play_button = QPushButton("Play")
        self.vid_pause_button = QPushButton("Pause")
        self.vid_stop_button = QPushButton("Stop")
        self.vid_play_button.setEnabled(False)
        self.vid_pause_button.setEnabled(False)
        self.vid_stop_button.setEnabled(False)
        video_controls.addWidget(self.vid_play_button)
        video_controls.addWidget(self.vid_pause_button)
        video_controls.addWidget(self.vid_stop_button)

        self.vid_play_button.clicked.connect(self.play_video)
        self.vid_pause_button.clicked.connect(self.video_player.pause)
        self.vid_stop_button.clicked.connect(self.video_player.stop)
        self.video_player.playbackStateChanged.connect(self.update_video_button_state)

        right_layout.addWidget(self.video_widget)
        right_layout.addLayout(video_controls)
        right_layout.addStretch()

        layout.addWidget(left_panel, 1)
        layout.addWidget(right_panel, 1)

        self.toggle_vid_flash_delay2(False)

        return widget

    def _update_video_image_count(self) -> None:
        """Calculates and updates the image count for the video's increment mode."""
        start_time = self.vid_inc_start_time.value()
        end_time = self.vid_inc_end_time.value()
        time_increment = self.vid_inc_time_increment.value()

        if end_time < start_time or time_increment == 0:
            self.vid_inc_image_count.setText("N/A")
            return

        image_count = round(((end_time - start_time) / time_increment) + 1)
        self.vid_inc_image_count.setText(str(int(image_count)))

    def _create_header_label(self, text: str) -> QLabel:
        """Creates a less obtrusive QLabel for section headers."""
        label = QLabel(text)
        font = label.font()
        font.setPointSize(font.pointSize() - 1)
        label.setFont(font)
        label.setStyleSheet("color: #999; margin-top: 10px;")
        return label

    def toggle_ss_flash_delay2(self, is_checked: bool) -> None:
        """Toggles visibility of the second flash delay for single shot."""
        self.ss_flash_delay2_label.setVisible(is_checked)
        self.ss_flash_delay2.setVisible(is_checked)

    def toggle_ms_flash_delay2(self, is_checked: bool) -> None:
        """Toggles visibility of the second flash delay for multi shot."""
        self.ms_flash_delay2_label.setVisible(is_checked)
        self.ms_flash_delay2.setVisible(is_checked)

    def toggle_vid_flash_delay2(self, is_double_flash: bool) -> None:
        """Toggles visibility of the second flash delay setting for video mode."""
        self.vid_const_flash_delay2_label.setVisible(is_double_flash)
        self.vid_const_flash_delay2.setVisible(is_double_flash)

    def _execute_worker_action(self, action_name: str, worker_starter_func: str, settings: BaseApiModel | None = None, save_to_db: bool = False) -> None:
        """Manages the creation, configuration, and execution of a worker thread."""
        ip = self.ip_input.text()
        if not ip:
            self.show_critical_error("Input Error", "Please provide a valid IP address.")
            return

        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "Busy", "Another operation is already in progress.")
            return

        self.current_action_type = action_name
        self.set_ui_for_action(True, action_name)

        self.worker_thread = QThread()
        self.worker = GuiApiBridge(ip_address=ip)
        self.worker.moveToThread(self.worker_thread)

        self.worker.finished_signal.connect(self._on_worker_finished)
        self.worker.critical_error_signal.connect(self.show_critical_error)
        self.worker.status_update_signal.connect(self.status_bar.showMessage)

        if action_name == "stream":
            self._resolve_conflict_signal.connect(self.worker.resolve_conflict_and_continue)
            self.worker.new_frame_signal.connect(self.update_video_display)
            self.worker.production_mode_conflict.connect(self.handle_production_mode_conflict)
            self.worker.fps_update_signal.connect(self.update_fps_display)
            self.worker_thread.started.connect(self.worker.start_raw_stream_sequence)
        elif action_name == "connect":
            self.worker.connection_successful_signal.connect(self._on_connection_successful)
            worker_method = getattr(self.worker, worker_starter_func)
            self.worker_thread.started.connect(worker_method)
        else:
            self.worker.control_action_finished_signal.connect(self.on_control_action_finished)
            worker_method = getattr(self.worker, worker_starter_func)
            self.worker_thread.started.connect(lambda: worker_method(settings, save_to_db))

        self.progress_dialog = QProgressDialog(f"Executing {action_name.replace('_', ' ')}...", "Cancel", 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.canceled.connect(self.worker.cancel_action)

        if action_name == "stream" or action_name == "connect":
            self.worker.handshake_finished_signal.connect(self.progress_dialog.accept)

        self.progress_dialog.show()
        self.worker_thread.start()

    def _on_worker_finished(self) -> None:
        """Slot for cleaning up the worker thread after it has finished its task."""
        logger.info("Worker has finished. Cleaning up thread.")

        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        if self.worker:
            try:
                self._resolve_conflict_signal.disconnect(self.worker.resolve_conflict_and_continue)
            except TypeError:
                pass

        if self.current_action_type:
            self.set_ui_for_action(False, self.current_action_type)
            self.current_action_type = None

        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()

        self.worker_thread, self.worker = None, None
        self.status_bar.showMessage("Ready.", 5000)

    def _on_connection_successful(self, machine_info: MachineInfo, all_settings: AllSettings) -> None:
        """Handles a successful connection by enabling and populating the UI."""
        logger.info("Successfully connected to device. Populating UI with settings.")
        self.status_bar.showMessage(f"Connected to {machine_info.analysisunit.hw}. Populating settings...", 10000)
        self._populate_ui_with_settings(all_settings)
        self.tabs.setEnabled(True)
        self.connect_button.setEnabled(False)
        self.ip_input.setEnabled(False)
        self.disconnect_button.setEnabled(True)

    def _populate_ui_with_settings(self, settings: AllSettings) -> None:
        """Fills all UI input fields with the values from the fetched settings object."""
        ss = settings.single_shot_settings
        self.ss_use_ext_trigger.setChecked(ss.use_external_trigger)
        self.toggle_ss_flash_delay2(ss.double_flash_active)
        self.ss_flash_delay.setValue(ss.flash_delay or 0)
        self.ss_flash_delay2.setValue(ss.flash_delay2 or 0)
        self.ss_power_factor.setValue(ss.power_factor or 0.0)

        ms = settings.multi_shot_settings
        self.ms_use_ext_trigger.setChecked(ms.use_external_trigger)
        self.ms_save_all_images.setChecked(ms.save_all_images)
        self.ms_mode_select.setCurrentText("Image count" if ms.capture_mode_on else "Trigger count")
        self.toggle_ms_flash_delay2(ms.double_flash_active)
        self.ms_flash_delay.setValue(ms.flash_delay or 0)
        self.ms_flash_delay2.setValue(ms.flash_delay2 or 0)
        self.ms_power_factor.setValue(ms.power_factor or 0.0)
        self.ms_trigger_count.setValue(ms.trigger_count or 0)
        self.ms_frequency.setValue(ms.frequency or 0.0)

        vs = settings.video_settings
        self.vid_use_ext_trigger.setChecked(vs.use_external_trigger)
        self.vid_mode_tabs.setCurrentIndex(0 if vs.use_constant_mode else 1)
        self.vid_stitch_count.setValue(vs.stitch_count or 0)
        self.vid_export_fps.setValue(vs.fps or 1)
        self.vid_power_factor.setValue(vs.power_factor or 0.0)
        self.vid_frequency.setValue(vs.frequency or 0.0)
        self.toggle_vid_flash_delay2(vs.double_flash_active)
        self.vid_const_flash_delay.setValue(vs.flash_delay or 0)
        self.vid_const_image_count.setValue(vs.image_count or 0)
        self.vid_const_flash_delay2.setValue(vs.flash_delay2 or 0)
        self.vid_inc_start_time.setValue(vs.start_time or 0)
        self.vid_inc_end_time.setValue(vs.end_time or 0)
        self.vid_inc_time_increment.setValue(vs.time_increment or 1)
        self._update_video_image_count()

    def connect_to_device(self) -> None:
        """Starts the connection and settings-fetching process."""
        self._execute_worker_action(action_name="connect", worker_starter_func="run_connection_handshake")

    def start_stream_process(self) -> None:
        """Initiates the process to start a live video stream."""
        logger.info("Start stream process initiated.")

        self.save_options.clear()
        save_groupbox = self.findChild(QGroupBox, "save_groupbox")
        if save_groupbox and save_groupbox.isChecked():
            path = self.save_path_input.text()
            if not path:
                QMessageBox.warning(self, "Missing Save Path", "Please select a valid save path.")
                return

            os.makedirs(path, exist_ok=True)
            self.save_options = {
                "enabled": True,
                "path": path,
                "mode": self.save_mode_combo.currentIndex(),
                "nth_frame": self.save_nth_frame_spinbox.value(),
                "total_frames": self.save_total_frames_spinbox.value(),
            }
            logger.info(f"Frame saving enabled with options: {self.save_options}")

        self.stream_frame_count = 0
        self.saved_frame_count = 0
        self.latest_image = None
        self.ui_frame_counter = 0
        self.ui_fps_last_time = time.time()
        self.save_fps_frame_counter = 0
        self.save_fps_last_time = time.time()
        self.display_update_timer.start()
        if self.stream_info_label:
            self.stream_info_label.show()

        self._execute_worker_action("stream", "start_raw_stream_sequence")

    def stop_stream_process(self) -> None:
        """Stops the currently running live video stream."""
        self.display_update_timer.stop()
        if self.worker:
            self.worker.cancel_action()

    def disconnect_from_device(self) -> None:
        """Resets the UI to the disconnected state."""
        logger.info("Disconnecting from device.")
        self.tabs.setEnabled(False)
        self.connect_button.setEnabled(True)
        self.ip_input.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.status_bar.showMessage("Disconnected.", 5000)

    def start_image_fetch(self, url: str, target_label: QLabel) -> None:
        """Starts a thread to fetch an image from a URL and display it."""
        thread = QThread()
        fetcher = MediaFetcher(url)
        fetcher.moveToThread(thread)

        worker_pair = (thread, fetcher)
        self.active_workers.append(worker_pair)

        def _cleanup_worker() -> None:
            """A closure to safely remove the worker pair from the active list."""
            try:
                self.active_workers.remove(worker_pair)
                logger.info(f"Cleaned up image fetcher for {url}. Active workers: {len(self.active_workers)}")
            except ValueError:
                logger.warning(f"Image fetcher for {url} was already cleaned up.")

        thread.started.connect(fetcher.run)
        fetcher.media_fetched.connect(lambda image_data: self.display_image_on_label(image_data, target_label))
        fetcher.error_occurred.connect(lambda error_msg: target_label.setText(f"Error:\n{error_msg[:100]}"))
        fetcher.finished.connect(thread.quit)
        thread.finished.connect(fetcher.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(_cleanup_worker)
        thread.start()

    def run_single_shot(self) -> None:
        """Gathers settings from the UI and executes a single shot action."""
        self.ss_output.clear()
        self.ss_image_label.setText("Validating settings...")
        try:
            settings = SingleShotSettings(
                useExternalTrigger=self.ss_use_ext_trigger.isChecked(),
                doubleFlashActive=self.ss_flash_delay2.isVisible(),
                flashDelay=self.ss_flash_delay.value(),
                flashDelay2=self.ss_flash_delay2.value(),
                powerFactor=self.ss_power_factor.value(),
            )
            save_to_db = self.ss_save_to_db.isChecked()
            self.ss_output.setText("Executing single shot...")
            self._execute_worker_action("single_shot", "run_single_shot", settings, save_to_db)
        except ValidationError as e:
            self.show_critical_error("Settings Error", f"Invalid single shot settings:\n{e}")
            self.ss_output.clear()
            self.ss_image_label.setText("Action failed.")

    def run_multi_shot(self) -> None:
        """Gathers settings from the UI and executes a multi shot action."""
        self.ms_output.clear()
        while (child := self.ms_image_layout.takeAt(0)) is not None:
            if widget := child.widget():
                widget.deleteLater()
        self.ms_output.setText("Validating settings...")
        try:
            settings = MultiShotSettings(
                useExternalTrigger=self.ms_use_ext_trigger.isChecked(),
                saveAllImages=self.ms_save_all_images.isChecked(),
                captureModeOn=(self.ms_mode_select.currentText() == "Image count"),
                doubleFlashActive=self.ms_flash_delay2.isVisible(),
                flashDelay=self.ms_flash_delay.value(),
                flashDelay2=self.ms_flash_delay2.value(),
                powerFactor=self.ms_power_factor.value(),
                triggerCount=self.ms_trigger_count.value(),
                frequency=self.ms_frequency.value(),
            )
            self.ms_output.setText("Executing multi shot...")
            self._execute_worker_action("multi_shot", "run_multi_shot", settings, save_to_db=False)
        except ValidationError as e:
            self.show_critical_error("Settings Error", f"Invalid multi shot settings:\n{e}")
            self.ms_output.setText("Action failed.")

    def run_video(self) -> None:
        """Gathers settings from the UI and executes a video capture action."""
        self.vid_output.clear()
        self.vid_output.setText("Validating settings...")
        self.video_player.setSource(QUrl())
        self.vid_image_label.setText("Video preview image will be displayed here")
        self.vid_image_label.setPixmap(QPixmap())

        is_constant_mode = self.vid_mode_tabs.currentIndex() == 0

        settings_dict: dict[str, Any] = {
            "useExternalTrigger": self.vid_use_ext_trigger.isChecked(),
            "useConstantMode": is_constant_mode,
            "stitchCount": self.vid_stitch_count.value(),
            "fps": self.vid_export_fps.value(),
            "powerFactor": self.vid_power_factor.value(),
            "frequency": self.vid_frequency.value(),
            "doubleFlashActive": False,
        }

        if is_constant_mode:
            is_double_flash = self.vid_const_flash_delay2.isVisible()
            settings_dict["doubleFlashActive"] = is_double_flash
            settings_dict["flashDelay"] = self.vid_const_flash_delay.value()
            settings_dict["imageCount"] = self.vid_const_image_count.value()
            if is_double_flash:
                settings_dict["flashDelay2"] = self.vid_const_flash_delay2.value()
        else:
            settings_dict["startTime"] = self.vid_inc_start_time.value()
            settings_dict["endTime"] = self.vid_inc_end_time.value()
            settings_dict["timeIncrement"] = self.vid_inc_time_increment.value()

        try:
            settings = VideoSettings(**settings_dict)
            self.vid_output.setText("Executing video capture...")
            self._execute_worker_action("video", "run_video", settings, save_to_db=False)
        except ValidationError as e:
            self.show_critical_error("Settings Error", f"Invalid video settings:\n{e}")
            self.vid_output.setText("Action failed.")

    def set_ui_for_action(self, is_running: bool, action_type: str) -> None:
        """Updates the UI state to reflect whether an action is running or not."""
        save_groupbox = self.findChild(QGroupBox, "save_groupbox")
        if save_groupbox:
            save_groupbox.setEnabled(not is_running)

        if action_type == "stream":
            self.start_button.setEnabled(not is_running)
            self.ip_input.setEnabled(not is_running)
            self.control_tab.setEnabled(not is_running)
            self.stop_button.setEnabled(is_running)
            self.disconnect_button.setEnabled(not is_running)
            if not is_running:
                self.display_update_timer.stop()
                self.disconnect_from_device()
                self.save_button.setEnabled(False)
                self.video_display_label.setText("No Video Signal")
                self.video_display_label.setPixmap(QPixmap())
                self.current_pixmap = None
                if self.stream_info_label:
                    self.stream_info_label.setText("Not streaming")
                    self.stream_info_label.hide()
        else:
            self.ss_trigger_button.setEnabled(not is_running)
            self.ms_trigger_button.setEnabled(not is_running)
            self.vid_trigger_button.setEnabled(not is_running)
            self.stream_tab.setEnabled(not is_running)
            self.ip_input.setEnabled(not is_running)

    def update_video_display(
        self,
        image: QImage,
        raw_data: bytes,
        id1: int,
        id2: int,
        id3: int,
        timestamp: str,
        width: int,
        height: int,
        comp_val: int,
        color_val: int,
        depth_val: int,
    ) -> None:
        """
        Receives frame data, formats it for the overlay, and stores the latest image.
        The actual display rendering is handled by the `refresh_display` slot.
        """
        self.stream_frame_count += 1

        try:
            compression = CompressionAlgorithm(comp_val)
            color_mode = ColorMode(color_val)
            bit_depth = BitDepth(depth_val)
        except ValueError as e:
            logging.error(f"Failed to convert int to enum: {e}")
            return

        info_lines = [
            f"Frame: {self.stream_frame_count}",
            f"Timestamp: {timestamp.split('T')[1]}",
            f"Resolution: {width}x{height}",
            f"Format: {color_mode.name.capitalize()}, {bit_depth.value}b, {compression.name.capitalize()}",
        ]
        self.stream_info_text = "\n".join(info_lines)

        full_info_text = f"{self.stream_fps_text}\n{self.stream_info_text}"
        if self.stream_info_label:
            self.stream_info_label.setText(full_info_text)

        self.latest_image = image

        if not self.save_button.isEnabled():
            self.save_button.setEnabled(True)

        if self.save_options.get("enabled", False):
            self._handle_automatic_frame_saving(raw_data, width, height, image.format())

    def refresh_display(self) -> None:
        """
        Slot for the display timer. Renders the latest frame.
        This method runs at a fixed rate to keep the GUI responsive.
        """
        if self.latest_image is None:
            return

        pixmap = QPixmap.fromImage(self.latest_image)
        self.current_pixmap = pixmap

        scaled_pixmap = pixmap.scaled(self.video_display_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.video_display_label.setPixmap(scaled_pixmap)

        self.ui_frame_counter += 1
        now = time.time()
        elapsed = now - self.ui_fps_last_time
        if elapsed >= 1.0:
            fps = self.ui_frame_counter / elapsed
            self.ui_fps_label.setText(f"UI FPS: {fps:.1f}")
            self.ui_frame_counter, self.ui_fps_last_time = 0, now

        save_elapsed = now - self.save_fps_last_time
        if self.save_options.get("enabled", False):
            if save_elapsed >= 1.0:
                save_fps = self.save_fps_frame_counter / save_elapsed
                self.save_fps_label.setText(f"Save FPS: {save_fps:.1f}")
                self.save_fps_frame_counter, self.save_fps_last_time = 0, now
        elif self.save_fps_label.text() != "Save FPS: --":
            self.save_fps_label.setText("Save FPS: --")

    def _handle_automatic_frame_saving(self, raw_data: bytes, width: int, height: int, img_format: QImage.Format) -> None:
        """Checks if the current frame should be saved based on user settings."""
        if not self.save_options.get("enabled", False):
            return

        should_save = False
        mode = self.save_options["mode"]

        if mode == 0:
            should_save = True
        elif mode == 1:
            if self.stream_frame_count % self.save_options["nth_frame"] == 0:
                should_save = True
        elif mode == 2:
            if self.saved_frame_count < self.save_options["total_frames"]:
                should_save = True

        if should_save:
            self.saved_frame_count += 1
            self._save_frame_async(raw_data, width, height, img_format)

            if mode == 2 and self.saved_frame_count >= self.save_options["total_frames"]:
                self.save_options["enabled"] = False
                logger.info("Frame saving limit reached. Stopping.")
                self.status_bar.showMessage("Frame count reached, saving stopped.", 5000)

    def _save_frame_async(self, raw_data: bytes, width: int, height: int, img_format: QImage.Format) -> None:
        """Creates a FrameSaver task with raw data and submits it to the global thread pool."""
        file_name = f"frame_{self.stream_frame_count:06d}.png"
        file_path = os.path.join(self.save_options["path"], file_name)

        saver = FrameSaver(raw_data, width, height, img_format, file_path)
        saver.signals.finished.connect(self._increment_saved_frame_counter)
        instance = QThreadPool.globalInstance()

        if instance:
            instance.start(saver)

    def _increment_saved_frame_counter(self) -> None:
        """Thread-safe slot to increment the counter for saved frames."""
        self.save_fps_frame_counter += 1

    def update_fps_display(self, fps: float) -> None:
        """Updates the FPS text variable for the overlay."""
        self.stream_fps_text = f"FPS: {fps:.1f}"

    def on_control_action_finished(self, action_type: str, result_model: BaseApiModel) -> None:
        """Handles the result of a control action and updates the UI accordingly."""
        try:
            result_dict = result_model.model_dump(by_alias=True)
            pretty_result = json.dumps(result_dict, indent=2)
            message = f"Success!\n\nResponse:\n{pretty_result}"
        except Exception as e:
            message = f"Received unexpected result type: {type(result_model)}\nError: {e}"
            logger.error(message)

        base_url = f"http://{self.ip_input.text()}"

        if action_type == "single_shot":
            if not isinstance(result_model, SingleShotResponse):
                logger.error(f"Expected SingleShotResponse for 'single_shot', got {type(result_model)}")
                return
            self.ss_output.setText(message)
            if result_model.single_drops and result_model.single_drops[0].p:
                image_path = result_model.single_drops[0].p
                url = f"{base_url}/data/{image_path}"
                self.ss_image_label.setText(f"Fetching image from\n{url}...")
                self.start_image_fetch(url, self.ss_image_label)
            else:
                self.ss_image_label.setText("No image path in response.")

        elif action_type == "multi_shot":
            if not isinstance(result_model, MultiShotResponse):
                logger.error(f"Expected MultiShotResponse for 'multi_shot', got {type(result_model)}")
                return
            self.ms_output.setText(message)
            if not result_model.single_drops:
                label = QLabel("No images in response.")
                self.ms_image_layout.addWidget(label)
            else:
                for drop in result_model.single_drops:
                    if drop.p:
                        image_label = QLabel("Fetching...")
                        image_label.setFixedSize(200, 200)
                        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.ms_image_layout.addWidget(image_label)
                        url = f"{base_url}/data/{drop.p}"
                        self.start_image_fetch(url, image_label)
                self.ms_image_layout.addStretch()

        elif action_type == "video":
            if not isinstance(result_model, VideoResponse):
                logger.error(f"Expected VideoResponse for 'video', got {type(result_model)}")
                return
            self.vid_output.setText(message)
            self.vid_image_label.setText("Video preview image will be displayed here")
            self.vid_image_label.setPixmap(QPixmap())

            if result_model.path_to_video:
                url = f"{base_url}/data/{result_model.path_to_video}"
                self.video_player.setSource(QUrl(url))
                self.video_player.play()
                self.vid_output.append("\n\nVideo loaded. Playback starts automatically.")
            else:
                self.vid_output.append("\n\nNo video path in response.")

            if result_model.path_to_image:
                image_url = f"{base_url}/data/{result_model.path_to_image}"
                self.vid_image_label.setText(f"Fetching image from\n{image_url}...")
                self.start_image_fetch(image_url, self.vid_image_label)
            else:
                self.vid_image_label.setText("No preview image in response.")

        self.status_bar.showMessage(f"{action_type.replace('_', ' ').title()} finished.", 5000)

    def display_image_on_label(self, image_data: QByteArray, label: QLabel) -> None:
        """Displays image data on a given QLabel, scaling it to fit."""
        pixmap = QPixmap()
        if not pixmap.loadFromData(image_data):
            label.setText("Failed to load image data.")
            return
        label.setPixmap(pixmap.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def play_video(self) -> None:
        """Starts video playback if a source is set."""
        source = self.video_player.source()
        if source is None or source.isEmpty():
            QMessageBox.warning(self, "No Video", "No video has been loaded.")
            return
        self.video_player.play()

    def update_video_button_state(self, state: QMediaPlayer.PlaybackState) -> None:
        """Updates the state of video control buttons based on playback state."""
        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        is_paused = state == QMediaPlayer.PlaybackState.PausedState
        is_stopped = state == QMediaPlayer.PlaybackState.StoppedState

        source = self.video_player.source()
        has_source = source is not None and not source.isEmpty()

        self.vid_play_button.setEnabled((is_paused or is_stopped) and has_source)
        self.vid_pause_button.setEnabled(is_playing)
        self.vid_stop_button.setEnabled(is_playing or is_paused)

    def handle_production_mode_conflict(self) -> None:
        """Prompts the user to deactivate production mode if a conflict occurs."""
        reply = QMessageBox.warning(
            self,
            "Mode Conflict",
            "The device is in Production Mode.\n\nDeactivate it to start the stream?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if self.worker:
            if reply == QMessageBox.StandardButton.Yes:
                self._resolve_conflict_signal.emit(True)
            else:
                self.stop_stream_process()

    def show_critical_error(self, title: str, message: str) -> None:
        """Displays a critical error message and resets the UI state."""
        if self.progress_dialog:
            self.progress_dialog.close()

        QMessageBox.critical(self, title, message)
        if self.current_action_type:
            self.set_ui_for_action(False, self.current_action_type)
        self.disconnect_from_device()

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """Handles the window close event, ensuring all threads are stopped."""
        logger.info("Close event triggered. Stopping worker if active.")
        self.video_player.stop()
        if self.worker:
            self.worker.cancel_action()
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.wait(1000)
        if a0:
            a0.accept()

    def save_current_frame(self) -> None:
        """Opens a save dialog to save the currently displayed frame."""
        if not self.current_pixmap:
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Image", "capture.png", "PNG (*.png);;JPEG (*.jpg)")
        if file_path:
            self.current_pixmap.save(file_path)
            self.status_bar.showMessage(f"Image saved to {file_path}", 5000)


def setup_client_logging(log_file: str = "client.log") -> None:
    """Configures logging for the client application."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-8s] %(name)-14s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )


if __name__ == "__main__":
    setup_client_logging()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
