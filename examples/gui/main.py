from __future__ import annotations

import logging
import os
import pathlib
import sys
import time
from datetime import datetime
from typing import Any

import shiboken6
from pydantic import ValidationError
from PySide6.QtCore import QByteArray, QObject, QPoint, QRect, QRunnable, QSize, Qt, QThread, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QColor, QIcon, QImage, QPainter, QPalette, QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


def _is_deleted(obj: object) -> bool:
    """True if the underlying C++ object has been destroyed (PySide6/shiboken6
    equivalent of PyQt's sip.isdeleted)."""
    return not shiboken6.isValid(obj)


# Allow running from a source checkout without installing the package: prepend the
# project's 'src' to sys.path BEFORE importing droptical_api_client, so the live
# source is used and shadows any (possibly stale) installed build.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(project_root, "src"))

from droptical_api_client import (  # noqa: E402
    ActionSettings,
    AllSettings,
    ApiError,
    DeviceError,
    ExportJob,
    FrameResult,
    FrameRoi,
    GpioLevels,
    Infos,
    Measurement,
    MeasurementFrame,
    Preset,
    dropticalAPIClient,
)
from examples.gui.api_bridge import BitDepth, ColorMode, CompressionAlgorithm, GuiApiBridge  # noqa: E402
from examples.gui.frame_saver import FrameSaver  # noqa: E402
from examples.gui.media_fetcher import MediaFetcher  # noqa: E402

logger = logging.getLogger("ClientGUI")

# Measurement status → status-badge object name (drives the QSS pill colour).
_STATUS_BADGE = {
    "done": "badgeSuccess",
    "in_progress": "badgePrimary",
    "waiting": "badgeWarning",
    "no_trigger_received": "badgeWarning",
    "cancelled": "badgeSecondary",
    "error": "badgeDanger",
}

# Dark theme (droptical blue #01669A on dark surfaces).
# Single source of truth for layout gaps, so spacing is uniform across the GUI.
# Titled #card widgets additionally reserve a 10px top margin (for their title), which
# naturally gives grouped section cards a bit more separation than loose widgets.
UI_SPACING = 10

# Official droptical logo (droplet symbol + white wordmark for dark backgrounds).
# The source SVG nests <svg>
# elements, which QSvgRenderer (SVG Tiny 1.2) silently drops — so it is FLATTENED here:
# the droplet paths (inner svg at x=0,y=0) are lifted as-is, and the wordmark path
# (inner svg at x=47,y=2, 1:1 viewBox) is wrapped in a translate(47,2) group.
DROPTICAL_LOGO_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 172 36" width="172" height="36">
  <path d="M 31.537 27.794 C 34.885 24.968 37.466 20.577 38.319 16.077 C 39.106 11.911 38.384 7.858 35.622 4.961 C 36.469 8.008 34.888 10.84 32.088 13.174 C 29.261 15.528 25.368 17.226 21.739 18.183 C 17.142 19.404 15.197 22.515 15.384 25.391 C 15.585 28.478 18.24 31.48 23.059 31.276 C 25.771 31.162 28.831 30.08 31.534 27.794" fill="#00a5b8"/>
  <path d="M 0.113 20.297 C -0.284 23.173 0.367 26.539 2.125 29.386 C 4.079 32.55 7.406 35.112 11.965 35.43 C 8.593 33.501 7.43 30.204 7.525 26.695 C 7.61 23.452 8.768 19.952 10.266 17.021 C 12.145 13.356 11.062 11.343 9.12 10.977 C 7.267 10.629 4.532 11.769 2.463 14.585 C 1.317 16.145 0.411 18.128 0.113 20.294" fill="#0087ab"/>
  <path d="M 23.045 0.058 C 20.448 -0.095 17.139 0.553 14.019 1.855 C 10.979 3.124 7.986 5.086 5.778 7.725 C 8.265 5.884 10.677 5.356 12.888 5.614 C 15.221 5.887 17.423 7.056 19.161 8.607 C 24.474 13.347 32.493 6.184 27.97 1.921 C 26.893 0.907 25.217 0.187 23.045 0.061" fill="#006a9c"/>
  <g transform="translate(47,2)">
    <path d="M 116.678 18.728 L 116.678 1.903 L 120.387 1.903 L 120.387 18.407 C 120.387 19.453 120.525 20.174 120.804 20.571 C 121.08 20.968 121.509 21.163 122.085 21.163 C 122.551 21.163 123.023 21.067 123.49 20.874 L 124.004 23.534 C 123.173 23.811 122.192 23.952 121.062 23.952 C 118.141 23.952 116.68 22.212 116.68 18.728 M 110.162 21.292 L 110.162 16.516 L 107.412 16.516 C 104.683 16.516 103.319 17.391 103.319 19.143 C 103.319 19.976 103.655 20.613 104.327 21.049 C 104.998 21.487 105.939 21.707 107.157 21.707 C 108.374 21.707 109.331 21.569 110.162 21.289 Z M 113.868 13.537 L 113.868 23.086 C 111.736 23.748 109.424 24.081 106.929 24.081 C 104.434 24.081 102.734 23.712 101.445 22.975 C 100.156 22.239 99.51 21.016 99.51 19.305 C 99.51 17.595 100.096 16.303 101.268 15.557 C 102.44 14.809 104.243 14.436 106.671 14.436 L 110.156 14.436 L 110.156 13.537 C 110.156 12.425 109.841 11.641 109.211 11.181 C 108.581 10.721 107.669 10.493 106.477 10.493 C 104.665 10.493 102.788 10.823 100.848 11.488 L 100.335 8.731 C 102.53 8.049 104.62 7.707 106.603 7.707 C 111.442 7.707 113.859 9.651 113.859 13.537 Z M 85.003 15.78 C 85.003 14.37 85.25 13.132 85.738 12.062 C 86.226 10.995 86.89 10.15 87.721 9.531 C 88.55 8.912 89.474 8.452 90.485 8.154 C 91.498 7.854 92.59 7.707 93.763 7.707 C 95.381 7.707 96.874 8.037 98.239 8.701 L 97.727 11.395 C 96.617 10.796 95.435 10.496 94.179 10.496 C 92.623 10.496 91.34 10.929 90.326 11.794 C 89.313 12.66 88.809 13.988 88.809 15.783 C 88.809 17.577 89.343 19.029 90.407 19.949 C 91.471 20.868 92.827 21.325 94.467 21.325 C 95.724 21.325 96.908 21.049 98.014 20.493 L 98.528 23.186 C 97.292 23.784 95.724 24.084 93.829 24.084 C 91.334 24.084 89.24 23.378 87.546 21.968 C 85.852 20.559 85.003 18.497 85.003 15.783 Z M 78.355 2.705 C 78.355 2.065 78.58 1.521 79.027 1.07 C 79.474 0.622 80.019 0.397 80.658 0.397 C 81.296 0.397 81.81 0.622 82.257 1.07 C 82.703 1.518 82.928 2.065 82.928 2.705 C 82.928 3.345 82.703 3.859 82.257 4.307 C 81.81 4.755 81.276 4.98 80.658 4.98 C 80.041 4.98 79.477 4.755 79.027 4.307 C 78.58 3.859 78.355 3.324 78.355 2.705 Z M 78.805 23.697 L 78.805 8.121 L 82.514 8.121 L 82.514 23.697 Z M 63.878 10.908 L 63.878 8.44 L 66.787 8.118 L 67.234 3.183 L 70.496 3.183 L 70.496 8.118 L 75.932 8.118 L 75.932 10.908 L 70.496 10.908 L 70.496 17.926 C 70.496 19.143 70.736 20.003 71.216 20.505 C 71.695 21.007 72.394 21.259 73.309 21.259 C 74.481 21.259 75.525 20.938 76.442 20.297 L 76.955 22.924 C 75.74 23.652 74.301 24.015 72.64 24.015 C 68.739 24.015 66.79 22.083 66.79 18.214 L 66.79 10.908 L 63.881 10.908 Z M 59.02 15.813 C 59.02 13.889 58.541 12.522 57.581 11.71 C 56.621 10.899 55.395 10.493 53.905 10.493 C 52.84 10.493 51.977 10.631 51.314 10.911 L 51.314 20.685 C 52.082 21.07 52.945 21.262 53.905 21.262 C 55.353 21.262 56.57 20.829 57.548 19.964 C 58.529 19.098 59.017 17.715 59.017 15.813 Z M 47.608 31.707 L 47.608 8.728 C 49.44 8.046 51.509 7.704 53.809 7.704 C 56.601 7.704 58.807 8.362 60.427 9.675 C 62.046 10.989 62.856 13.066 62.856 15.909 C 62.856 18.752 62.1 20.679 60.586 22.013 C 59.071 23.348 57.089 24.015 54.639 24.015 C 53.338 24.015 52.232 23.835 51.314 23.471 L 51.314 31.707 L 47.605 31.707 Z M 28.204 15.909 C 28.204 14.478 28.444 13.222 28.923 12.143 C 29.403 11.064 30.057 10.21 30.89 9.579 C 31.721 8.948 32.639 8.479 33.64 8.169 C 34.642 7.86 35.706 7.704 36.837 7.704 C 39.245 7.704 41.281 8.383 42.942 9.738 C 44.603 11.094 45.437 13.153 45.437 15.906 C 45.437 18.659 44.612 20.712 42.96 22.059 C 41.308 23.405 39.266 24.078 36.837 24.078 C 34.408 24.078 32.36 23.405 30.698 22.059 C 29.037 20.712 28.204 18.662 28.204 15.906 Z M 41.601 15.909 C 41.601 14.006 41.134 12.63 40.195 11.776 C 39.257 10.923 38.138 10.496 36.837 10.496 C 35.535 10.496 34.387 10.923 33.448 11.776 C 32.51 12.63 32.042 14.009 32.042 15.909 C 32.042 17.809 32.51 19.161 33.448 20.027 C 34.387 20.892 35.514 21.325 36.837 21.325 C 38.159 21.325 39.257 20.892 40.195 20.027 C 41.134 19.161 41.601 17.788 41.601 15.909 Z M 18.488 23.697 L 18.488 8.795 C 19.064 8.497 19.889 8.245 20.965 8.04 C 22.042 7.836 23.058 7.737 24.018 7.737 C 25.466 7.737 26.638 7.866 27.535 8.121 L 27.022 10.878 C 26.533 10.664 25.787 10.556 24.785 10.556 C 23.721 10.556 22.857 10.694 22.194 10.974 L 22.194 23.697 L 18.485 23.697 Z M 5.432 11.839 C 4.44 12.693 3.945 14.082 3.945 16.005 C 3.945 17.929 4.431 19.296 5.399 20.108 C 6.368 20.919 7.6 21.325 9.094 21.325 C 10.095 21.325 10.959 21.175 11.684 20.877 L 11.684 11.103 C 10.917 10.739 10.044 10.559 9.064 10.559 C 7.636 10.559 6.425 10.986 5.435 11.839 Z M 15.391 1.903 L 15.391 23.086 C 13.472 23.748 11.405 24.081 9.19 24.081 C 6.398 24.081 4.191 23.423 2.572 22.11 C 0.952 20.796 0.143 18.719 0.143 15.876 C 0.143 13.033 0.898 11.106 2.413 9.771 C 3.927 8.437 5.909 7.77 8.359 7.77 C 9.66 7.77 10.767 7.95 11.684 8.314 L 11.684 1.903 L 15.394 1.903 Z" fill="#ffffff"/>
  </g>
</svg>
"""

STYLESHEET = """
* { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 13px; }
QMainWindow, QWidget { background: #212529; color: #DEE2E6; }
QScrollArea, QAbstractScrollArea { border: none; background: transparent; }

/* Branded top bar (droptical header). */
QFrame#appHeader { background: #1A1D20; border-bottom: 1px solid #495057; }
QLabel#headerLabel { color: #AFB3B7; }

/* Demo notice bar under the header (amber, informational). */
QFrame#demoNotice { background: #33301F; border-bottom: 1px solid #5C531F; }
QLabel#demoNoticeText { color: #FFC107; font-weight: 600; }

QTabWidget::pane { border: 1px solid #495057; border-radius: 6px; top: -1px; background: #212529; }
QTabBar { background: transparent; }  /* the bar strip itself, so it never paints a mismatched box */
/* Flat underline tabs: no boxes; the active tab is marked only by a coloured underline
   + brighter text, so unselected tabs blend with the body/card instead of looking sunken. */
QTabBar::tab { background: transparent; color: #AFB3B7; padding: 8px 18px;
               border: none; border-bottom: 2px solid transparent; margin-right: 2px; }
QTabBar::tab:selected { color: #FFFFFF; border-bottom: 2px solid #01669A; }
QTabBar::tab:hover:!selected { color: #DEE2E6; }
QTabBar::tab:disabled { color: #5A5F63; }

/* Nested Increment/Constant tabs live inside a #card → paint their pane and page with the
   card colour (not the darker body bg). The page is opaque so it also covers Qt's internal
   QStackedWidget, which otherwise shows through as #212529. */
QTabWidget#modeTabs { background: transparent; }
QTabWidget#modeTabs::pane { background: #2B3035; border: 1px solid #495057; border-radius: 6px; top: -1px; }
QWidget#modeTabPage { background: #2B3035; }

QGroupBox#card, QFrame#card { background: #2B3035; border: 1px solid #495057; border-radius: 8px; margin-top: 10px; }
QGroupBox#card { padding: 12px 10px 6px 10px; }
QGroupBox#card::title { subcontrol-origin: margin; left: 10px; padding: 0 4px;
                        color: #AFB3B7; font-weight: 700; }

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #2B3035; color: #DEE2E6; border: 1px solid #495057; border-radius: 6px;
    padding: 4px 8px; min-height: 20px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #01669A; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background: #343A40; color: #808488; border-color: #3A4046; }
QComboBox { combobox-popup: 1; }
QComboBox QAbstractItemView { background: #2B3035; color: #DEE2E6; padding: 4px;
    selection-background-color: #01669A; selection-color: #FFFFFF; border: 1px solid #495057;
    outline: 0; }
QComboBox QAbstractItemView::item { min-height: 22px; padding: 3px 10px; border-radius: 4px; }
QComboBox QAbstractItemView::item:selected { background: #01669A; color: #FFFFFF; }

/* Spin-box step arrows and the combo drop-down arrow are drawn natively by the
   Fusion style. Qt does NOT load data: URIs in QSS url(), so custom arrow images
   never render; native rendering uses the dark palette's text colour and stays
   consistent with the theme. */

QPushButton { background: #343A40; color: #DEE2E6; border: 1px solid #495057; border-radius: 6px;
    padding: 5px 12px; min-height: 14px; }
QPushButton:hover:enabled { background: #3D444B; border-color: #5A6169; }
QPushButton:disabled { background: transparent; color: #6C757D; border-color: #495057; }
QPushButton#primaryButton { background: #01669A; color: #FFFFFF; border: 1px solid #01669A; font-weight: 600;
    padding: 5px 14px; min-height: 14px; }
QPushButton#primaryButton:hover:enabled { background: #01527B; border-color: #01527B; }
QPushButton#primaryButton:pressed { background: #014A6F; }
QPushButton#primaryButton:disabled { background: transparent; color: #6C757D; border-color: #495057; }
QPushButton#dangerButton { background: #DC3545; color: #FFFFFF; border: 1px solid #DC3545; font-weight: 600;
    padding: 5px 14px; min-height: 14px; }
QPushButton#dangerButton:hover:enabled { background: #BB2D3B; border-color: #BB2D3B; }
QPushButton#dangerButton:pressed { background: #B02A37; }
QPushButton#dangerButton:disabled { background: transparent; color: #6C757D; border-color: #495057; }

/* QLabel inherits the generic `QWidget { background: #212529 }` rule above, which
   paints an opaque rectangle that clashes on cards/inputs (#2B3035). Reset it to
   transparent here; the #objectName rules below are more specific and keep their
   own backgrounds (badges, imageArea). */
QLabel { background: transparent; }
/* Layout wrappers on cards must not paint the opaque window background. */
QWidget#unitRow { background: transparent; }
QLabel#unitAddon { color: #AFB3B7; font-weight: 600; padding: 0 2px; }
QLabel#metaKey { color: #AFB3B7; }
QLabel#sectionHeader { color: #AFB3B7; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QLabel#metaValue { color: #DEE2E6; font-weight: 600; }
QLabel#statusLine { color: #AFB3B7; font-style: italic; }
QLabel#imageArea { background: #1A1D20; color: #808488; border: 1px solid #495057; border-radius: 6px; }
QLabel#resultText { color: #AFB3B7; }

QLabel#badgeSuccess   { background: #198754; color: #FFFFFF; border-radius: 8px; padding: 2px 10px; font-weight: 600; }
QLabel#badgeWarning   { background: #FFC107; color: #000000; border-radius: 8px; padding: 2px 10px; font-weight: 600; }
QLabel#badgeDanger    { background: #DC3545; color: #FFFFFF; border-radius: 8px; padding: 2px 10px; font-weight: 600; }
QLabel#badgePrimary   { background: #01669A; color: #FFFFFF; border-radius: 8px; padding: 2px 10px; font-weight: 600; }
QLabel#badgeSecondary { background: #6C757D; color: #FFFFFF; border-radius: 8px; padding: 2px 10px; font-weight: 600; }

QStatusBar { background: #1A1D20; color: #AFB3B7; }
QScrollBar:vertical { background: #212529; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #495057; border-radius: 5px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #212529; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #495057; border-radius: 5px; min-width: 20px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""


def _apply_dark_palette(app: QApplication) -> None:
    """Give the Fusion style a dark base palette so widgets NOT covered by the
    stylesheet (menus, tooltips, dialogs, message boxes) stay on-theme too."""
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#212529"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#DEE2E6"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#2B3035"))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#343A40"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#DEE2E6"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#343A40"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#DEE2E6"))
    pal.setColor(QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#01669A"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2B3035"))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#DEE2E6"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#808488"))
    disabled = QColor("#6C757D")
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    app.setPalette(pal)


def _assets_dir() -> pathlib.Path:
    """Resolve the bundled ``assets`` directory both from source and from a PyInstaller
    build. The .spec ships it via ``datas=[('assets', 'assets')]`` → under a frozen build
    it lives at ``sys._MEIPASS/assets``, not next to ``__file__``."""
    if getattr(sys, "frozen", False):
        base = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(sys.executable).parent))
    else:
        base = pathlib.Path(__file__).resolve().parent
    return base / "assets"


def _arrow_stylesheet() -> str:
    """QSS for custom chevron arrows on spin boxes and combo boxes, loaded from the SVG
    files in the assets dir. Qt does NOT accept data: URIs in QSS url(), so real file
    paths are required. If the assets are missing we return "" and Fusion draws its
    (plainer) native arrows instead. The stepper/drop-down columns share one width so the
    arrows of number inputs and selects line up."""
    assets = _assets_dir()
    down, up = assets / "chevron-down.svg", assets / "chevron-up.svg"
    if not (down.exists() and up.exists()):
        return ""
    down_url, up_url = down.as_posix(), up.as_posix()
    arrow_col = 22  # identical width for combo drop-down and spin-box step buttons

    # Style the tab-bar overflow scrollers with the same chevron look (left/right variants),
    # replacing Qt's plain native arrows. Only added when those assets are present.
    left, right = assets / "chevron-left.svg", assets / "chevron-right.svg"
    tab_scroller_qss = ""
    if left.exists() and right.exists():
        tab_scroller_qss = f"""
QTabBar::scroller {{ width: 40px; }}
QTabBar QToolButton {{ background: #2B3035; border: 1px solid #495057; border-radius: 6px; margin: 4px 1px; }}
QTabBar QToolButton:hover:enabled {{ background: #3D444B; border-color: #5A6169; }}
QTabBar QToolButton:disabled {{ background: transparent; border-color: #3A4046; }}
QTabBar QToolButton::left-arrow {{ image: url("{left.as_posix()}"); width: 8px; height: 12px; }}
QTabBar QToolButton::right-arrow {{ image: url("{right.as_posix()}"); width: 8px; height: 12px; }}
"""
    return tab_scroller_qss + f"""
QComboBox::drop-down {{ subcontrol-origin: border; subcontrol-position: center right; width: {arrow_col}px;
    background: transparent; border-left: 1px solid #495057;
    border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
QComboBox::down-arrow {{ image: url("{down_url}"); width: 12px; height: 8px; }}

QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
    width: {arrow_col}px; background: transparent; border-left: 1px solid #495057; border-top-right-radius: 6px; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
    width: {arrow_col}px; background: transparent; border-left: 1px solid #495057; border-bottom-right-radius: 6px; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: #3D444B; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up_url}"); width: 12px; height: 8px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down_url}"); width: 12px; height: 8px; }}
"""


class _SettingsSaveSignals(QObject):
    """Signals for the off-thread settings autosave (marshaled back to the GUI thread)."""

    done = Signal()
    error = Signal(str)


class _SettingsSaveTask(QRunnable):
    """Fire-and-forget PATCH of the settings on a thread-pool worker so the on-blur
    autosave never blocks the UI. Uses its own short-lived client (``connect()`` makes
    no network call), independent of the measurement worker's client.
    """

    def __init__(self, ip_address: str, api_port: int, settings: AllSettings) -> None:
        super().__init__()
        self._ip_address = ip_address
        self._api_port = api_port
        self._settings = settings
        self.signals = _SettingsSaveSignals()

    def run(self) -> None:
        try:
            api = dropticalAPIClient()
            api.connect(self._ip_address, api_port=self._api_port)
            api.update_settings(self._settings)
            self.signals.done.emit()
        except (ApiError, DeviceError) as e:
            self.signals.error.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.signals.error.emit(str(e))


class _MachineModeTask(QRunnable):
    """Off-thread POST of the device operating mode (streaming/lab/production) so the
    header mode switch never blocks the UI. Uses its own short-lived client, like the
    settings autosave task."""

    def __init__(self, ip_address: str, api_port: int, mode: str) -> None:
        super().__init__()
        self._ip_address = ip_address
        self._api_port = api_port
        self._mode = mode
        self.signals = _SettingsSaveSignals()  # reuse the done/error signals

    def run(self) -> None:
        try:
            api = dropticalAPIClient()
            api.connect(self._ip_address, api_port=self._api_port)
            if self._mode == "streaming":
                api.set_streaming_mode(True)
            elif self._mode == "production":
                api.set_production_mode(True)
            else:
                api.set_lab_mode()
            self.signals.done.emit()
        except (ApiError, DeviceError) as e:
            self.signals.error.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.signals.error.emit(str(e))


class _HistoryPageSignals(QObject):
    """Signals for the off-thread history page fetch (marshaled back to the GUI thread)."""

    loaded = Signal(list, object, int)  # (frames, next_cursor, generation)
    error = Signal(str, int)  # (message, generation)


class _HistoryPageTask(QRunnable):
    """Fetch one page of the global frame list (GET /frames) off-thread so the endless-scroll
    history never blocks the UI, then resolve each frame's detail (GET /frames/{id}) so the
    cards can show per-frame results (the list view omits rois). Uses its own short-lived
    client. The generation token lets the GUI drop a page that arrives after a reload/disconnect."""

    def __init__(self, ip_address: str, api_port: int, cursor: str | None, per_page: int, generation: int) -> None:
        super().__init__()
        self._ip_address = ip_address
        self._api_port = api_port
        self._cursor = cursor
        self._per_page = per_page
        self._generation = generation
        self.signals = _HistoryPageSignals()

    def run(self) -> None:
        try:
            api = dropticalAPIClient()
            api.connect(self._ip_address, api_port=self._api_port)
            page = api.list_frames(per_page=self._per_page, cursor=self._cursor)
            detailed = []
            for frame in page.data:
                try:
                    detailed.append(api.get_frame(frame.id))  # detail includes rois (results)
                except (ApiError, DeviceError):
                    detailed.append(frame)  # fall back to the list entry (image only, no results)
            self._safe_emit("loaded", detailed, page.next_cursor, self._generation)
        except (ApiError, DeviceError) as e:
            self._safe_emit("error", str(e), self._generation)
        except Exception as e:  # noqa: BLE001
            self._safe_emit("error", str(e), self._generation)

    def _safe_emit(self, kind: str, *args: Any) -> None:
        # The GUI (and this task's own signals object) can be torn down while a long page
        # fetch is still in flight (app close / disconnect); accessing/emitting the signal
        # would then raise on the worker thread. Guard the whole access, not just the emit.
        try:
            if _is_deleted(self.signals):
                return
            getattr(self.signals, kind).emit(*args)
        except RuntimeError:
            pass


class _ApiCallSignals(QObject):
    """Signals for a generic off-thread API call (marshaled back to the GUI thread)."""

    done = Signal(object)  # the call's return value
    error = Signal(str)


class _ApiCallTask(QRunnable):
    """Run an arbitrary API operation off-thread with its own short-lived client, then emit
    its result (or the error) back to the GUI thread. This is the read/command counterpart to
    the fire-and-forget _SettingsSaveTask, used by the Presets and Machine tabs so their
    list/refresh/command calls never block the UI. ``fn`` receives a connected client and
    returns whatever should be handed to the ``done`` handler."""

    def __init__(self, ip_address: str, api_port: int, fn: Any) -> None:
        super().__init__()
        self._ip_address = ip_address
        self._api_port = api_port
        self._fn = fn  # Callable[[dropticalAPIClient], Any]
        self.signals = _ApiCallSignals()

    def run(self) -> None:
        try:
            api = dropticalAPIClient()
            api.connect(self._ip_address, api_port=self._api_port)
            result = self._fn(api)
            self._safe_emit("done", result)
        except (ApiError, DeviceError) as e:
            self._safe_emit("error", str(e))
        except Exception as e:  # noqa: BLE001
            self._safe_emit("error", str(e))

    def _safe_emit(self, kind: str, *args: Any) -> None:
        # The GUI (and this task's signals object) can be torn down while a call is still in
        # flight (app close / disconnect); guard the whole access, not just the emit.
        try:
            if _is_deleted(self.signals):
                return
            getattr(self.signals, kind).emit(*args)
        except RuntimeError:
            pass


class _PresetDialog(QDialog):
    """Small modal form for creating/editing a preset: a name and an optional comment."""

    def __init__(self, parent: QWidget | None = None, *, name: str = "", comment: str = "", title: str = "Preset") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        form = QFormLayout(self)
        self._name = QLineEdit(name)
        self._name.setPlaceholderText("Name (3–32 characters)")
        self._comment = QLineEdit(comment)
        self._comment.setPlaceholderText("Comment (optional)")
        form.addRow("Name:", self._name)
        form.addRow("Comment:", self._comment)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[str, str]:
        return self._name.text().strip(), self._comment.text().strip()


class FlowLayout(QLayout):
    """A layout that arranges its items left-to-right and wraps to the next row when the
    current one is full — so cards flow into as many columns as the width allows and
    reflow on resize. Adapted from Qt's canonical FlowLayout example."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[Any] = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: Any) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Any:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> Any:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    @staticmethod
    def _item_size(item: Any) -> QSize:
        # Clamp to maximumSize so a widget with a large content size hint (e.g. an image
        # label) still lays out at its fixed card width instead of ballooning the column.
        hint, cap = item.sizeHint(), item.maximumSize()
        return QSize(min(hint.width(), cap.width()), min(hint.height(), cap.height()))

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        spacing = self.spacing()

        # First pass: pack items into rows by width.
        rows: list[list[Any]] = []
        row: list[Any] = []
        row_width = 0
        for item in self._items:
            w = self._item_size(item).width()
            add = w if not row else spacing + w
            if row and row_width + add > effective.width():
                rows.append(row)
                row, row_width = [item], w
            else:
                row.append(item)
                row_width += add
        if row:
            rows.append(row)

        # Second pass: place each row, horizontally centered within the available width.
        y = effective.y()
        for items in rows:
            sizes = [self._item_size(it) for it in items]
            total_w = sum(s.width() for s in sizes) + spacing * (len(items) - 1)
            x = effective.x() + max(0, (effective.width() - total_w) // 2)
            line_height = 0
            for item, size in zip(items, sizes, strict=False):
                if not test_only:
                    item.setGeometry(QRect(QPoint(x, y), size))
                x += size.width() + spacing
                line_height = max(line_height, size.height())
            y += line_height + spacing

        if not rows:
            return margins.top() + margins.bottom()
        return (y - spacing) - rect.y() + margins.bottom()


class _HistoryFlowScrollArea(QScrollArea):
    """Scroll area for the history FlowLayout: keeps its child tall enough for the wrapped
    rows (a FlowLayout's own size hint doesn't account for height-for-width in a scroll area)."""

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self.sync_height()

    def sync_height(self) -> None:
        child = self.widget()
        layout = child.layout() if child is not None else None
        if layout is not None and layout.hasHeightForWidth():
            child.setMinimumHeight(layout.heightForWidth(self.viewport().width()))


class ValueStreamWorker(QObject):
    """Consumes ``client.value_stream()`` on its own thread and relays each ValueMessage to
    the GUI. Uses its own short-lived client so it is fully independent of the measurement
    worker — value messages keep arriving while the user triggers measurements elsewhere."""

    message = Signal(object)  # a ValueMessage
    error = Signal(str)
    finished = Signal()

    def __init__(self, ip_address: str, api_port: int) -> None:
        super().__init__()
        self._ip_address = ip_address
        self._api_port = api_port
        self._api = None

    @Slot()
    def run(self) -> None:
        try:
            self._api = dropticalAPIClient()
            self._api.connect(self._ip_address, api_port=self._api_port)
            for msg in self._api.value_stream():
                self.message.emit(msg)
        except (ApiError, DeviceError) as e:
            self.error.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    def stop(self) -> None:
        """Ask the value stream to stop; run()'s loop then ends and finished() fires."""
        if self._api is not None:
            self._api.stop_value_stream()


class EventStreamWorker(QObject):
    """Consumes ``client.event_stream()`` on its own thread and relays each realtime
    broadcast to the GUI as a signal. Entirely optional: if ``websocket-client`` is missing
    or the device's customer Reverb app is unreachable it reports that once and the GUI keeps
    polling. Uses its own short-lived client, independent of every other worker."""

    connected = Signal()  # first broadcast arrived -> the stream is live
    # NB: not named `event` — that would shadow QObject.event(), which Qt calls internally.
    broadcast = Signal(str, str, object)  # channel, event name, payload dict
    unavailable = Signal(str)  # websocket-client missing / stream could not run
    finished = Signal()

    def __init__(self, ip_address: str, api_port: int) -> None:
        super().__init__()
        self._ip_address = ip_address
        self._api_port = api_port
        self._api = None

    @Slot()
    def run(self) -> None:
        try:
            import websocket  # noqa: F401 - presence check; the client imports it internally
        except ImportError:
            self.unavailable.emit("websocket-client not installed")
            self.finished.emit()
            return
        try:
            self._api = dropticalAPIClient()
            self._api.connect(self._ip_address, api_port=self._api_port)
            seen = False
            # reconnect=True (default): transient drops re-subscribe transparently; the loop
            # only ends when stop() is called or a terminal error bubbles up.
            for evt in self._api.event_stream():
                if not seen:
                    seen = True
                    self.connected.emit()
                self.broadcast.emit(evt.channel, evt.event, evt.data)
        except (ApiError, DeviceError) as e:
            self.unavailable.emit(str(e))
        except Exception as e:  # noqa: BLE001 - a broken event stream must never crash the GUI
            self.unavailable.emit(str(e))
        finally:
            self.finished.emit()

    def stop(self) -> None:
        """Ask the event stream to stop; run()'s loop then ends and finished() fires."""
        if self._api is not None:
            self._api.stop_event_stream()


class _FooterStatus:
    """A QLabel-compatible status sink: forwards ``setText``/``clear`` to
    the app footer (the QMainWindow status bar), so transient action messages
    ("Executing…", "Done.") live in the footer instead of eating content space.
    Resolves the status bar lazily — it is only ever written to at runtime."""

    def __init__(self, window: MainWindow) -> None:
        self._window = window

    def setText(self, text: str) -> None:
        self._window.status_bar.showMessage(text)

    def clear(self) -> None:
        self._window.status_bar.clearMessage()


class MainWindow(QMainWindow):
    """The main application window with integrated media display."""

    _resolve_conflict_signal = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        logger.info("Initializing MainWindow...")
        self.setWindowTitle("Droptical API Example Client")
        self.setGeometry(100, 100, 950, 850)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        self.worker_thread: QThread | None = None
        self.worker: GuiApiBridge | None = None
        self.current_action_type: str | None = None
        self.progress_dialog: QProgressDialog | None = None
        # A second, independent worker for a shot fired *while the image stream is running*
        # (lab mode only). It uses its own client, so it never contends with the stream worker.
        self._shot_thread: QThread | None = None
        self._shot_worker: GuiApiBridge | None = None
        self.active_workers: list[tuple[QThread, MediaFetcher]] = []
        # Workers detached by a cancel that can't be interrupted (a blocking connect): kept
        # referenced here so Python doesn't GC a still-running QThread, until it self-cleans.
        self._orphaned_workers: list[tuple[QObject, QThread]] = []

        # --- value-stream worker (own thread, independent of the measurement worker) ---
        self._vs_thread: QThread | None = None
        self._vs_worker: ValueStreamWorker | None = None
        self._vs_count = 0
        self._vs_unseen = 0  # messages arrived while the Value Stream tab is not in view
        self._vs_dot_icon = self._dot_icon("#01A4B7")  # tab badge for unseen value messages
        self._feature_map: dict[int, tuple[str, str]] = {}  # featureId -> (name, unit)

        # --- optional realtime event bridge (Reverb) ---
        # When the device's customer event app is reachable, broadcasts drive the refreshes
        # that otherwise poll; if it is missing or drops, the GUI silently keeps polling.
        self._events_thread: QThread | None = None
        self._events_worker: EventStreamWorker | None = None
        self._events_healthy = False
        self._events_disabled = False  # set once if websocket-client is missing (no retries)

        # --- settings autosave (on-blur, off-thread) + cross-tab field sync ---
        self._connected = False
        self._suppress_autosave = False  # set while programmatically populating widgets
        # Velocity feature (feature id 7) gates the exposure
        # controls; set for real from the settings on connect. Default-on pre-connect
        # (inputs are disabled until a device is initialized anyway).
        self._velocity_enabled = True
        self._syncing = False  # set while mirroring a field to the other tabs
        self._sync_map: dict[QWidget, tuple[str, list[str]]] = {}
        self._autosave_prefix: str | None = None
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(200)  # coalesce editingFinished double-fires / rapid tabbing
        self._autosave_timer.timeout.connect(self._perform_autosave)
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

    @staticmethod
    def _render_svg_logo(svg: str, height: int) -> QPixmap:
        """Render an SVG string to a crisp (2x) QPixmap of the given logical height."""
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        size = renderer.defaultSize()
        if size.height() <= 0:
            return QPixmap()
        dpr = 2  # oversample for HiDPI; setDevicePixelRatio keeps the logical size
        width = round(height * size.width() / size.height())
        pix = QPixmap(width * dpr, height * dpr)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        renderer.render(painter)
        painter.end()
        pix.setDevicePixelRatio(dpr)
        return pix

    def _build_app_header(self) -> QWidget:
        """Branded top bar: droptical logo on the left, connection controls on the right
        (device host + the single Initialize/Change button)."""
        header = QFrame()
        header.setObjectName("appHeader")
        header.setFixedHeight(60)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(self._render_svg_logo(DROPTICAL_LOGO_SVG, height=30))
        logo.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(logo)
        lay.addStretch()

        # Connection controls in the header (right side).
        dev_label = QLabel("Device:")
        dev_label.setObjectName("headerLabel")
        # Editable combo: a few selectable host suggestions (mDNS name + a typical LAN IP +
        # a local default), while staying freely typeable for any other host/IP.
        self.ip_input = QComboBox()
        self.ip_input.setEditable(True)
        self.ip_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)  # typed hosts aren't appended to the hint list
        self.ip_input.addItems(["analysisunit.local", "192.168.1.100", "127.0.0.1"])
        self.ip_input.setCurrentText("analysisunit.local")
        self.ip_input.setPlaceholderText("host or IP, optionally :port (e.g. 127.0.0.1:8080)")
        self.ip_input.setToolTip("Device host/IP — pick a suggestion or type your own. Append :port to override the default (80); e.g. 127.0.0.1:8080")
        self.ip_input.setFixedWidth(240)
        # Single toggle button: "Initialize Device" while disconnected, then "Change Device"
        # once a device is initialized. Its action is dispatched in _on_device_button().
        self.device_button = QPushButton("Initialize Device")

        # Device operating-mode switch. Lab/Production attach per-frame measurement values
        # (frame metadata + value stream); Streaming is a plain live preview without values.
        mode_label = QLabel("Mode:")
        mode_label.setObjectName("headerLabel")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Streaming", "Lab", "Production"])
        self.mode_combo.setToolTip(
            "Device operating mode. Lab/Production attach measurement values to frames and the "
            "value stream; Streaming is a plain live preview without values."
        )
        self.mode_combo.setEnabled(False)  # enabled once a device is initialized

        lay.addWidget(mode_label)
        lay.addWidget(self.mode_combo)
        lay.addWidget(dev_label)
        lay.addWidget(self.ip_input)
        lay.addWidget(self.device_button)
        return header

    # Combo index <-> wire mode name.
    _MODES = ("streaming", "lab", "production")
    HISTORY_PAGE_SIZE = 12  # frames fetched per endless-scroll history page
    HISTORY_CARD_WIDTH = 320  # fixed width per history card so the flow layout wraps into columns

    def _set_mode_combo(self, mode: str | None) -> None:
        """Reflect a device mode in the header combo without triggering _on_mode_changed."""
        try:
            idx = self._MODES.index((mode or "streaming").lower())
        except ValueError:
            idx = 0
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(idx)
        self.mode_combo.blockSignals(False)

    def _current_mode(self) -> str:
        idx = self.mode_combo.currentIndex()
        return self._MODES[idx] if 0 <= idx < len(self._MODES) else "streaming"

    def _post_mode(self, mode: str) -> None:
        """POST the operating mode to the device off-thread (never blocks the UI)."""
        if not self._connected:
            return
        host, port = self._parse_host_port(self.ip_input.currentText())
        task = _MachineModeTask(host, port, mode)
        task.signals.done.connect(lambda m=mode: self.status_bar.showMessage(f"Mode set to {m}.", 3000))
        task.signals.error.connect(lambda msg: self.status_bar.showMessage(f"Mode change failed: {msg[:120]}", 6000))
        QThreadPool.globalInstance().start(task)

    def _apply_mode_to_tabs(self, mode: str) -> None:
        """Streaming mode is a plain live image preview without measurement values, so only the
        Image Stream and Machine tabs stay usable. Lab/Production leave every tab available —
        the stream (image and/or value) can always be switched on, and you can run single shots
        etc. to get the raw frames live plus their optional measured values. When the current
        tab is not usable in the selected mode, fall back to the Image Stream tab."""
        stream_index = self.tabs.indexOf(self.stream_tab)
        if mode == "streaming":
            allowed = {stream_index, self.tabs.indexOf(self.machine_tab)}
        else:  # lab / production: everything is available
            allowed = set(range(self.tabs.count()))
        # Capture the active tab first: disabling it makes Qt auto-select another enabled
        # tab, which would otherwise hide whether a fallback is actually needed.
        current = self.tabs.currentIndex()
        for i in range(self.tabs.count()):
            self.tabs.setTabEnabled(i, i in allowed)
        if current not in allowed:
            self.tabs.setCurrentIndex(stream_index)

    def _on_mode_changed(self, index: int) -> None:
        """User picked a mode → POST it off-thread and update tab availability."""
        if not self._connected or not (0 <= index < len(self._MODES)):
            return
        mode = self._MODES[index]
        self._post_mode(mode)
        self._apply_mode_to_tabs(mode)

    def _create_value_stream_tab(self) -> QWidget:
        """Value-stream tab: listens on the JSON value stream and shows the per-frame
        feature results that the device pushes on every measurement (lab/production)."""
        widget = QWidget()
        root = QVBoxLayout(widget)
        root.setSpacing(UI_SPACING)

        self.vs_button = QPushButton("Start Value Stream")
        self.vs_button.setObjectName("primaryButton")
        self.vs_button.clicked.connect(self._on_vs_button)
        root.addWidget(self.vs_button)

        controls = QHBoxLayout()
        self.vs_count_label = QLabel("No results received yet.")
        self.vs_count_label.setObjectName("statusLine")
        vs_clear_button = QPushButton("Clear")
        vs_clear_button.clicked.connect(self._clear_vs_table)
        controls.addWidget(self.vs_count_label)
        controls.addStretch()
        controls.addWidget(vs_clear_button)
        root.addLayout(controls)

        self.vs_table = QTableWidget(0, 6)
        self.vs_table.setHorizontalHeaderLabels(["Measurement", "Frame", "ROI", "Feature", "Value", "Status"])
        self.vs_table.verticalHeader().setVisible(False)
        self.vs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.vs_table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.vs_table, 1)
        return widget

    def _on_vs_button(self) -> None:
        """Toggle the value-stream listener."""
        if self._vs_thread is not None:
            self._stop_value_stream()
        else:
            self._start_value_stream()

    @staticmethod
    def _set_button_variant(button: QPushButton, object_name: str) -> None:
        """Swap a button's QSS variant and re-polish so the new style applies at runtime."""
        button.setObjectName(object_name)
        style = button.style()
        style.unpolish(button)
        style.polish(button)

    def _start_value_stream(self) -> None:
        host, port = self._parse_host_port(self.ip_input.currentText())
        self._vs_thread = QThread()
        self._vs_worker = ValueStreamWorker(host, port)
        self._vs_worker.moveToThread(self._vs_thread)
        self._vs_thread.started.connect(self._vs_worker.run)
        self._vs_worker.message.connect(self._on_value_message)
        self._vs_worker.error.connect(lambda m: self.status_bar.showMessage(f"Value stream error: {m[:120]}", 6000))
        self._vs_worker.finished.connect(self._on_vs_finished)
        self._vs_thread.start()
        self.vs_button.setText("Stop Value Stream")
        self._set_button_variant(self.vs_button, "dangerButton")
        self.status_bar.showMessage("Value stream listening — trigger a measurement to see results.", 4000)

    def _stop_value_stream(self) -> None:
        if self._vs_worker is not None:
            self._vs_worker.stop()  # ends run()'s loop -> finished() -> _on_vs_finished

    def _on_vs_finished(self) -> None:
        if self._vs_thread is not None:
            self._vs_thread.quit()
            self._vs_thread.wait(2000)
        self._vs_thread = None
        self._vs_worker = None
        self.vs_button.setText("Start Value Stream")
        self._set_button_variant(self.vs_button, "primaryButton")
        self.status_bar.showMessage("Value stream stopped.", 3000)

    # --- optional realtime event bridge -------------------------------------------------
    def _start_event_bridge(self) -> None:
        """Spin up the event-stream worker after a successful connect. Best-effort: any failure
        just leaves the GUI on its polling fallback (see EventStreamWorker)."""
        if self._events_disabled or self._events_thread is not None or not self._connected:
            return
        host, port = self._parse_host_port(self.ip_input.currentText())
        self._events_thread = QThread()
        self._events_worker = EventStreamWorker(host, port)
        self._events_worker.moveToThread(self._events_thread)
        self._events_thread.started.connect(self._events_worker.run)
        self._events_worker.connected.connect(self._on_events_connected)
        self._events_worker.broadcast.connect(self._on_event)
        self._events_worker.unavailable.connect(self._on_events_unavailable)
        self._events_worker.finished.connect(self._on_events_finished)
        self._events_thread.start()

    def _stop_event_bridge(self) -> None:
        """Tear the event worker down (on disconnect / close). Safe to call when not running."""
        self._events_healthy = False
        if self._events_worker is not None:
            self._events_worker.stop()  # ends run()'s loop -> finished() -> _on_events_finished

    def _sync_jobs_controls(self) -> None:
        """Reflect event-stream health in the jobs controls: while live events drive the list,
        the manual poll toggle is moot, so hide it and show a 'Live updates' indicator instead."""
        live = self._events_healthy
        if hasattr(self, "jobs_live_label"):
            self.jobs_live_label.setVisible(live)
        if hasattr(self, "jobs_autorefresh"):
            self.jobs_autorefresh.setVisible(not live)

    def _on_events_connected(self) -> None:
        """First broadcast arrived — realtime is live, so back the job poll off to slow."""
        self._events_healthy = True
        self.status_bar.showMessage("Realtime events connected — live updates enabled.", 4000)
        self._sync_jobs_controls()
        self._sync_jobs_polling()

    def _on_events_unavailable(self, message: str) -> None:
        """The stream could not run (no websocket-client, or Reverb unreachable) — stay on polling."""
        self._events_healthy = False
        if "websocket-client" in message:
            self._events_disabled = True  # missing dependency won't appear at runtime; don't retry
        logger.info("Realtime events unavailable, using polling fallback: %s", message)
        self._sync_jobs_controls()
        self._sync_jobs_polling()

    def _on_events_finished(self) -> None:
        """Worker ended (stopped, or the stream died). Resume the fast poll and, if the drop was
        unexpected, try to re-establish the stream so it self-heals when Reverb comes back."""
        was_healthy = self._events_healthy
        self._events_healthy = False
        if self._events_thread is not None:
            self._events_thread.quit()
            self._events_thread.wait(2000)
        self._events_thread = None
        self._events_worker = None
        self._sync_jobs_controls()  # events gone → the poll toggle is relevant again
        self._sync_jobs_polling()  # fall back to the fast poll if a job is still active
        if self._connected and not self._events_disabled:
            # Faster retry after a live drop; slow retry while Reverb was never reachable.
            QTimer.singleShot(5000 if was_healthy else 30000, self._start_event_bridge)

    def _on_event(self, channel: str, event: str, data: object) -> None:
        """A realtime broadcast arrived → refresh the affected view. Notification, not source of
        truth: we re-fetch via REST rather than trusting the payload."""
        payload = data if isinstance(data, dict) else {}
        if channel == "exports" and event == "updated":
            self._reload_jobs()  # the realtime replacement for the job poll
        elif channel == "measurement" and event == "updated":
            # Only on a lifecycle transition, and only while the list is on screen (a reload
            # resets paging/selection) — per-frame ticks don't warrant a full list reload.
            if payload.get("status_changed") and self.tabs.currentWidget() is self.measurements_tab:
                self._reload_measurements()
        elif channel == "presets" and event == "changed":
            if self.tabs.currentWidget() is self.presets_tab:
                self._reload_presets()
        elif channel == "settings" and event == "updated":
            self.status_bar.showMessage("Settings changed on the device (externally).", 4000)
        # infos/changed is a lightweight heartbeat; it only serves to prove the stream is live.

    def _on_value_message(self, msg: object) -> None:
        """One ValueMessage arrived → append its per-frame feature results to the table."""
        self._vs_count += 1
        self.vs_count_label.setText(f"Received: {self._vs_count} message(s)")
        for frame in getattr(msg, "frames", None) or []:
            for roi in getattr(frame, "rois", None) or []:
                results = list(getattr(roi, "results", None) or [])
                for drop in getattr(roi, "drops", None) or []:
                    results += list(getattr(drop, "results", None) or [])
                for res in results:
                    name, value_str, status = self._result_cells(res)
                    self._prepend_vs_row(
                        getattr(msg, "id", None), getattr(frame, "index", None), getattr(roi, "index", None),
                        name, value_str, status,
                    )
        # Badge the tab if the results arrived while the user is looking elsewhere.
        if self.tabs.currentWidget() is not self.value_stream_tab:
            self._vs_unseen += 1
            self._update_vs_badge()

    @staticmethod
    def _dot_icon(color: str, size: int = 10) -> QIcon:
        """A small filled circle as a QIcon — the unseen-messages badge on the tab."""
        dpr = 2
        pix = QPixmap(size * dpr, size * dpr)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1 * dpr, 1 * dpr, (size - 2) * dpr, (size - 2) * dpr)
        painter.end()
        pix.setDevicePixelRatio(dpr)
        return QIcon(pix)

    def _update_vs_badge(self) -> None:
        """Show a coloured dot on the Value Stream tab while it has unseen messages."""
        idx = self.tabs.indexOf(self.value_stream_tab)
        if idx >= 0:
            self.tabs.setTabIcon(idx, self._vs_dot_icon if self._vs_unseen else QIcon())

    def _on_tab_changed(self, index: int) -> None:
        """Viewing the Value Stream tab marks its messages as seen (clears the badge);
        opening the History tab lazily loads the first page of frames."""
        widget = self.tabs.widget(index)
        if widget is self.value_stream_tab and self._vs_unseen:
            self._vs_unseen = 0
            self._update_vs_badge()
        if widget is self.history_tab and self._connected and not self._history_loaded:
            self._reload_history()
        if widget is self.presets_tab and self._connected and not self._presets_loaded:
            self._reload_presets()
        if widget is self.machine_tab and self._connected and not self._machine_loaded:
            self._refresh_machine()
        if widget is self.measurements_tab and self._connected and not self._measurements_loaded:
            self._reload_measurements()
        if widget is self.jobs_tab and self._connected and not self._jobs_loaded:
            self._reload_jobs()

    def _prepend_vs_row(self, *cells: object) -> None:
        # Newest results on top: insert at row 0 (within a message the last-iterated,
        # highest-index result ends up topmost).
        self.vs_table.insertRow(0)
        for col, value in enumerate(cells):
            self.vs_table.setItem(0, col, QTableWidgetItem("" if value is None else str(value)))
        self.vs_table.scrollToTop()

    def _clear_vs_table(self) -> None:
        self.vs_table.setRowCount(0)
        self._vs_count = 0
        self._vs_unseen = 0
        self._update_vs_badge()
        self.vs_count_label.setText("No results received yet.")

    # --- History tab (endless-scroll list of recent frames) -----------------

    def _create_history_tab(self) -> QWidget:
        """Endless-scroll list of the most recent frames (the global frame window), rendered
        as the same stacked frame cards as the Multi Shot tab. Pages are fetched lazily as
        the user scrolls toward the bottom."""
        self._history_cursor: str | None = None
        self._history_loading = False
        self._history_exhausted = False
        self._history_loaded = False
        self._history_count = 0
        self._history_gen = 0  # bumped on reset/reload to drop stale in-flight pages

        widget = QWidget()
        root = QVBoxLayout(widget)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(UI_SPACING)

        header = QHBoxLayout()
        title = QLabel("Recent Frames")
        title.setObjectName("sectionHeader")
        self.history_status = QLabel("")
        self.history_status.setObjectName("statusLine")
        self.history_refresh_button = QPushButton("Refresh")
        self.history_refresh_button.clicked.connect(self._reload_history)
        header.addWidget(title)
        header.addWidget(self.history_status)
        header.addStretch(1)
        header.addWidget(self.history_refresh_button)
        root.addLayout(header)

        # Flow layout: cards wrap into as many columns as the width allows and reflow on resize.
        container = QWidget()
        self.history_layout = FlowLayout(container, spacing=UI_SPACING)
        self.history_scroll = _HistoryFlowScrollArea()
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.history_scroll.setWidget(container)
        self.history_scroll.verticalScrollBar().valueChanged.connect(self._on_history_scroll)
        root.addWidget(self.history_scroll, 1)
        return widget

    def _reset_history(self) -> None:
        """Clear the history list and its paging state (on connect/disconnect)."""
        self._history_gen += 1
        self._clear_layout(self.history_layout)
        self._history_cursor = None
        self._history_loading = False
        self._history_exhausted = False
        self._history_loaded = False
        self._history_count = 0
        self.history_status.setText("")

    def _reload_history(self) -> None:
        """(Re)load the frame history from the top."""
        if not self._connected:
            return
        self._history_gen += 1
        self._clear_layout(self.history_layout)
        self._history_cursor = None
        self._history_exhausted = False
        self._history_loading = False
        self._history_count = 0
        self._history_loaded = True
        self.history_status.setText("Loading…")
        self._load_history_page()

    def _load_history_page(self) -> None:
        """Fetch the next page of frames off-thread (guarded against overlap/exhaustion)."""
        if self._history_loading or self._history_exhausted or not self._connected:
            return
        host, port = self._parse_host_port(self.ip_input.currentText())
        self._history_loading = True
        task = _HistoryPageTask(host, port, self._history_cursor, self.HISTORY_PAGE_SIZE, self._history_gen)
        task.signals.loaded.connect(self._on_history_page_loaded)
        task.signals.error.connect(self._on_history_error)
        QThreadPool.globalInstance().start(task)

    def _on_history_page_loaded(self, frames: list, next_cursor: object, generation: int) -> None:
        if generation != self._history_gen:
            return  # a page from before a reload/disconnect — drop it
        self._history_loading = False
        host, port = self._parse_host_port(self.ip_input.currentText())
        base_url = f"http://{host}:{port}"
        for frame in frames:
            card = self._make_frame_card(frame, base_url, use_id=True)  # history: title by frame id
            card.setFixedWidth(self.HISTORY_CARD_WIDTH)
            self.history_layout.addWidget(card)
        self._history_count += len(frames)
        self.history_scroll.sync_height()  # grow the container so the new rows are scrollable
        self._history_cursor = next_cursor if isinstance(next_cursor, str) else None
        if not self._history_cursor:
            self._history_exhausted = True
        if self._history_count == 0:
            self.history_status.setText("No frames yet.")
        else:
            self.history_status.setText(f"{self._history_count} frame(s)" + (" — end" if self._history_exhausted else ""))
        # A short first page may not fill the viewport; keep pulling until it scrolls.
        QTimer.singleShot(0, self._maybe_fill_history)

    def _on_history_error(self, message: str, generation: int) -> None:
        if generation != self._history_gen:
            return
        self._history_loading = False
        self.history_status.setText(f"Failed to load: {message[:80]}")
        self.status_bar.showMessage(f"History error: {message[:120]}", 6000)

    def _maybe_fill_history(self) -> None:
        """If the loaded content does not fill the viewport yet, pull the next page."""
        if self._history_exhausted or self._history_loading:
            return
        if self.history_scroll.verticalScrollBar().maximum() == 0:
            self._load_history_page()

    def _on_history_scroll(self, value: int) -> None:
        """Endless scroll: nearing the bottom pulls the next page."""
        bar = self.history_scroll.verticalScrollBar()
        if bar.maximum() - value <= 400:
            self._load_history_page()

    # --- shared off-thread call helper (Presets / Machine tabs) --------------

    def _run_api(self, fn: Any, on_done: Any = None, on_error: Any = None) -> None:
        """Run an API operation off-thread against a fresh client and route the result back
        to the GUI thread (see :class:`_ApiCallTask`). ``fn`` takes a connected client."""
        host, port = self._parse_host_port(self.ip_input.currentText())
        task = _ApiCallTask(host, port, fn)
        if on_done is not None:
            task.signals.done.connect(on_done)
        task.signals.error.connect(on_error or (lambda m: self.status_bar.showMessage(f"Error: {m[:120]}", 6000)))
        QThreadPool.globalInstance().start(task)

    def _busy(self) -> bool:
        """True while a measurement/stream worker holds the device — used to refuse a
        device-mutating action (load preset, machine command) that must not run concurrently."""
        if self.worker_thread is not None and self.worker_thread.isRunning():
            QMessageBox.warning(self, "Busy", "Another operation is in progress. Try again once it finishes.")
            return True
        return False

    # --- Measurements tab ----------------------------------------------------

    def _create_measurements_tab(self) -> QWidget:
        """Measurement history: list past measurements (``list_measurements``, cursor-paginated,
        with optional type/status filters) and delete a selected one (``delete_measurement``)."""
        self._measurements: list[Measurement] = []
        self._measurements_cursor: str | None = None
        self._measurements_loaded = False

        widget = QWidget()
        root = QVBoxLayout(widget)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(UI_SPACING)

        controls = QHBoxLayout()
        title = QLabel("Measurements")
        title.setObjectName("sectionHeader")
        self.measurements_status = QLabel("")
        self.measurements_status.setObjectName("statusLine")
        self.meas_type_filter = QComboBox()
        self.meas_type_filter.addItems(["all types", "singleshot", "multishot", "video", "production", "continuous_singleshot"])
        self.meas_status_filter = QComboBox()
        self.meas_status_filter.addItems(["all statuses", "done", "in_progress", "waiting", "cancelled", "no_trigger_received", "error"])
        self.measurements_refresh_button = QPushButton("Refresh")
        self.measurements_refresh_button.clicked.connect(self._reload_measurements)
        # Connect the filter combos only after populating them, so building the tab does not
        # trigger a reload (and _reload_measurements is a no-op until connected anyway).
        self.meas_type_filter.currentIndexChanged.connect(lambda *_: self._reload_measurements())
        self.meas_status_filter.currentIndexChanged.connect(lambda *_: self._reload_measurements())
        controls.addWidget(title)
        controls.addWidget(self.measurements_status)
        controls.addStretch(1)
        controls.addWidget(QLabel("Type:"))
        controls.addWidget(self.meas_type_filter)
        controls.addWidget(QLabel("Status:"))
        controls.addWidget(self.meas_status_filter)
        controls.addWidget(self.measurements_refresh_button)
        root.addLayout(controls)

        self.measurements_table = QTableWidget(0, 6)
        self.measurements_table.setHorizontalHeaderLabels(["ID", "Type", "Status", "Progress", "Frames", "Created"])
        m_vheader = self.measurements_table.verticalHeader()
        if m_vheader is not None:
            m_vheader.setVisible(False)
        self.measurements_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.measurements_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.measurements_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        m_header = self.measurements_table.horizontalHeader()
        if m_header is not None:
            m_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            m_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)  # created column takes the slack
        self.measurements_table.itemSelectionChanged.connect(self._update_measurement_buttons)
        root.addWidget(self.measurements_table, 1)

        actions = QHBoxLayout()
        self.measurements_more_button = QPushButton("Load more")
        self.measurements_more_button.clicked.connect(self._load_measurements_page)
        self.measurement_delete_button = QPushButton("Delete")
        self.measurement_delete_button.setObjectName("dangerButton")
        self.measurement_delete_button.clicked.connect(self._delete_selected_measurement)
        actions.addWidget(self.measurements_more_button)
        actions.addStretch(1)
        actions.addWidget(self.measurement_delete_button)
        root.addLayout(actions)

        self._update_measurement_buttons()
        return widget

    def _measurement_filters(self) -> dict[str, Any]:
        """Only the active (non-"all") filters, as list_measurements query params."""
        filters: dict[str, Any] = {}
        if self.meas_type_filter.currentIndex() > 0:
            filters["type"] = self.meas_type_filter.currentText()
        if self.meas_status_filter.currentIndex() > 0:
            filters["status"] = self.meas_status_filter.currentText()
        return filters

    def _reset_measurements(self) -> None:
        self._measurements = []
        self._measurements_cursor = None
        self._measurements_loaded = False
        if hasattr(self, "measurements_table"):
            self.measurements_table.setRowCount(0)
            self.measurements_status.setText("")
        self._update_measurement_buttons()

    def _reload_measurements(self) -> None:
        """Reset to the first page (applying the current filters) and load it."""
        if not self._connected:
            return
        self._measurements = []
        self._measurements_cursor = None
        self._measurements_loaded = True
        self.measurements_table.setRowCount(0)
        self._load_measurements_page()

    def _load_measurements_page(self) -> None:
        """Fetch the next cursor page (list_measurements) and append it to the table."""
        if not self._connected:
            return
        filters = self._measurement_filters()
        cursor = self._measurements_cursor
        self.measurements_status.setText("Loading…")
        self._run_api(
            lambda api: api.list_measurements(cursor=cursor, per_page=50, filters=filters),
            self._on_measurements_page, self._on_measurements_error,
        )

    def _on_measurements_page(self, page: object) -> None:
        self._measurements.extend(page.data)  # page: Page[Measurement]
        table = self.measurements_table
        for m in page.data:
            row = table.rowCount()
            table.insertRow(row)
            cells = [
                m.id, m.type, m.status,
                f"{m.progress}%" if m.progress is not None else "",
                m.frames_count if m.frames_count is not None else "",
                (m.created_at or "")[:19].replace("T", " "),
            ]
            for col, value in enumerate(cells):
                table.setItem(row, col, QTableWidgetItem("" if value is None else str(value)))
        self._measurements_cursor = page.next_cursor
        more = " (more available)" if page.next_cursor else ""
        self.measurements_status.setText(f"{len(self._measurements)} measurement(s){more}.")
        self._update_measurement_buttons()

    def _on_measurements_error(self, message: str) -> None:
        self.measurements_status.setText("")
        self.status_bar.showMessage(f"Measurements error: {message[:120]}", 6000)

    def _selected_measurement(self) -> Measurement | None:
        if not hasattr(self, "measurements_table"):
            return None
        row = self.measurements_table.currentRow()
        return self._measurements[row] if 0 <= row < len(self._measurements) else None

    def _update_measurement_buttons(self) -> None:
        self.measurement_delete_button.setEnabled(self._connected and self._selected_measurement() is not None)
        self.measurements_more_button.setEnabled(self._connected and bool(self._measurements_cursor))

    def _delete_selected_measurement(self) -> None:
        m = self._selected_measurement()
        if m is None or not self._connected:
            return
        if QMessageBox.question(
            self, "Delete measurement",
            f"Delete measurement #{m.id} and all its frames, results and images?\n\nThis cannot be undone.",
        ) != QMessageBox.StandardButton.Yes:
            return
        mid = m.id
        self._run_api(lambda api: api.delete_measurement(mid), lambda _r: self._on_measurement_deleted(mid), self._on_measurements_error)

    def _on_measurement_deleted(self, mid: int) -> None:
        self.status_bar.showMessage(f"Measurement #{mid} deleted.", 5000)
        self._reload_measurements()

    # --- Exports & Jobs tab --------------------------------------------------

    def _create_jobs_tab(self) -> QWidget:
        """Demonstrate the full export/download surface in one place:

        * queue an async export job (measurement- or frame-scoped) — ``create_measurement_export`` /
          ``create_frame_export``;
        * stream a direct ZIP download — ``download_measurement`` / ``download_frames``;
        * track / abort / delete / download the resulting jobs — ``list_jobs`` / ``get_job`` /
          ``abort_job`` / ``delete_job`` / ``download_export``.
        """
        self._jobs: list[ExportJob] = []
        self._jobs_loaded = False

        widget = QWidget()
        root = QVBoxLayout(widget)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(UI_SPACING)

        # -- Create export / direct download form --------------------------
        self.jobs_form_box = QGroupBox("Create export / direct download")
        self.jobs_form_box.setObjectName("card")
        form = QGridLayout(self.jobs_form_box)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.export_scope_combo = QComboBox()
        self.export_scope_combo.addItems(["Measurement", "Frames (filtered)"])
        self.export_scope_combo.currentIndexChanged.connect(self._update_export_form)
        self.export_measurement_id = QSpinBox()
        self.export_measurement_id.setRange(1, 10_000_000)
        self.export_format_combo = QComboBox()
        self.export_format_combo.addItems(["csv", "json", "images", "attachments"])
        self.export_format_combo.currentIndexChanged.connect(self._update_export_form)
        self.export_config_combo = QComboBox()
        self.export_config_combo.addItems(["excel_global", "excel_dach", "python_pandas", "custom"])

        form.addWidget(QLabel("Scope:"), 0, 0)
        form.addWidget(self.export_scope_combo, 0, 1)
        self.export_mid_label = QLabel("Measurement ID:")
        form.addWidget(self.export_mid_label, 0, 2)
        form.addWidget(self.export_measurement_id, 0, 3)
        form.addWidget(QLabel("Format:"), 1, 0)
        form.addWidget(self.export_format_combo, 1, 1)
        self.export_config_label = QLabel("CSV config:")
        form.addWidget(self.export_config_label, 1, 2)
        form.addWidget(self.export_config_combo, 1, 3)
        self.export_hint = QLabel("")
        self.export_hint.setObjectName("statusLine")
        self.export_hint.setWordWrap(True)
        form.addWidget(self.export_hint, 2, 0, 1, 4)

        form_buttons = QHBoxLayout()
        form_buttons.setSpacing(UI_SPACING)  # gap between the two action buttons
        self.export_job_button = QPushButton("Start Export Job")
        self.export_job_button.setObjectName("primaryButton")
        self.export_job_button.clicked.connect(self._start_export_job)
        self.export_download_button = QPushButton("Direct Download (ZIP)…")
        self.export_download_button.clicked.connect(self._direct_download)
        form_buttons.addWidget(self.export_job_button)
        form_buttons.addWidget(self.export_download_button)
        form_buttons.addStretch(1)
        form.addLayout(form_buttons, 3, 0, 1, 4)
        root.addWidget(self.jobs_form_box)

        # -- Export-jobs table + row actions -------------------------------
        controls = QHBoxLayout()
        title = QLabel("Export Jobs")
        title.setObjectName("sectionHeader")
        self.jobs_status = QLabel("")
        self.jobs_status.setObjectName("statusLine")
        # Auto-refresh polls list_jobs every 3 s while any job is still non-terminal, and
        # stops on its own once every job has settled (complete/failed/cancelled).
        self.jobs_autorefresh = QCheckBox("Auto-refresh (3s)")
        self.jobs_autorefresh.setChecked(True)
        self.jobs_autorefresh.setToolTip("Poll the job list every 3 s until all exports reach a terminal state.")
        self.jobs_autorefresh.toggled.connect(lambda *_: self._sync_jobs_polling())
        # Shown instead of the poll checkbox while the event stream is live: job updates then
        # arrive via the exports channel broadcasts, so the manual poll toggle is moot.
        self.jobs_live_label = QLabel("⚡ Live updates")
        self.jobs_live_label.setObjectName("statusLine")
        self.jobs_live_label.setToolTip("Export jobs update in real time via the event stream; a slow safety poll still runs in the background.")
        self.jobs_live_label.setVisible(False)
        self._jobs_loading = False
        self._jobs_poll_timer = QTimer(self)
        self._jobs_poll_timer.setInterval(self._JOBS_POLL_FAST_MS)
        self._jobs_poll_timer.timeout.connect(self._reload_jobs)
        self.jobs_refresh_button = QPushButton("Refresh")
        self.jobs_refresh_button.clicked.connect(self._reload_jobs)
        controls.addWidget(title)
        controls.addWidget(self.jobs_status)
        controls.addStretch(1)
        controls.addWidget(self.jobs_live_label)
        controls.addWidget(self.jobs_autorefresh)
        controls.addWidget(self.jobs_refresh_button)
        root.addLayout(controls)

        self.jobs_table = QTableWidget(0, 6)
        self.jobs_table.setHorizontalHeaderLabels(["ID", "Measurement", "Format", "Status", "Progress", "Created"])
        vheader = self.jobs_table.verticalHeader()
        if vheader is not None:
            vheader.setVisible(False)
        self.jobs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.jobs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.jobs_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        j_header = self.jobs_table.horizontalHeader()
        if j_header is not None:
            j_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            j_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)  # created column takes the slack
        self.jobs_table.itemSelectionChanged.connect(self._update_job_buttons)
        root.addWidget(self.jobs_table, 1)

        actions = QHBoxLayout()
        self.job_download_button = QPushButton("Download…")
        self.job_download_button.setObjectName("primaryButton")
        self.job_download_button.clicked.connect(self._download_selected_job)
        self.job_abort_button = QPushButton("Abort")
        self.job_abort_button.clicked.connect(lambda: self._abort_selected_job(force=False))
        self.job_force_abort_button = QPushButton("Force Abort")
        self.job_force_abort_button.clicked.connect(lambda: self._abort_selected_job(force=True))
        self.job_delete_button = QPushButton("Delete")
        self.job_delete_button.setObjectName("dangerButton")
        self.job_delete_button.clicked.connect(self._delete_selected_job)
        actions.addWidget(self.job_download_button)
        actions.addWidget(self.job_abort_button)
        actions.addWidget(self.job_force_abort_button)
        actions.addStretch(1)
        actions.addWidget(self.job_delete_button)
        root.addLayout(actions)

        self._update_export_form()
        self._update_job_buttons()
        return widget

    # form helpers

    def _update_export_form(self, *_: object) -> None:
        """Keep the export form coherent: CSV-config only applies to csv, and the hint spells
        out which formats each action accepts (export jobs: csv/json; direct download also
        images, plus attachments for a measurement)."""
        is_measurement = self.export_scope_combo.currentIndex() == 0
        fmt = self.export_format_combo.currentText()
        self.export_config_combo.setEnabled(fmt == "csv")
        self.export_config_label.setEnabled(fmt == "csv")
        if is_measurement:
            self.export_hint.setText("Measurement scope — ID required. Export job: csv/json. Direct download: csv/json/images/attachments.")
        else:
            self.export_hint.setText("Frames scope — Measurement ID is an optional filter (leave at 1+ to scope; ignored by 'all'). Export job: csv/json. Direct download: csv/json/images.")

    def _export_params(self) -> tuple[bool, int, str, str | None]:
        is_measurement = self.export_scope_combo.currentIndex() == 0
        mid = self.export_measurement_id.value()
        fmt = self.export_format_combo.currentText()
        cfg = self.export_config_combo.currentText() if fmt == "csv" else None
        return is_measurement, mid, fmt, cfg

    def _start_export_job(self) -> None:
        """POST an async export job (csv/json only) for the current scope, then refresh the list."""
        if not self._connected:
            return
        is_measurement, mid, fmt, cfg = self._export_params()
        if fmt not in ("csv", "json"):
            QMessageBox.information(self, "Export job", "Export jobs support only csv or json.\nUse Direct Download for images/attachments.")
            return
        if is_measurement:
            def fn(api: dropticalAPIClient) -> ExportJob:
                return api.create_measurement_export(mid, format=fmt, config_name=cfg)
        else:
            filters = {"measurement_id": mid} if mid else {}
            def fn(api: dropticalAPIClient) -> ExportJob:
                return api.create_frame_export(format=fmt, config_name=cfg, filters=filters)
        self.jobs_status.setText("Starting export job…")
        self._run_api(fn, self._on_export_started, self._on_jobs_error)

    def _on_export_started(self, job: object) -> None:
        self.status_bar.showMessage(f"Export job #{getattr(job, 'id', '?')} queued.", 5000)
        self._reload_jobs()

    def _direct_download(self) -> None:
        """Stream a filtered ZIP straight to disk (no job) via download_measurement / download_frames."""
        if not self._connected:
            return
        is_measurement, mid, fmt, cfg = self._export_params()
        if is_measurement and fmt not in ("images", "csv", "json", "attachments"):
            QMessageBox.information(self, "Download", "Measurement download supports images/csv/json/attachments.")
            return
        if not is_measurement and fmt not in ("images", "csv", "json"):
            QMessageBox.information(self, "Download", "Frame download supports images/csv/json.")
            return
        suggested = f"measurement_{mid}_{fmt}.zip" if is_measurement else f"frames_{fmt}.zip"
        path, _ = QFileDialog.getSaveFileName(self, "Save export ZIP", suggested, "ZIP archive (*.zip)")
        if not path:
            return
        filters = {"measurement_id": mid} if (not is_measurement and mid) else {}

        def fn(api: dropticalAPIClient) -> str:
            if is_measurement:
                data = api.download_measurement(mid, format=fmt, config_name=cfg)
            else:
                data = api.download_frames(format=fmt, config_name=cfg, filters=filters)
            with open(path, "wb") as fh:
                fh.write(data)
            return path

        self.jobs_status.setText("Downloading…")
        self._run_api(fn, self._on_download_saved, self._on_jobs_error)

    def _on_download_saved(self, path: object) -> None:
        self.jobs_status.setText("")
        self.status_bar.showMessage(f"Saved {path}", 6000)

    # jobs list + row actions

    # Statuses at which an export job stops progressing (see ExportJobStatus). `deleted` only
    # appears in broadcast events, never in REST responses, but is terminal for completeness.
    _JOB_TERMINAL_STATUSES = frozenset({"complete", "failed", "cancelled", "deleted"})
    _JOBS_POLL_FAST_MS = 3000  # no realtime events: poll actively
    _JOBS_POLL_SLOW_MS = 15000  # events healthy: they drive the refreshes, this is just a safety net

    def _reset_jobs(self) -> None:
        self._jobs = []
        self._jobs_loaded = False
        self._jobs_loading = False
        if hasattr(self, "_jobs_poll_timer"):
            self._jobs_poll_timer.stop()
        if hasattr(self, "jobs_table"):
            self.jobs_table.setRowCount(0)
            self.jobs_status.setText("")
        self._update_job_buttons()

    def _reload_jobs(self) -> None:
        if not self._connected or self._jobs_loading:
            return  # skip if a fetch is already in flight (e.g. a poll tick during a slow list)
        self._jobs_loaded = True
        self._jobs_loading = True
        self.jobs_status.setText("Loading…")
        self._run_api(lambda api: api.list_jobs(per_page=100).data, self._on_jobs_loaded, self._on_jobs_error)

    def _on_jobs_loaded(self, jobs: object) -> None:
        self._jobs_loading = False
        self._jobs = list(jobs)  # list[ExportJob]
        table = self.jobs_table
        table.setRowCount(0)
        for job in self._jobs:
            row = table.rowCount()
            table.insertRow(row)
            cells = [
                job.id, job.measurement_id, job.format, job.status,
                f"{job.progress}%" if job.progress is not None else "",
                (job.created_at or "")[:19].replace("T", " "),
            ]
            for col, value in enumerate(cells):
                table.setItem(row, col, QTableWidgetItem("" if value is None else str(value)))
        pending = sum(1 for j in self._jobs if j.status not in self._JOB_TERMINAL_STATUSES)
        suffix = f" · auto-refreshing {pending} active…" if (pending and self.jobs_autorefresh.isChecked()) else ""
        self.jobs_status.setText(f"{len(self._jobs)} job(s).{suffix}")
        self._update_job_buttons()
        self._sync_jobs_polling()  # start/stop the 3 s poll depending on whether any job is active

    def _on_jobs_error(self, message: str) -> None:
        self._jobs_loading = False
        self.jobs_status.setText("")
        self._jobs_poll_timer.stop()  # back off on error rather than hammering a failing endpoint
        self.status_bar.showMessage(f"Jobs error: {message[:120]}", 6000)

    def _sync_jobs_polling(self) -> None:
        """Run the poll only while auto-refresh is on, we're connected, and at least one job
        is still non-terminal; stop as soon as every job has reached a terminal state. When the
        realtime event stream is healthy, drop to the slow safety interval — the exports channel
        broadcasts drive the refreshes, the poll only guards against a silent stream stall."""
        if not hasattr(self, "_jobs_poll_timer"):
            return
        active = any(j.status not in self._JOB_TERMINAL_STATUSES for j in self._jobs)
        should_poll = self.jobs_autorefresh.isChecked() and self._connected and active
        interval = self._JOBS_POLL_SLOW_MS if self._events_healthy else self._JOBS_POLL_FAST_MS
        if self._jobs_poll_timer.interval() != interval:
            self._jobs_poll_timer.setInterval(interval)
        if should_poll and not self._jobs_poll_timer.isActive():
            self._jobs_poll_timer.start()
        elif not should_poll and self._jobs_poll_timer.isActive():
            self._jobs_poll_timer.stop()

    def _selected_job(self) -> ExportJob | None:
        if not hasattr(self, "jobs_table"):
            return None
        row = self.jobs_table.currentRow()
        return self._jobs[row] if 0 <= row < len(self._jobs) else None

    def _update_job_buttons(self) -> None:
        job = self._selected_job()
        status = job.status if job else None
        active = status is not None and status not in self._JOB_TERMINAL_STATUSES
        self.job_download_button.setEnabled(self._connected and status == "complete")
        self.job_abort_button.setEnabled(self._connected and active)
        self.job_force_abort_button.setEnabled(self._connected and status == "aborting")
        self.job_delete_button.setEnabled(self._connected and job is not None and not active)

    def _download_selected_job(self) -> None:
        """Re-fetch the job (get_job) for its current download_url, then download_export to disk."""
        job = self._selected_job()
        if job is None or not self._connected:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save export", f"export_job_{job.id}.zip", "ZIP archive (*.zip)")
        if not path:
            return
        jid = job.id

        def fn(api: dropticalAPIClient) -> str:
            fresh = api.get_job(jid)          # refresh for the current status / download_url
            data = api.download_export(fresh)  # follows fresh.download_url
            with open(path, "wb") as fh:
                fh.write(data)
            return path

        self.jobs_status.setText("Downloading job…")
        self._run_api(fn, self._on_download_saved, self._on_jobs_error)

    def _abort_selected_job(self, *, force: bool) -> None:
        job = self._selected_job()
        if job is None or not self._connected:
            return
        jid = job.id
        self._run_api(lambda api: api.abort_job(jid, force=force), lambda _r: self._reload_jobs(), self._on_jobs_error)

    def _delete_selected_job(self) -> None:
        job = self._selected_job()
        if job is None or not self._connected:
            return
        if QMessageBox.question(self, "Delete job", f"Delete export job #{job.id}?") != QMessageBox.StandardButton.Yes:
            return
        jid = job.id
        self._run_api(lambda api: api.delete_job(jid), lambda _r: self._reload_jobs(), self._on_jobs_error)

    # --- Presets tab ---------------------------------------------------------

    def _create_presets_tab(self) -> QWidget:
        """Manage the device's presets (recipes): list them, load one onto the device, create
        new presets / versions, edit, and delete. Wraps the client's preset endpoints."""
        self._presets: list[Preset] = []
        self._presets_loaded = False

        widget = QWidget()
        root = QVBoxLayout(widget)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(UI_SPACING)

        controls = QHBoxLayout()
        title = QLabel("Presets")
        title.setObjectName("sectionHeader")
        self.presets_status = QLabel("")
        self.presets_status.setObjectName("statusLine")
        self.presets_include_deleted = QCheckBox("Include deleted")
        self.presets_include_deleted.stateChanged.connect(lambda _=0: self._reload_presets())
        self.presets_refresh_button = QPushButton("Refresh")
        self.presets_refresh_button.clicked.connect(self._reload_presets)
        controls.addWidget(title)
        controls.addWidget(self.presets_status)
        controls.addStretch(1)
        controls.addWidget(self.presets_include_deleted)
        controls.addWidget(self.presets_refresh_button)
        root.addLayout(controls)

        self.presets_table = QTableWidget(0, 6)
        self.presets_table.setHorizontalHeaderLabels(["ID", "GID", "Version", "Name", "Comment", "Camera SNR"])
        self.presets_table.verticalHeader().setVisible(False)
        self.presets_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.presets_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.presets_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        p_header = self.presets_table.horizontalHeader()
        if p_header is not None:
            p_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            p_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)  # comment column takes the slack
        self.presets_table.itemSelectionChanged.connect(self._update_preset_buttons)
        self.presets_table.itemDoubleClicked.connect(lambda *_: self._load_selected_preset())
        root.addWidget(self.presets_table, 1)

        actions = QHBoxLayout()
        self.preset_load_button = QPushButton("Load")
        self.preset_load_button.setObjectName("primaryButton")
        self.preset_load_button.clicked.connect(self._load_selected_preset)
        self.preset_version_button = QPushButton("New Version")
        self.preset_version_button.clicked.connect(self._new_selected_preset_version)
        self.preset_edit_button = QPushButton("Edit")
        self.preset_edit_button.clicked.connect(self._edit_selected_preset)
        self.preset_delete_button = QPushButton("Delete")
        self.preset_delete_button.setObjectName("dangerButton")
        self.preset_delete_button.clicked.connect(self._delete_selected_preset)
        actions.addWidget(self.preset_load_button)
        actions.addWidget(self.preset_version_button)
        actions.addWidget(self.preset_edit_button)
        actions.addStretch(1)
        actions.addWidget(self.preset_delete_button)
        root.addLayout(actions)

        create_box, create_form = self._section_card("Create Preset")
        self.preset_new_name = QLineEdit()
        self.preset_new_name.setPlaceholderText("Name (3–32 characters)")
        self.preset_new_comment = QLineEdit()
        self.preset_new_comment.setPlaceholderText("Comment (optional)")
        self.preset_create_button = QPushButton("Create")
        self.preset_create_button.setObjectName("primaryButton")
        self.preset_create_button.clicked.connect(self._create_preset)
        create_form.addRow("Name:", self.preset_new_name)
        create_form.addRow("Comment:", self.preset_new_comment)
        create_form.addRow("", self.preset_create_button)
        root.addWidget(create_box)

        self._update_preset_buttons()
        return widget

    def _selected_preset(self) -> Preset | None:
        row = self.presets_table.currentRow()
        return self._presets[row] if 0 <= row < len(self._presets) else None

    def _update_preset_buttons(self) -> None:
        has = self._connected and self._selected_preset() is not None
        for b in (self.preset_load_button, self.preset_version_button, self.preset_edit_button, self.preset_delete_button):
            b.setEnabled(has)

    def _reset_presets(self) -> None:
        """Clear the preset list and its loaded flag (on connect/disconnect)."""
        self._presets = []
        self._presets_loaded = False
        self.presets_table.setRowCount(0)
        self.presets_status.setText("")
        self._update_preset_buttons()

    def _reload_presets(self) -> None:
        """(Re)load the preset list from the device off-thread."""
        if not self._connected:
            return
        self._presets_loaded = True
        self.presets_status.setText("Loading…")
        include_deleted = self.presets_include_deleted.isChecked()
        self._run_api(
            lambda api, inc=include_deleted: api.list_presets(include_deleted=inc, sort_by="id", direction="asc"),
            self._on_presets_loaded,
            self._on_presets_error,
        )

    def _on_presets_loaded(self, presets: object) -> None:
        self._presets = list(presets or [])  # type: ignore[arg-type]
        table = self.presets_table
        table.setRowCount(len(self._presets))
        for r, p in enumerate(self._presets):
            cells = [f"#{p.id}", str(p.gid), f"v{p.version}", p.name, p.comment or "", p.camera_snr or ""]
            for c, val in enumerate(cells):
                table.setItem(r, c, QTableWidgetItem(val))
        self.presets_status.setText(f"{len(self._presets)} preset(s)")
        self._update_preset_buttons()

    def _on_presets_error(self, message: str) -> None:
        self.presets_status.setText(f"Failed: {message[:80]}")
        self.status_bar.showMessage(f"Presets error: {message[:120]}", 6000)

    def _preset_action_done(self, message: str) -> None:
        """A preset mutation succeeded → report it and refresh the list."""
        self.status_bar.showMessage(message, 4000)
        self._reload_presets()

    def _load_selected_preset(self) -> None:
        p = self._selected_preset()
        if p is None or self._busy():
            return
        self.presets_status.setText(f"Loading preset '{p.name}'…")
        self._run_api(
            lambda api, gid=p.gid, ver=p.version: api.load_preset(gid=gid, version=ver),
            lambda _r, name=p.name: self._on_preset_loaded_onto_device(name),
            self._on_presets_error,
        )

    def _on_preset_loaded_onto_device(self, name: str) -> None:
        """A preset was applied → its settings are now active, so re-fetch them and refresh
        the control tabs so the UI reflects the freshly loaded recipe."""
        self.status_bar.showMessage(f"Preset '{name}' loaded.", 4000)
        self.presets_status.setText(f"Loaded '{name}'.")
        self._run_api(lambda api: api.get_settings(), self._populate_ui_with_settings, self._on_presets_error)

    def _new_selected_preset_version(self) -> None:
        p = self._selected_preset()
        if p is None or self._busy():
            return
        text, ok = QInputDialog.getText(self, "New Version", f"Comment for the new version of '{p.name}' (optional):")
        if not ok:
            return
        comment = text.strip() or None
        self._run_api(
            lambda api, pid=p.id, c=comment: api.create_preset_version(pid, comment=c),
            lambda _r, name=p.name: self._preset_action_done(f"New version of '{name}' created."),
            self._on_presets_error,
        )

    def _edit_selected_preset(self) -> None:
        p = self._selected_preset()
        if p is None or self._busy():
            return
        dlg = _PresetDialog(self, name=p.name, comment=p.comment or "", title=f"Edit Preset #{p.id}")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, comment = dlg.values()
        if not (3 <= len(name) <= 32):
            self.presets_status.setText("Name must be 3–32 characters.")
            return
        self._run_api(
            lambda api, pid=p.id, n=name, c=comment or None: api.edit_preset(pid, n, comment=c),
            lambda _r, n=name: self._preset_action_done(f"Preset '{n}' updated."),
            self._on_presets_error,
        )

    def _delete_selected_preset(self) -> None:
        p = self._selected_preset()
        if p is None or self._busy():
            return
        reply = QMessageBox.warning(
            self, "Delete Preset",
            f"Delete preset '{p.name}' (#{p.id})?\n\nThis cannot be undone. The currently loaded "
            "preset cannot be deleted — switch to another one first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_api(
            lambda api, pid=p.id: api.delete_preset(pid),
            lambda _r, name=p.name: self._preset_action_done(f"Preset '{name}' deleted."),
            self._on_presets_error,
        )

    def _create_preset(self) -> None:
        if not self._connected or self._busy():
            return
        name = self.preset_new_name.text().strip()
        comment = self.preset_new_comment.text().strip() or None
        if not (3 <= len(name) <= 32):
            self.presets_status.setText("Name must be 3–32 characters.")
            return
        self._run_api(
            lambda api, n=name, c=comment: api.create_preset(n, comment=c),
            lambda _r, n=name: self._on_preset_created(n),
            self._on_presets_error,
        )

    def _on_preset_created(self, name: str) -> None:
        self.preset_new_name.clear()
        self.preset_new_comment.clear()
        self._preset_action_done(f"Preset '{name}' created.")

    # --- Machine tab ---------------------------------------------------------

    def _create_machine_tab(self) -> QWidget:
        """Device info + control plane: readiness/info, GPIO levels, the feature catalogue,
        maintenance actions and the destructive commands (each behind a confirmation)."""
        self._mi: dict[str, QLabel] = {}  # info key -> value label
        self._gpo_checkboxes: dict[str, QCheckBox] = {}
        self._machine_buttons: list[QPushButton] = []
        self._machine_loaded = False

        outer = QWidget()
        outer_root = QVBoxLayout(outer)
        outer_root.setContentsMargins(4, 4, 4, 4)
        outer_root.setSpacing(UI_SPACING)

        header = QHBoxLayout()
        title = QLabel("Machine")
        title.setObjectName("sectionHeader")
        self.machine_status = QLabel("")
        self.machine_status.setObjectName("statusLine")
        self.machine_refresh_button = QPushButton("Refresh")
        self.machine_refresh_button.clicked.connect(self._refresh_machine)
        header.addWidget(title)
        header.addWidget(self.machine_status)
        header.addStretch(1)
        header.addWidget(self.machine_refresh_button)
        outer_root.addLayout(header)

        # Everything below scrolls, so the danger zone stays reachable on small windows.
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 0, 9, 0)
        root.setSpacing(UI_SPACING)

        # Readiness verdict (computed from infos, like the machine example).
        ready_box, ready_form = self._section_card("Readiness")
        self.machine_readiness = QLabel("—")
        self.machine_readiness.setObjectName("metaValue")
        self.machine_readiness.setWordWrap(True)
        ready_form.addRow("Ready for a measurement:", self.machine_readiness)
        root.addWidget(ready_box)

        # Device info: system / analysis unit / camera / storage, in a two-column grid.
        info_row = QHBoxLayout()
        info_row.setSpacing(UI_SPACING)
        info_row.addWidget(self._machine_kv_card("System", [
            ("Status:", "sys_status"), ("Mode:", "sys_mode"), ("Action:", "sys_action"),
            ("Bundle:", "sys_bundle"), ("Software:", "sys_sw"), ("GUI:", "sys_gui")]))
        info_row.addWidget(self._machine_kv_card("Analysis Unit", [
            ("Hardware:", "au_hardware"), ("Order No.:", "au_order"), ("Serial:", "au_serial"),
            ("Mfg. Date:", "au_mfg"), ("Firmware:", "au_fw")]))
        root.addLayout(info_row)
        info_row2 = QHBoxLayout()
        info_row2.setSpacing(UI_SPACING)
        info_row2.addWidget(self._machine_kv_card("Camera Unit", [
            ("Type:", "cam_type"), ("Serial:", "cam_serial"), ("Hardware:", "cam_hardware"),
            ("Firmware:", "cam_fw"), ("Max FPS:", "cam_maxfps"), ("Status:", "cam_status")]))
        info_row2.addWidget(self._machine_kv_card("Storage", [
            ("Free:", "st_free"), ("Used:", "st_used"), ("Total:", "st_size")]))
        root.addLayout(info_row2)

        # GPIO: read-only GPI levels + toggleable GPO outputs (rebuilt on refresh).
        gpio_box = QGroupBox("GPIO")
        gpio_box.setObjectName("card")
        self.machine_gpio_layout = QVBoxLayout(gpio_box)
        self.machine_gpio_layout.setSpacing(6)
        self._gpio_placeholder = QLabel("Refresh to read GPIO levels.")
        self._gpio_placeholder.setObjectName("statusLine")
        self.machine_gpio_layout.addWidget(self._gpio_placeholder)
        root.addWidget(gpio_box)

        # Feature catalogue (id -> name / unit / type), from GET /features.
        feat_box = QGroupBox("Feature Catalogue")
        feat_box.setObjectName("card")
        feat_layout = QVBoxLayout(feat_box)
        self.machine_features_table = QTableWidget(0, 5)
        self.machine_features_table.setHorizontalHeaderLabels(["ID", "Name", "Unit", "Value Type", "Entity Type"])
        self.machine_features_table.verticalHeader().setVisible(False)
        self.machine_features_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.machine_features_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.machine_features_table.setMaximumHeight(160)
        f_header = self.machine_features_table.horizontalHeader()
        if f_header is not None:
            f_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        feat_layout.addWidget(self.machine_features_table)
        root.addWidget(feat_box)

        # Maintenance (safe) actions.
        maint_box = QGroupBox("Maintenance")
        maint_box.setObjectName("card")
        maint_grid = QGridLayout(maint_box)
        maint_grid.setHorizontalSpacing(UI_SPACING)
        maint_grid.setVerticalSpacing(6)
        maint = [
            ("Reset Errors", lambda: self._machine_command("Reset errors", lambda api: api.reset_errors(), refresh=True)),
            ("Clear Messages", lambda: self._machine_command("Clear messages", lambda api: api.clear_messages())),
            ("Camera Power On", lambda: self._machine_command("Camera power on", lambda api: api.power_on_camera(), refresh=True)),
            ("Camera Power Off", lambda: self._machine_command("Camera power off", lambda api: api.power_off_camera(), refresh=True)),
        ]
        for i, (label, handler) in enumerate(maint):
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            self._machine_buttons.append(btn)
            maint_grid.addWidget(btn, i // 2, i % 2)
        root.addWidget(maint_box)

        # Danger zone: destructive commands, each behind an explicit confirmation.
        danger_box = QGroupBox("Danger Zone")
        danger_box.setObjectName("card")
        danger_grid = QGridLayout(danger_box)
        danger_grid.setHorizontalSpacing(UI_SPACING)
        danger_grid.setVerticalSpacing(6)
        # Each entry: (label, confirm text, fn, needs_serial). The two irreversible, device-scoped
        # wipes require the caller to type this device's analysis-unit serial (guardrail against
        # wiping the wrong unit); their fn therefore takes (api, serial).
        danger = [
            ("Reboot", "Reboot the device now?\n\nIt will be unavailable until it comes back up.",
             lambda api: api.reboot(), False),
            ("Shutdown", "Shut the device down now?\n\nIt will stay off until powered on again physically.",
             lambda api: api.shutdown(), False),
            ("Clear Data", "Permanently delete ALL measurement data on the device?\n\nThis cannot be undone.",
             lambda api, serial: api.clear_data(serial), True),
            ("Factory Reset", "Reset the device to factory defaults?\n\nAll settings and data are lost. This cannot be undone.",
             lambda api, serial: api.factory_reset(serial), True),
        ]
        for i, (label, confirm, fn, needs_serial) in enumerate(danger):
            btn = QPushButton(label)
            btn.setObjectName("dangerButton")
            btn.clicked.connect(lambda _checked=False, lb=label, cf=confirm, f=fn, ns=needs_serial: self._machine_command(lb, f, confirm=cf, require_serial=ns))
            self._machine_buttons.append(btn)
            danger_grid.addWidget(btn, i // 2, i % 2)
        root.addWidget(danger_box)
        root.addStretch(1)

        outer_root.addWidget(self._wrap_scroll(inner), 1)
        return outer

    def _machine_kv_card(self, title: str, rows: list[tuple[str, str]]) -> QGroupBox:
        """A titled card of fixed key/value label rows; values are stored in ``self._mi``
        keyed by the row's key, so :meth:`_update_machine_info` can fill them in later."""
        box, form = self._section_card(title)
        for disp, key in rows:
            val = QLabel("—")
            val.setObjectName("metaValue")
            self._mi[key] = val
            form.addRow(disp, val)
        return box

    def _set_mi(self, key: str, value: object) -> None:
        label = self._mi.get(key)
        if label is not None:
            label.setText("—" if value is None or value == "" else str(value))

    @staticmethod
    def _format_bytes(num: int | None) -> str:
        """Human-readable byte size."""
        if num is None:
            return "—"
        size = float(num)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{num}"

    def _update_machine_info(self, infos: Infos) -> None:
        """Fill the info cards + readiness verdict from an :class:`Infos` payload."""
        s = infos.system
        self._set_mi("sys_status", s.status if s else None)
        self._set_mi("sys_mode", s.mode if s else None)
        self._set_mi("sys_action", s.action_type if s else None)
        self._set_mi("sys_bundle", s.bundle_version if s else None)
        self._set_mi("sys_sw", s.software_version if s else None)
        self._set_mi("sys_gui", s.gui_version if s else None)
        au = infos.analysisunit
        self._set_mi("au_hardware", au.hardware_version if au else None)
        self._set_mi("au_order", au.order_number if au else None)
        self._set_mi("au_serial", au.serial_number if au else None)
        self._set_mi("au_mfg", au.manufacturing_date if au else None)
        self._set_mi("au_fw", au.firmware_version if au else None)
        cam = infos.cameraunit
        self._set_mi("cam_type", cam.type if cam else None)
        self._set_mi("cam_serial", cam.serial_number if cam else None)
        self._set_mi("cam_hardware", cam.hardware_version if cam else None)
        self._set_mi("cam_fw", cam.firmware_version if cam else None)
        self._set_mi("cam_maxfps", cam.max_fps if cam else None)
        self._set_mi("cam_status", cam.status if cam else None)
        st = infos.storage
        self._set_mi("st_free", self._format_bytes(st.free) if st else None)
        self._set_mi("st_used", self._format_bytes(st.used) if st else None)
        self._set_mi("st_size", self._format_bytes(st.size) if st else None)

        # Readiness verdict, mirroring the machine example. Each key is a *requirement*; the ones
        # not satisfied are listed after "No —". The camera check uses the authoritative `status`
        # (the `power` field is optional and not emitted by all firmware), so a powered-on camera
        # is never mis-reported as off.
        checks = {
            "unit idle": bool(s and s.status == "idle"),
            "camera powered on": bool(cam and cam.status == "powered_on"),
            "storage > 10% free": bool(st and st.size and (st.free or 0) / st.size > 0.10),
        }
        unmet = [name for name, ok in checks.items() if not ok]
        if not unmet:
            self.machine_readiness.setText("Yes — all checks pass.")
        else:
            self.machine_readiness.setText("No — not met: " + ", ".join(unmet))

    def _update_features(self, features: object) -> None:
        feats = list(features or [])  # type: ignore[arg-type]
        table = self.machine_features_table
        table.setRowCount(len(feats))
        for r, f in enumerate(feats):
            cells = [f"#{f.id}", f.name or "", f.unit or "", f.value_type or "", f.entity_type or ""]
            for c, val in enumerate(cells):
                table.setItem(r, c, QTableWidgetItem(val))

    def _update_gpio(self, levels: GpioLevels) -> None:
        """Rebuild the GPIO panel: read-only GPI badges + a toggle per GPO output."""
        self._clear_layout(self.machine_gpio_layout)
        self._gpo_checkboxes = {}

        gpi = levels.gpi or {}
        gpo = levels.gpo or {}
        if not gpi and not gpo:
            placeholder = QLabel("No GPIO reported by the device.")
            placeholder.setObjectName("statusLine")
            self.machine_gpio_layout.addWidget(placeholder)
            return

        if gpi:
            gpi_header = QLabel("Inputs (GPI) — read-only")
            gpi_header.setObjectName("metaKey")
            self.machine_gpio_layout.addWidget(gpi_header)
            for name in sorted(gpi):
                row = QWidget()
                row.setObjectName("unitRow")
                h = QHBoxLayout(row)
                h.setContentsMargins(0, 0, 0, 0)
                name_label = QLabel(name)
                badge = QLabel("High" if gpi[name] else "Low")
                badge.setObjectName("badgeSuccess" if gpi[name] else "badgeSecondary")
                h.addWidget(name_label)
                h.addStretch(1)
                h.addWidget(badge)
                self.machine_gpio_layout.addWidget(row)

        if gpo:
            gpo_header = QLabel("Outputs (GPO) — toggle to set")
            gpo_header.setObjectName("metaKey")
            self.machine_gpio_layout.addWidget(gpo_header)
            for name in sorted(gpo):
                check = QCheckBox(name)
                check.blockSignals(True)
                check.setChecked(bool(gpo[name]))
                check.blockSignals(False)
                check.toggled.connect(lambda checked, n=name: self._on_gpo_toggled(n, checked))
                self._gpo_checkboxes[name] = check
                self.machine_gpio_layout.addWidget(check)

    def _on_gpo_toggled(self, name: str, checked: bool) -> None:
        """A GPO checkbox was toggled by the user → PATCH it, then re-read to confirm."""
        if self._busy():
            self._refresh_gpio()  # revert the checkbox to the device's actual state
            return
        self.machine_status.setText(f"Setting {name} {'high' if checked else 'low'}…")
        self._run_api(
            lambda api, n=name, v=checked: api.set_gpo(n, v),
            lambda _r, n=name, v=checked: self._on_gpo_set(n, v),
            lambda msg: self._on_gpo_error(msg),
        )

    def _on_gpo_set(self, name: str, value: bool) -> None:
        self.machine_status.setText(f"{name} set {'high' if value else 'low'}.")
        self._refresh_gpio()  # read back to confirm the device's actual level

    def _on_gpo_error(self, message: str) -> None:
        self.machine_status.setText(f"GPO error: {message[:80]}")
        self.status_bar.showMessage(f"GPO error: {message[:120]}", 6000)
        self._refresh_gpio()  # restore the checkboxes to the device's real state

    def _refresh_gpio(self) -> None:
        if not self._connected:
            return
        self._run_api(lambda api: api.get_gpio_levels(), self._update_gpio,
                      lambda msg: self.machine_status.setText(f"GPIO read failed: {msg[:80]}"))

    def _reset_machine(self) -> None:
        """Clear the machine tab (on connect/disconnect)."""
        self._machine_loaded = False
        for label in self._mi.values():
            label.setText("—")
        self.machine_readiness.setText("—")
        self._clear_layout(self.machine_gpio_layout)
        self._gpo_checkboxes = {}
        placeholder = QLabel("Refresh to read GPIO levels.")
        placeholder.setObjectName("statusLine")
        self.machine_gpio_layout.addWidget(placeholder)
        self.machine_features_table.setRowCount(0)
        self.machine_status.setText("")

    def _refresh_machine(self) -> None:
        """Re-read infos + GPIO off-thread and repopulate the machine tab."""
        if not self._connected:
            return
        self._machine_loaded = True
        self.machine_status.setText("Loading…")
        self._run_api(
            lambda api: (api.get_infos(), api.get_gpio_levels()),
            self._on_machine_loaded,
            lambda msg: self._on_machine_error("Refresh", msg),
        )

    def _on_machine_loaded(self, result: object) -> None:
        infos, gpio = result  # type: ignore[misc]
        self._update_machine_info(infos)
        self._update_gpio(gpio)
        self.machine_status.setText("Updated.")

    def _on_machine_error(self, label: str, message: str) -> None:
        self.machine_status.setText(f"{label} failed: {message[:80]}")
        self.status_bar.showMessage(f"{label} failed: {message[:120]}", 6000)

    def _machine_command(self, label: str, fn: Any, *, confirm: str | None = None, refresh: bool = False, require_serial: bool = False) -> None:
        """Run a machine command off-thread. ``confirm`` (if given) requires a Yes in a
        warning dialog first; ``require_serial`` additionally prompts for this device's
        analysis-unit serial number and passes it to ``fn`` as a second argument (the
        server rejects a mismatch with 422); ``refresh`` re-reads the info/GPIO afterwards."""
        if not self._connected or self._busy():
            return
        if confirm is not None:
            reply = QMessageBox.warning(
                self, label, confirm,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        dispatch = fn
        if require_serial:
            # Deliberately NOT pre-filled: the caller must state which device they mean, so a
            # wrong-device wipe is caught (locally-typed value is verified server-side → 422).
            serial, ok = QInputDialog.getText(
                self, label,
                "Type this device's analysis-unit serial number to confirm.\n"
                "(Shown under System / analysis unit, or via GET /infos.)",
            )
            serial = serial.strip()
            if not ok or not serial:
                return
            dispatch = lambda api, s=serial: fn(api, s)  # noqa: E731
        self.machine_status.setText(f"{label}…")
        self._run_api(
            dispatch,
            lambda _r, lb=label, rf=refresh: self._on_machine_command_done(lb, rf),
            lambda msg, lb=label: self._on_machine_error(lb, msg),
        )

    def _on_machine_command_done(self, label: str, refresh: bool) -> None:
        self.machine_status.setText(f"{label}: done.")
        self.status_bar.showMessage(f"{label}: done.", 4000)
        if refresh:
            self._refresh_machine()

    def _build_demo_notice(self) -> QWidget:
        """Slim banner making clear this is an example client for the API, not
        production software — so glitches are expected."""
        bar = QFrame()
        bar.setObjectName("demoNotice")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 6, 20, 6)
        label = QLabel(
            "Demo application — an example client for the droptical API. "
            "It is not production software, so bugs and rough edges are expected."
        )
        label.setObjectName("demoNoticeText")
        # Single line spanning the full width (no word-wrap → no wasted vertical space).
        lay.addWidget(label, 1)
        return bar

    def _setup_ui(self) -> None:
        """Sets up the main structure of the application's user interface."""
        # Flush branded header bar (droptical logo),
        # then a padded content area holding the device controls and the four tabs.
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        # Per-tab action status ("Executing…", "Done.") is routed to the footer status bar.
        self._footer_status = _FooterStatus(self)
        # The header holds the device host + Initialize/Change button; a slim demo notice
        # sits flush beneath it, then the padded content area with the tabs.
        self.main_layout.addWidget(self._build_app_header())
        self.main_layout.addWidget(self._build_demo_notice())

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(UI_SPACING)
        self.main_layout.addWidget(content)

        # Four flat, always-navigable top-level tabs (no "Control" parent). Their
        # inputs are gated by connection state via _set_inputs_enabled(), not by
        # disabling the whole tab bar.
        self.tabs = QTabWidget()
        content_layout.addWidget(self.tabs)

        self.stream_tab = QWidget()
        self.tabs.addTab(self.stream_tab, "Image Stream")
        self._create_stream_tab()
        self.value_stream_tab = self._create_value_stream_tab()
        self.tabs.addTab(self.value_stream_tab, "Value Stream")
        self.tabs.addTab(self._create_single_shot_tab(), "Single Shot")
        self.tabs.addTab(self._create_multi_shot_tab(), "Multi Shot")
        self.tabs.addTab(self._create_video_tab(), "Video")
        self.presets_tab = self._create_presets_tab()
        self.tabs.addTab(self.presets_tab, "Presets")
        self.machine_tab = self._create_machine_tab()
        self.tabs.addTab(self.machine_tab, "Machine")
        self.measurements_tab = self._create_measurements_tab()
        self.tabs.addTab(self.measurements_tab, "Measurements")
        self.history_tab = self._create_history_tab()
        self.tabs.addTab(self.history_tab, "History")
        self.jobs_tab = self._create_jobs_tab()
        self.tabs.addTab(self.jobs_tab, "Exports && Jobs")  # && renders a literal '&' (single & is a Qt mnemonic)

        self._wire_autosave()
        # Size every combo (and thus its popup) to its widest item — otherwise the
        # macOS popup renders narrow/clipped ("Trigger coun…"). QSS can't set this.
        combos = self.findChildren(QComboBox)
        for combo in combos:
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        # Spin boxes size-hint ~5px taller than combos/line-edits (room for both step
        # buttons), so pin every spin box to the combo height for a uniform input row.
        input_h = combos[0].sizeHint().height() if combos else 30
        for spin in self.findChildren(QAbstractSpinBox):
            spin.setFixedHeight(input_h)
        self._set_inputs_enabled(False)  # locked until a device is initialized

        self._setup_status_bar()

        self.device_button.clicked.connect(self._on_device_button)
        line_edit = self.ip_input.lineEdit()
        if line_edit is not None:
            line_edit.returnPressed.connect(self._on_device_button)  # Enter in the host field connects
        self.mode_combo.activated.connect(self._on_mode_changed)  # user-only signal (not setCurrentIndex)
        self.tabs.currentChanged.connect(self._on_tab_changed)  # clears the value-stream badge on view

    def _setup_status_bar(self) -> None:
        """Configures the status bar to display real-time information."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.ui_fps_label = QLabel("UI FPS: --")
        self.save_fps_label = QLabel("Save FPS: --")
        self.status_bar.addPermanentWidget(self.ui_fps_label)
        self.status_bar.addPermanentWidget(self.save_fps_label)
        # Only shown while the values are actually being updated: UI FPS during a live
        # stream, Save FPS only while frames are being saved. Hidden otherwise.
        self.ui_fps_label.setVisible(False)
        self.save_fps_label.setVisible(False)
        self.status_bar.showMessage("Ready.")

    def _create_stream_tab(self) -> None:
        """Builds the UI elements for the live stream tab."""
        layout = QVBoxLayout(self.stream_tab)
        self.video_display_label = QLabel("No Video Signal")
        self.video_display_label.setMinimumSize(640, 480)
        self.video_display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_display_label.setObjectName("imageArea")
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

        # Video on the left, a live per-frame results table on the right (same style as
        # the Value Stream tab, but showing only the current frame).
        self.stream_results_table = QTableWidget(0, 4)
        self.stream_results_table.setHorizontalHeaderLabels(["Source", "Feature", "Value", "Status"])
        self.stream_results_table.verticalHeader().setVisible(False)
        self.stream_results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stream_results_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        sr_header = self.stream_results_table.horizontalHeader()
        if sr_header is not None:
            sr_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        results_header = QLabel("Frame Results")
        results_header.setObjectName("sectionHeader")
        results_panel = QWidget()
        results_panel.setFixedWidth(300)
        results_panel_layout = QVBoxLayout(results_panel)
        results_panel_layout.setContentsMargins(0, 0, 0, 0)
        results_panel_layout.setSpacing(6)
        results_panel_layout.addWidget(results_header)
        results_panel_layout.addWidget(self.stream_results_table, 1)

        video_row = QHBoxLayout()
        video_row.setSpacing(UI_SPACING)
        video_row.addWidget(self.video_display_label, 1)
        video_row.addWidget(results_panel)
        layout.addLayout(video_row, 1)

        self.stream_info_label = QLabel("Not streaming")
        font = self.stream_info_label.font()
        font.setFamily("Monospace")
        self.stream_info_label.setFont(font)
        self.stream_info_label.setStyleSheet("QLabel { background-color: rgba(26,29,32,200); color: #DEE2E6; padding: 8px; border-radius: 6px; }")
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

    # ---- shared layout / output helpers ----------------------------------

    def _section_card(self, title: str) -> tuple[QGroupBox, QFormLayout]:
        """A titled settings card (same look as the Measurement panel) with a form layout
        inside. The title renders in the card's border like a legend."""
        box = QGroupBox(title)
        box.setObjectName("card")
        form = QFormLayout(box)
        return box, form

    def _input_panel(self, cards: list[QWidget]) -> QWidget:
        """Right-hand input panel: a vertical stack of titled section cards. The trigger
        button lives outside this panel so it can span the full tab width."""
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(4, 4, 4, 4)
        # UI_SPACING between cards, plus each card's own 10px title margin → clear
        # separation between sections while staying consistent with the rest of the GUI.
        v.setSpacing(UI_SPACING)
        for card in cards:
            v.addWidget(card)
        v.addStretch()
        return panel

    @staticmethod
    def _unit_row(field: QWidget, unit: str) -> QWidget:
        """Pair an input with its unit shown in a separate cell to the right (not as a
        suffix inside the field)."""
        row = QWidget()
        # Plain QWidgets inherit the global `QWidget { background:#212529 }` rule, which
        # would paint an opaque rectangle on the #2B3035 card. Keep the wrapper transparent.
        row.setObjectName("unitRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(field, 1)
        addon = QLabel(unit)
        addon.setObjectName("unitAddon")
        # Fixed width so every unit cell (V / Hz / µs) is identical → the fields line up.
        addon.setFixedWidth(24)
        addon.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(addon)
        return row

    @staticmethod
    def _wrap_scroll(inner: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return scroll

    def _build_meta_panel(self, prefix: str) -> QGroupBox:
        """A card of fixed labels for the measurement's static meta info.

        Laid out as a compact grid (two key/value pairs per row) rather than one
        tall column, so the panel doesn't eat vertical space in the output area.
        """
        box = QGroupBox("Measurement")
        box.setObjectName("card")
        for key in ("id", "status", "progress", "frames", "timestamp"):
            lbl = QLabel("—")
            if key == "status":
                lbl.setObjectName("badgeSecondary")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                lbl.setObjectName("metaValue")
            setattr(self, f"{prefix}_meta_{key}", lbl)

        def key_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName("metaKey")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return lbl

        grid = QGridLayout(box)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        # (row, col) pairs: label in col 0/2, value in col 1/3 → two pairs per row.
        cells = [
            ("ID:", "id", 0, 0), ("Status:", "status", 0, 2),
            ("Progress:", "progress", 1, 0), ("Frames:", "frames", 1, 2),
            ("Timestamp:", "timestamp", 2, 0),
        ]
        for text, key, row, col in cells:
            grid.addWidget(key_label(text), row, col)
            value = getattr(self, f"{prefix}_meta_{key}")
            # Align the status pill left so its background hugs the text instead of
            # stretching across the whole cell.
            grid.addWidget(value, row, col + 1, left if key == "status" else Qt.AlignmentFlag.AlignVCenter)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        return box

    def _apply_status_badge(self, label: QLabel, status: str | None) -> None:
        label.setText(str(status) if status else "—")
        label.setObjectName(_STATUS_BADGE.get(str(status), "badgeSecondary"))
        style = label.style()
        if style is not None:  # re-polish so the new objectName's QSS takes effect
            style.unpolish(label)
            style.polish(label)

    @staticmethod
    def _format_timestamp(ts: str | None) -> str:
        """Render an ISO timestamp as ``YYYY-MM-DD HH:MM:SS``; fall back to the raw value."""
        if not ts:
            return "—"
        try:
            return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return ts

    def _update_meta(self, prefix: str, m: Measurement) -> None:
        """Fill a tab's fixed measurement-meta labels."""
        getattr(self, f"{prefix}_meta_id").setText(f"#{m.id}")
        self._apply_status_badge(getattr(self, f"{prefix}_meta_status"), m.status)
        getattr(self, f"{prefix}_meta_progress").setText(f"{m.progress}%" if m.progress is not None else "—")
        getattr(self, f"{prefix}_meta_frames").setText(str(m.frames_count) if m.frames_count is not None else "—")
        getattr(self, f"{prefix}_meta_timestamp").setText(self._format_timestamp(m.created_at))

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while (child := layout.takeAt(0)) is not None:
            w = child.widget()
            if w is not None:
                w.deleteLater()

    @staticmethod
    def _format_results_list(results: list[FrameResult] | None) -> list[str]:
        """Render a list of typed frame results (feature name/unit, value, status)."""
        out: list[str] = []
        for r in results or []:
            name = (r.feature.name if r.feature and r.feature.name else None) or "value"
            unit = (r.feature.unit if r.feature and r.feature.unit else None) or ""
            line = f"{name}: {r.value}{(' ' + str(unit)) if unit else ''}"
            if r.status and r.status not in ("disabled", "ok", "nominal"):
                line += f"  [{r.status}]"
            out.append(line)
        return out

    def _format_frame_results(self, rois: list[FrameRoi] | None) -> str:
        """Compactly render a frame's per-ROI + per-drop results (typed FrameRoi tree from
        ``GET /frames/{id}`` / ``?include=rois``)."""
        if not rois:
            return "No results."
        lines: list[str] = []
        for roi in rois:
            lines += self._format_results_list(roi.results)
            for drop in roi.drops:
                drop_vals = self._format_results_list(drop.results)
                if drop_vals:
                    lines.append(f"Drop {drop.index if drop.index is not None else '?'}: " + ", ".join(drop_vals))
        return "\n".join(lines) if lines else "No results."

    def _make_frame_card(self, frame: MeasurementFrame, base_url: str, use_id: bool = False, title: str | None = None) -> QGroupBox:
        """A card showing a frame's image with its results underneath, styled like the
        Measurement card: the title is a group-box legend sitting on the top border.

        ``title`` overrides the card heading (single shot uses a plain "Frame", as there is
        only ever one). Otherwise ``use_id`` titles by the frame's (global) id rather than its
        per-measurement index — used by the History tab, where indices repeat across measurements."""
        if title is None:
            label = frame.id if use_id else (frame.index if frame.index is not None else frame.id)
            title = f"Frame {label}"
        card = QGroupBox(title)
        card.setObjectName("card")
        v = QVBoxLayout(card)
        img = QLabel("Fetching…")
        img.setObjectName("imageArea")
        img.setMinimumSize(240, 200)
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        v.addWidget(img)
        if frame.url:
            self.start_image_fetch(f"{base_url}/api/v2/frames/{frame.id}/image", img)
        else:
            img.setText("No stored image")
        # Only show a results line when results were actually loaded (rois populated). The
        # frame-list view (History tab) omits rois, so its cards stay image-only.
        if frame.rois is not None:
            results = QLabel(self._format_frame_results(frame.rois))
            results.setObjectName("resultText")
            results.setWordWrap(True)
            v.addWidget(results)
        return card

    def _set_inputs_enabled(self, enabled: bool) -> None:
        """Connection gate: enable/disable ALL inputs + trigger/stream buttons. The tabs
        stay navigable; only their controls follow the connection state."""
        for panel in (self.ss_input_panel, self.ms_input_panel, self.vid_input_panel):
            panel.setEnabled(enabled)
        # Trigger buttons sit outside the input panels (full-width), so they are gated here.
        for btn in (self.ss_trigger_button, self.ms_trigger_button, self.vid_trigger_button):
            btn.setEnabled(enabled)
        self.start_button.setEnabled(enabled)
        self.vs_button.setEnabled(enabled)  # value-stream listener toggle
        self.history_refresh_button.setEnabled(enabled)
        # Presets tab: refresh / include-deleted / create are gated by connection; the
        # row-action buttons additionally need a selection (handled by _update_preset_buttons).
        self.presets_refresh_button.setEnabled(enabled)
        self.presets_include_deleted.setEnabled(enabled)
        self.preset_new_name.setEnabled(enabled)
        self.preset_new_comment.setEnabled(enabled)
        self.preset_create_button.setEnabled(enabled)
        self._update_preset_buttons()
        # Machine tab: refresh + every command button.
        self.machine_refresh_button.setEnabled(enabled)
        for btn in self._machine_buttons:
            btn.setEnabled(enabled)
        # Measurements tab: refresh + filters; Delete/Load-more depend on selection/cursor
        # (handled by _update_measurement_buttons).
        self.measurements_refresh_button.setEnabled(enabled)
        self.meas_type_filter.setEnabled(enabled)
        self.meas_status_filter.setEnabled(enabled)
        self._update_measurement_buttons()
        # Exports & Jobs tab: the create/download form + refresh; the row-action buttons
        # additionally depend on the selected job's status (handled by _update_job_buttons).
        self.jobs_form_box.setEnabled(enabled)
        self.jobs_refresh_button.setEnabled(enabled)
        self.jobs_autorefresh.setEnabled(enabled)
        self._update_job_buttons()
        self._sync_jobs_polling()  # a disconnect must stop the poll timer
        save_groupbox = self.findChild(QGroupBox, "save_groupbox")
        if save_groupbox is not None:
            save_groupbox.setEnabled(enabled)
        if enabled:  # re-apply the external-trigger → frequency-disabled rule
            for p in ("ss", "ms", "vid"):
                self._sync_valve_frequency_enabled(p)

    def _create_single_shot_tab(self) -> QWidget:
        """Single-shot control panel (Trigger + Timing).

        Valve-only inputs (a0 / frequency / pwl) are intentionally omitted, matching
        a build with no valve configured.
        """
        widget = QWidget()
        root = QVBoxLayout(widget)
        root.setSpacing(UI_SPACING)

        # --- inputs (right): one titled card per section (Trigger / Timing / Valve) ---
        self.ss_trigger_mode = QComboBox()
        self.ss_trigger_mode.addItems(["Internal Trigger", "External Trigger"])
        # Exposure mode + its Flash Delay 2 / Exit Delay rows are gated on the velocity
        # feature. Explicit label handle so the row hides as a unit.
        self.ss_exposure_label = QLabel("Exposure:")
        self.ss_exposure_mode = QComboBox()
        self.ss_exposure_mode.addItems(["Single Exposure", "Double Exposure"])
        self.ss_exposure_mode.currentIndexChanged.connect(self._on_ss_exposure_changed)
        self.ss_flash_delay = self._make_us_spinbox(ActionSettings.FLASH_DELAY_MIN, ActionSettings.FLASH_DELAY_MAX)
        self.ss_flash_delay2_label = QLabel("Flash Delay 2:")
        self.ss_flash_delay2 = self._make_us_spinbox(ActionSettings.FLASH_DELAY2_MIN, ActionSettings.FLASH_DELAY2_MAX)
        self.ss_flash_delay2_row = self._unit_row(self.ss_flash_delay2, "µs")
        self.ss_exit_delay_label = QLabel("Exit Delay:")
        self.ss_exit_delay = self._make_us_spinbox(ActionSettings.EXIT_DELAY_MIN, ActionSettings.EXIT_DELAY_MAX)
        self.ss_exit_delay_row = self._unit_row(self.ss_exit_delay, "µs")

        trigger_box, trigger_form = self._section_card("Trigger")
        trigger_form.addRow("Trigger:", self.ss_trigger_mode)

        timing_box, timing_form = self._section_card("Timing")
        timing_form.addRow(self.ss_exposure_label, self.ss_exposure_mode)
        timing_form.addRow("Flash Delay:", self._unit_row(self.ss_flash_delay, "µs"))
        timing_form.addRow(self.ss_flash_delay2_label, self.ss_flash_delay2_row)
        timing_form.addRow(self.ss_exit_delay_label, self.ss_exit_delay_row)

        params_box, params_form = self._section_card("Parameters")
        self._add_parameters_section(params_form, "ss")

        # No trigger frequency for single shot — a single capture has no repetition rate.
        valve_box, valve_form = self._section_card("Valve Control")
        self._add_valve_section(valve_form, "ss", include_frequency=False)

        self._on_ss_exposure_changed()
        self.ss_trigger_button = QPushButton("Single Shot")
        self.ss_trigger_button.setObjectName("primaryButton")
        self.ss_trigger_button.clicked.connect(self.run_single_shot)
        self.ss_input_panel = self._input_panel([trigger_box, timing_box, params_box, valve_box])

        # --- outputs (left): meta + the captured frame (image + results). Status text
        # goes to the footer via self.ss_output (a _FooterStatus proxy). ---
        self.ss_output = self._footer_status
        self.ss_result_layout = QVBoxLayout()
        self.ss_result_layout.setSpacing(UI_SPACING)
        # No side margins: a single shot yields exactly one frame card, which should
        # span the same width as the Measurement card above it (vertical spacing comes
        # from the parent layout + the card's own top margin).
        self.ss_result_layout.setContentsMargins(0, 0, 0, 0)
        results_container = QWidget()
        results_container.setLayout(self.ss_result_layout)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)  # match the input panel so cards top-align
        left_layout.setSpacing(UI_SPACING)
        left_layout.addWidget(self._build_meta_panel("ss"))
        left_layout.addWidget(self._wrap_scroll(results_container), 1)

        split = QHBoxLayout()
        split.setSpacing(UI_SPACING)
        split.addWidget(left_panel, 3)
        split.addWidget(self._wrap_scroll(self.ss_input_panel), 2)
        root.addWidget(self.ss_trigger_button)  # full-width CTA directly under the tab bar
        root.addLayout(split, 1)
        return widget

    def _create_multi_shot_tab(self) -> QWidget:
        """Multi-shot control panel (Trigger + Timing + Capture)."""
        widget = QWidget()
        root = QVBoxLayout(widget)
        root.setSpacing(UI_SPACING)

        # --- inputs (right): one titled card per section (Trigger / Timing / Capture / Valve) ---
        self.ms_trigger_mode = QComboBox()
        self.ms_trigger_mode.addItems(["Internal Trigger", "External Trigger"])
        self.ms_exposure_label = QLabel("Exposure:")
        self.ms_exposure_mode = QComboBox()
        self.ms_exposure_mode.addItems(["Single Exposure", "Double Exposure"])
        self.ms_exposure_mode.currentIndexChanged.connect(self._on_ms_exposure_changed)
        self.ms_flash_delay = self._make_us_spinbox(ActionSettings.FLASH_DELAY_MIN, ActionSettings.FLASH_DELAY_MAX)
        self.ms_flash_delay2_label = QLabel("Flash Delay 2:")
        self.ms_flash_delay2 = self._make_us_spinbox(ActionSettings.FLASH_DELAY2_MIN, ActionSettings.FLASH_DELAY2_MAX)
        self.ms_flash_delay2_row = self._unit_row(self.ms_flash_delay2, "µs")
        self.ms_exit_delay_label = QLabel("Exit Delay:")
        self.ms_exit_delay = self._make_us_spinbox(ActionSettings.EXIT_DELAY_MIN, ActionSettings.EXIT_DELAY_MAX)
        self.ms_exit_delay_row = self._unit_row(self.ms_exit_delay, "µs")
        # Capture — one shared count value; the select only flips captureModeOn.
        self.ms_save_all_images = QComboBox()
        self.ms_save_all_images.addItems(["Warning & Limits", "Save all images"])
        self.ms_count_mode = QComboBox()
        self.ms_count_mode.addItems(["Trigger count", "Image count"])
        self.ms_trigger_count = self._make_count_spinbox(ActionSettings.TRIGGER_COUNT_MIN, ActionSettings.TRIGGER_COUNT_MAX)
        count_layout = QHBoxLayout()
        count_layout.addWidget(self.ms_count_mode)
        count_layout.addWidget(self.ms_trigger_count)

        trigger_box, trigger_form = self._section_card("Trigger")
        trigger_form.addRow("Trigger:", self.ms_trigger_mode)

        timing_box, timing_form = self._section_card("Timing")
        timing_form.addRow(self.ms_exposure_label, self.ms_exposure_mode)
        timing_form.addRow("Flash Delay:", self._unit_row(self.ms_flash_delay, "µs"))
        timing_form.addRow(self.ms_flash_delay2_label, self.ms_flash_delay2_row)
        timing_form.addRow(self.ms_exit_delay_label, self.ms_exit_delay_row)

        capture_box, capture_form = self._section_card("Capture")
        capture_form.addRow("Images:", self.ms_save_all_images)
        capture_form.addRow("Count:", count_layout)

        params_box, params_form = self._section_card("Parameters")
        self._add_parameters_section(params_form, "ms")

        valve_box, valve_form = self._section_card("Valve Control")
        self._add_valve_section(valve_form, "ms")

        self._on_ms_exposure_changed()
        self.ms_trigger_button = QPushButton("Multi Shot")
        self.ms_trigger_button.setObjectName("primaryButton")
        self.ms_trigger_button.clicked.connect(self.run_multi_shot)
        self.ms_input_panel = self._input_panel([trigger_box, timing_box, capture_box, params_box, valve_box])

        # --- outputs (left): meta + one card per captured frame. Status text goes to
        # the footer via self.ms_output (a _FooterStatus proxy). ---
        self.ms_output = self._footer_status
        self.ms_image_layout = QVBoxLayout()
        self.ms_image_layout.setSpacing(UI_SPACING)
        # Flush-left with the Measurement card above; keep a right margin so the stacked
        # frame cards don't collide with the scrollbar when it appears.
        self.ms_image_layout.setContentsMargins(0, 0, 9, 0)
        results_container = QWidget()
        results_container.setLayout(self.ms_image_layout)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)  # match the input panel so cards top-align
        left_layout.setSpacing(UI_SPACING)
        left_layout.addWidget(self._build_meta_panel("ms"))
        left_layout.addWidget(self._wrap_scroll(results_container), 1)

        split = QHBoxLayout()
        split.setSpacing(UI_SPACING)
        split.addWidget(left_panel, 3)
        split.addWidget(self._wrap_scroll(self.ms_input_panel), 2)
        root.addWidget(self.ms_trigger_button)  # full-width CTA directly under the tab bar
        root.addLayout(split, 1)
        return widget

    def _create_video_tab(self) -> QWidget:
        """Video control panel (Trigger + Timings + Capture).

        The right panel now plays the produced video attachment (QMediaPlayer) and
        shows the stitched-image attachment.
        """
        widget = QWidget()
        root = QVBoxLayout(widget)
        root.setSpacing(UI_SPACING)

        # --- inputs (right): one titled card per section (Trigger / Timings / Capture / Valve) ---
        self.vid_trigger_mode = QComboBox()
        self.vid_trigger_mode.addItems(["Internal Trigger", "External Trigger"])
        trigger_box, trigger_form = self._section_card("Trigger")
        trigger_form.addRow("Trigger:", self.vid_trigger_mode)

        # Timings — Increment (index 0) / Constant (index 1).
        timings_box, timings_form = self._section_card("Timings")
        self.vid_mode_tabs = QTabWidget()
        self.vid_mode_tabs.setObjectName("modeTabs")  # nested tabs → transparent pane (see QSS)

        self.increment_mode_widget = QWidget()
        self.increment_mode_widget.setObjectName("modeTabPage")
        increment_layout = QFormLayout(self.increment_mode_widget)
        increment_layout.setContentsMargins(12, 12, 12, 12)
        self.vid_inc_start_time = self._make_us_spinbox(ActionSettings.START_TIME_MIN, ActionSettings.START_TIME_MAX)
        self.vid_inc_end_time = self._make_us_spinbox(ActionSettings.END_TIME_MIN, ActionSettings.END_TIME_MAX)
        self.vid_inc_time_increment = self._make_us_spinbox(ActionSettings.TIME_INCREMENT_MIN, ActionSettings.TIME_INCREMENT_MAX)
        self.vid_inc_image_count = QLineEdit("0")
        self.vid_inc_image_count.setReadOnly(True)
        increment_layout.addRow("Start Time:", self._unit_row(self.vid_inc_start_time, "µs"))
        increment_layout.addRow("End Time:", self._unit_row(self.vid_inc_end_time, "µs"))
        increment_layout.addRow("Time Increment:", self._unit_row(self.vid_inc_time_increment, "µs"))
        increment_layout.addRow("Image Count (calc.):", self.vid_inc_image_count)
        self.vid_mode_tabs.addTab(self.increment_mode_widget, "Increment")

        self.constant_mode_widget = QWidget()
        self.constant_mode_widget.setObjectName("modeTabPage")
        constant_layout = QFormLayout(self.constant_mode_widget)
        constant_layout.setContentsMargins(12, 12, 12, 12)
        self.vid_const_exposure_label = QLabel("Exposure:")
        self.vid_const_exposure_mode = QComboBox()
        self.vid_const_exposure_mode.addItems(["Single Exposure", "Double Exposure"])
        self.vid_const_exposure_mode.currentIndexChanged.connect(self._on_vid_exposure_changed)
        self.vid_const_flash_delay = self._make_us_spinbox(ActionSettings.FLASH_DELAY_MIN, ActionSettings.FLASH_DELAY_MAX)
        self.vid_const_flash_delay2_label = QLabel("Flash Delay 2:")
        self.vid_const_flash_delay2 = self._make_us_spinbox(ActionSettings.FLASH_DELAY2_MIN, ActionSettings.FLASH_DELAY2_MAX)
        self.vid_const_flash_delay2_row = self._unit_row(self.vid_const_flash_delay2, "µs")
        self.vid_const_exit_delay_label = QLabel("Exit Delay:")
        self.vid_const_exit_delay = self._make_us_spinbox(ActionSettings.EXIT_DELAY_MIN, ActionSettings.EXIT_DELAY_MAX)
        self.vid_const_exit_delay_row = self._unit_row(self.vid_const_exit_delay, "µs")
        self.vid_const_image_count = self._make_count_spinbox(ActionSettings.IMAGE_COUNT_MIN, ActionSettings.IMAGE_COUNT_MAX)
        constant_layout.addRow(self.vid_const_exposure_label, self.vid_const_exposure_mode)
        constant_layout.addRow("Flash Delay:", self._unit_row(self.vid_const_flash_delay, "µs"))
        constant_layout.addRow(self.vid_const_flash_delay2_label, self.vid_const_flash_delay2_row)
        constant_layout.addRow(self.vid_const_exit_delay_label, self.vid_const_exit_delay_row)
        constant_layout.addRow("Image Count:", self.vid_const_image_count)
        self.vid_mode_tabs.addTab(self.constant_mode_widget, "Constant")

        timings_form.addRow(self.vid_mode_tabs)

        self.vid_inc_start_time.valueChanged.connect(self._update_video_image_count)
        self.vid_inc_end_time.valueChanged.connect(self._update_video_image_count)
        self.vid_inc_time_increment.valueChanged.connect(self._update_video_image_count)

        # Capture — save mode, stitch count, video fps (shown in both modes).
        self.vid_save_all_images = QComboBox()
        self.vid_save_all_images.addItems(["Warning & Limits", "Save all images"])
        self.vid_stitch_count = self._make_count_spinbox(ActionSettings.STITCH_COUNT_MIN, ActionSettings.STITCH_COUNT_MAX)
        self.vid_export_fps = QSpinBox()
        self.vid_export_fps.setMinimum(ActionSettings.FPS_MIN)
        self.vid_export_fps.setMaximum(ActionSettings.FPS_MAX)
        self.vid_export_fps.setValue(ActionSettings.FPS_MIN)
        capture_box, capture_form = self._section_card("Capture")
        capture_form.addRow("Images:", self.vid_save_all_images)
        capture_form.addRow("Stitch Count:", self.vid_stitch_count)
        capture_form.addRow("Video FPS:", self._unit_row(self.vid_export_fps, "Hz"))

        params_box, params_form = self._section_card("Parameters")
        self._add_parameters_section(params_form, "vid")

        valve_box, valve_form = self._section_card("Valve Control")
        self._add_valve_section(valve_form, "vid")

        self._on_vid_exposure_changed()
        self.vid_trigger_button = QPushButton("Create Video")
        self.vid_trigger_button.setObjectName("primaryButton")
        self.vid_trigger_button.clicked.connect(self.run_video)
        self.vid_input_panel = self._input_panel([trigger_box, timings_box, capture_box, params_box, valve_box])

        # --- outputs (left): meta + produced video + stitched image. Status text goes
        # to the footer via self.vid_output (a _FooterStatus proxy). ---
        self.vid_output = self._footer_status
        self.video_player = QMediaPlayer()
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumSize(400, 240)
        self.video_player.setVideoOutput(self.video_widget)
        self.video_player.setLoops(QMediaPlayer.Loops.Infinite)

        video_controls = QHBoxLayout()
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

        self.vid_stitched_label = QLabel("Stitched image will be displayed here")
        self.vid_stitched_label.setObjectName("imageArea")
        self.vid_stitched_label.setMinimumSize(400, 180)
        self.vid_stitched_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)  # match the input panel so cards top-align
        left_layout.setSpacing(UI_SPACING)
        left_layout.addWidget(self._build_meta_panel("vid"))
        video_header = QLabel("Video")
        video_header.setObjectName("sectionHeader")
        left_layout.addWidget(video_header)
        left_layout.addWidget(self.video_widget, 1)
        left_layout.addLayout(video_controls)
        stitched_header = QLabel("Stitched image")
        stitched_header.setObjectName("sectionHeader")
        left_layout.addWidget(stitched_header)
        left_layout.addWidget(self.vid_stitched_label, 1)

        split = QHBoxLayout()
        split.setSpacing(UI_SPACING)
        split.addWidget(left_panel, 3)
        split.addWidget(self._wrap_scroll(self.vid_input_panel), 2)
        root.addWidget(self.vid_trigger_button)  # full-width CTA directly under the tab bar
        root.addLayout(split, 1)
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

    @staticmethod
    def _make_us_spinbox(minimum: int, maximum: int) -> QSpinBox:
        """A microsecond QSpinBox (step 1), seeded at its minimum. The 'µs' unit is
        rendered in a separate cell via _unit_row(), not as an in-field suffix."""
        box = QSpinBox()
        box.setMinimum(minimum)
        box.setMaximum(maximum)
        box.setSingleStep(1)
        box.setValue(minimum)
        return box

    @staticmethod
    def _make_count_spinbox(minimum: int, maximum: int) -> QSpinBox:
        """A plain integer QSpinBox (step 1), seeded at its minimum."""
        box = QSpinBox()
        box.setMinimum(minimum)
        box.setMaximum(maximum)
        box.setSingleStep(1)
        box.setValue(minimum)
        return box

    # Exposure-mode handlers: the exposure toggle and its Flash Delay 2 / Exit Delay rows
    # are shown only when the velocity feature (id 7) is enabled. With the feature off,
    # only Flash Delay is shown
    # and the exposure stays Single Exposure (doubleSnap off). When on, Single Exposure
    # shows Exit Delay and Double Exposure shows Flash Delay 2 (mutually exclusive).
    def _apply_exposure_visibility(self, combo: QComboBox, combo_label: QLabel,
                                   fd2_label: QLabel, fd2_row: QWidget,
                                   exit_label: QLabel, exit_row: QWidget) -> None:
        velocity = self._velocity_enabled
        combo.setVisible(velocity)
        combo_label.setVisible(velocity)
        if not velocity and combo.currentIndex() != 0:
            blocked = combo.blockSignals(True)
            combo.setCurrentIndex(0)  # force Single Exposure so doubleSnap stays false
            combo.blockSignals(blocked)
        is_double = velocity and combo.currentIndex() == 1
        fd2_label.setVisible(is_double)
        fd2_row.setVisible(is_double)
        exit_label.setVisible(velocity and not is_double)
        exit_row.setVisible(velocity and not is_double)

    def _on_ss_exposure_changed(self) -> None:
        self._apply_exposure_visibility(
            self.ss_exposure_mode, self.ss_exposure_label,
            self.ss_flash_delay2_label, self.ss_flash_delay2_row,
            self.ss_exit_delay_label, self.ss_exit_delay_row)

    def _on_ms_exposure_changed(self) -> None:
        self._apply_exposure_visibility(
            self.ms_exposure_mode, self.ms_exposure_label,
            self.ms_flash_delay2_label, self.ms_flash_delay2_row,
            self.ms_exit_delay_label, self.ms_exit_delay_row)

    def _on_vid_exposure_changed(self) -> None:
        self._apply_exposure_visibility(
            self.vid_const_exposure_mode, self.vid_const_exposure_label,
            self.vid_const_flash_delay2_label, self.vid_const_flash_delay2_row,
            self.vid_const_exit_delay_label, self.vid_const_exit_delay_row)

    def _add_valve_section(self, form_layout: QFormLayout, prefix: str, *, include_frequency: bool = True) -> None:
        """Adds the valve-control rows (a0, trigger frequency, PWL string) into the given
        form. The caller supplies the titled "Valve Control" card, so no header is added
        here. Widgets are stored as ``self.{prefix}_a0`` etc.

        ``include_frequency=False`` omits the trigger frequency — it is meaningless
        for a single shot (there is no repetition rate). Which
        sub-field is relevant depends on the configured valve type (a0 for a generic
        valve, PWL for clickjetpro, …); this example simply exposes them so any
        valve can be driven.
        """
        a0 = QDoubleSpinBox()
        a0.setMinimum(ActionSettings.ANALOG_VOLTAGE_MIN)
        a0.setMaximum(ActionSettings.ANALOG_VOLTAGE_MAX)
        a0.setSingleStep(0.01)
        a0.setDecimals(2)

        pwl = QLineEdit()
        pwl.setPlaceholderText("PWL=0-100;0+0,10+0")
        pwl.setToolTip(
            "Piecewise-linear valve waveform. Format: PWL=min-max;ticks+voltage,…\n"
            "The min-max voltage-range prefix (0–100 V) is required; 2–16 points,\n"
            "first point at t=0, start voltage == end voltage."
        )

        setattr(self, f"{prefix}_a0", a0)
        setattr(self, f"{prefix}_pwl", pwl)

        form_layout.addRow("Analog Voltage a0:", self._unit_row(a0, "V"))

        if include_frequency:
            frequency = QDoubleSpinBox()
            frequency.setMinimum(ActionSettings.FREQUENCY_MIN)
            frequency.setMaximum(ActionSettings.FREQUENCY_MAX)
            frequency.setSingleStep(0.1)
            frequency.setValue(ActionSettings.FREQUENCY_MIN)
            setattr(self, f"{prefix}_frequency", frequency)
            form_layout.addRow("Trigger Frequency:", self._unit_row(frequency, "Hz"))

            # The frequency is driven by the external trigger when one is used, so it
            # is disabled while External Trigger is selected.
            trigger_mode = getattr(self, f"{prefix}_trigger_mode")
            trigger_mode.currentIndexChanged.connect(lambda _idx, p=prefix: self._sync_valve_frequency_enabled(p))
            self._sync_valve_frequency_enabled(prefix)

        form_layout.addRow("PWL String:", pwl)

    def _sync_valve_frequency_enabled(self, prefix: str) -> None:
        """Disable the trigger-frequency field while External Trigger is active
        (no-op for tabs without a frequency field, e.g. single shot)."""
        frequency = getattr(self, f"{prefix}_frequency", None)
        if frequency is None:
            return
        is_external = getattr(self, f"{prefix}_trigger_mode").currentIndex() == 1
        frequency.setEnabled(not is_external)
        frequency.setToolTip("Controlled by the external trigger" if is_external else "")

    def _validate_pwl(self, text: str) -> str | None:
        """Validate a PWL string against the same contract the API enforces (ValidPwl).

        Returns an error message, or ``None`` if the string is valid (or empty).
        Format: ``PWL=min-max;ticks+voltage,ticks+voltage,…`` with 2–16 points; the
        ``min-max`` voltage-range prefix (0–100 V) is required.
        """
        raw = text.strip()
        if not raw:
            return None  # empty ⇒ "not set"; the caller omits the field
        if len(raw) > ActionSettings.PWL_MAX_LENGTH:
            return f"PWL string is too long ({len(raw)} > {ActionSettings.PWL_MAX_LENGTH} characters)."
        if not raw.startswith("PWL="):
            return "PWL string must start with 'PWL='."
        body = raw[len("PWL="):]

        if ";" not in body:
            return "PWL string must include a 'min-max;' voltage-range prefix."
        prefix, _, points_str = body.partition(";")
        dash = prefix.find("-", 1)
        if dash <= 0:
            return "The voltage-range prefix must be 'min-max' (e.g. '0-100')."
        try:
            v_min, v_max = float(prefix[:dash]), float(prefix[dash + 1:])
        except ValueError:
            return "The voltage-range prefix must be 'min-max' with numeric bounds."
        if v_min < 0.0 or v_max > 100.0 or v_min > v_max:
            return "The voltage range must satisfy 0 <= min <= max <= 100."

        points: list[tuple[int, float]] = []
        for pair in points_str.split(","):
            parts = pair.split("+")
            if len(parts) != 2:
                return f"Invalid point '{pair.strip()}' — expected 'ticks+voltage'."
            try:
                points.append((int(parts[0]), float(parts[1])))
            except ValueError:
                return f"Invalid point '{pair.strip()}' — ticks must be an integer and voltage a number."

        if len(points) < 2 or len(points) > 16:
            return f"PWL must contain between 2 and 16 points (found {len(points)})."

        points.sort(key=lambda p: p[0])
        if any(ticks < 0 for ticks, _ in points):
            return "Ticks cannot be negative."
        if points[0][0] != 0:
            return "The first point must start at time 0 (t=0)."
        if points[0][1] != points[-1][1]:
            return f"Start and end voltage must be equal (start {points[0][1]} V, end {points[-1][1]} V)."
        for _ticks, volt in points:
            if volt < v_min or volt > v_max:
                return f"Voltage must be between {v_min} V and {v_max} V (found {volt} V)."

        counts: dict[int, int] = {}
        for ticks, _ in points:
            counts[ticks] = counts.get(ticks, 0) + 1
        for tick, count in counts.items():
            if count > 2:
                return f"Time {tick} appears {count} times; a maximum of 2 points per timestamp is allowed."

        return None

    def _add_parameters_section(self, form_layout: QFormLayout, prefix: str) -> None:
        """Up to three optional key/value rows, emitted as parameter1/2/3 ("key: value")
        into action.parameters. Postfix, key suggestions and row persistence are
        intentionally omitted here."""
        for i in range(1, 4):
            key = QLineEdit()
            key.setPlaceholderText("Key")
            value = QLineEdit()
            value.setPlaceholderText("Value")
            setattr(self, f"{prefix}_param{i}_key", key)
            setattr(self, f"{prefix}_param{i}_value", value)
            row = QHBoxLayout()
            row.addWidget(key, 1)
            row.addWidget(value, 1)
            cell = QWidget()
            cell.setLayout(row)
            form_layout.addRow(f"Parameter {i}:", cell)

    def _tab_parameters(self, prefix: str) -> dict[str, str]:
        """Assemble parameter1/2/3 from a tab's key/value rows. A row missing either the
        key or the value yields an empty string."""
        params: dict[str, str] = {}
        for i in range(1, 4):
            key = getattr(self, f"{prefix}_param{i}_key").text().strip()
            value = getattr(self, f"{prefix}_param{i}_value").text().strip()
            params[f"parameter{i}"] = f"{key}: {value}" if key and value else ""
        return params

    def _tab_action_dict(self, prefix: str) -> dict[str, Any]:
        """Build the ActionSettings fields from a tab's widgets — shared by the trigger
        builders and the on-blur autosave. ``pwl`` is handled separately (:meth:`_tab_pwl`)."""
        action: dict[str, Any] = {"useExternalTrigger": getattr(self, f"{prefix}_trigger_mode").currentIndex() == 1}

        if prefix == "vid":
            is_constant = self.vid_mode_tabs.currentIndex() == 1  # 0=Increment, 1=Constant
            action["useConstantMode"] = is_constant
            action["saveAllImages"] = self.vid_save_all_images.currentIndex() == 1
            action["stitchCount"] = self.vid_stitch_count.value()
            action["fps"] = self.vid_export_fps.value()
            if is_constant:
                is_double = self.vid_const_exposure_mode.currentIndex() == 1
                action["doubleSnap"] = is_double
                action["flashDelay"] = self.vid_const_flash_delay.value()
                action["imageCount"] = self.vid_const_image_count.value()
                action["flashDelay2" if is_double else "exitDelay"] = (
                    self.vid_const_flash_delay2 if is_double else self.vid_const_exit_delay
                ).value()
            else:
                action["startTime"] = self.vid_inc_start_time.value()
                action["endTime"] = self.vid_inc_end_time.value()
                action["timeIncrement"] = self.vid_inc_time_increment.value()
        else:
            is_double = getattr(self, f"{prefix}_exposure_mode").currentIndex() == 1
            action["doubleSnap"] = is_double
            action["flashDelay"] = getattr(self, f"{prefix}_flash_delay").value()
            if is_double:
                action["flashDelay2"] = getattr(self, f"{prefix}_flash_delay2").value()
            else:
                action["exitDelay"] = getattr(self, f"{prefix}_exit_delay").value()
            if prefix == "ms":
                action["saveAllImages"] = self.ms_save_all_images.currentIndex() == 1
                action["captureModeOn"] = self.ms_count_mode.currentText() == "Image count"
                action["triggerCount"] = self.ms_trigger_count.value()

        # Valve (shared): a0 always, frequency only where the field exists (not single-shot).
        action["a0"] = getattr(self, f"{prefix}_a0").value()
        frequency = getattr(self, f"{prefix}_frequency", None)
        if frequency is not None:
            action["frequency"] = frequency.value()
        action["parameters"] = self._tab_parameters(prefix)
        return action

    def _tab_pwl(self, prefix: str) -> tuple[str | None, str | None]:
        """Return ``(pwl, error)`` for a tab. Empty field → ``(None, None)``; invalid →
        ``(None, message)``; valid → ``(pwl, None)``."""
        text = getattr(self, f"{prefix}_pwl").text().strip()
        if not text:
            return None, None
        error = self._validate_pwl(text)
        return (None, error) if error else (text, None)

    # --- on-blur field handling: mirror shared fields across tabs + autosave -----------
    def _wire_autosave(self) -> None:
        """Wire control inputs so that, on blur, shared fields mirror to the other tabs
        and the active tab autosaves. Both use the same 'value finalized' signals
        (user-only), so programmatic population and cross-tab mirroring never self-trigger."""
        # Widgets that represent the SAME device (action) setting on more than one tab.
        # v2 has a single action-settings block, so these must stay in sync.
        sync_groups: list[tuple[str, list[str]]] = [
            ("index", ["ss_trigger_mode", "ms_trigger_mode", "vid_trigger_mode"]),           # useExternalTrigger
            ("index", ["ss_exposure_mode", "ms_exposure_mode", "vid_const_exposure_mode"]),  # doubleSnap
            ("value", ["ss_flash_delay", "ms_flash_delay", "vid_const_flash_delay"]),
            ("value", ["ss_flash_delay2", "ms_flash_delay2", "vid_const_flash_delay2"]),
            ("value", ["ss_exit_delay", "ms_exit_delay", "vid_const_exit_delay"]),
            ("value", ["ss_a0", "ms_a0", "vid_a0"]),
            ("value", ["ms_frequency", "vid_frequency"]),
            ("index", ["ms_save_all_images", "vid_save_all_images"]),                         # saveAllImages
            ("text", ["ss_pwl", "ms_pwl", "vid_pwl"]),
            # parameters (parameter1/2/3) belong to the single shared action block too
            ("text", ["ss_param1_key", "ms_param1_key", "vid_param1_key"]),
            ("text", ["ss_param1_value", "ms_param1_value", "vid_param1_value"]),
            ("text", ["ss_param2_key", "ms_param2_key", "vid_param2_key"]),
            ("text", ["ss_param2_value", "ms_param2_value", "vid_param2_value"]),
            ("text", ["ss_param3_key", "ms_param3_key", "vid_param3_key"]),
            ("text", ["ss_param3_value", "ms_param3_value", "vid_param3_value"]),
        ]
        self._sync_map = {}
        for kind, attrs in sync_groups:
            for attr in attrs:
                widget = getattr(self, attr, None)
                if widget is not None:
                    self._sync_map[widget] = (kind, attrs)

        tab_widgets: dict[str, list[QWidget]] = {
            "ss": [self.ss_trigger_mode, self.ss_exposure_mode, self.ss_flash_delay,
                   self.ss_flash_delay2, self.ss_exit_delay, self.ss_a0, self.ss_pwl],
            "ms": [self.ms_trigger_mode, self.ms_exposure_mode, self.ms_flash_delay,
                   self.ms_flash_delay2, self.ms_exit_delay, self.ms_save_all_images,
                   self.ms_count_mode, self.ms_trigger_count, self.ms_a0, self.ms_frequency, self.ms_pwl],
            "vid": [self.vid_trigger_mode, self.vid_mode_tabs, self.vid_const_exposure_mode,
                    self.vid_const_flash_delay, self.vid_const_flash_delay2, self.vid_const_exit_delay,
                    self.vid_const_image_count, self.vid_inc_start_time, self.vid_inc_end_time,
                    self.vid_inc_time_increment, self.vid_save_all_images, self.vid_stitch_count,
                    self.vid_export_fps, self.vid_a0, self.vid_frequency, self.vid_pwl],
        }
        # Parameters (parameter1/2/3) participate in mirroring + autosave like the rest
        # of the shared action block.
        for tab_prefix, widget_list in tab_widgets.items():
            widget_list.extend(getattr(self, f"{tab_prefix}_param{i}_{fld}")
                               for i in (1, 2, 3) for fld in ("key", "value"))

        for prefix, widgets in tab_widgets.items():
            for widget in widgets:
                self._connect_field_signal(widget, prefix)

    def _connect_field_signal(self, widget: QWidget, prefix: str) -> None:
        """Wire a widget's 'value finalized' signal (on-blur): editingFinished for
        spin/line edits, activated for combos, currentChanged for the mode tabs. These
        fire on user interaction only, so populating / mirroring never self-trigger."""
        def _fire(*_: object, w: QWidget = widget, p: str = prefix) -> None:
            self._on_field_finalized(w, p)

        if isinstance(widget, (QSpinBox, QDoubleSpinBox, QLineEdit)):
            widget.editingFinished.connect(_fire)
        elif isinstance(widget, QComboBox):
            widget.activated.connect(_fire)
        elif isinstance(widget, QTabWidget):
            widget.currentChanged.connect(_fire)

    def _on_field_finalized(self, widget: QWidget, prefix: str) -> None:
        """A control finished editing: mirror it to the other pages, then autosave."""
        self._mirror_field(widget)
        self._schedule_autosave(prefix)

    def _mirror_field(self, widget: QWidget) -> None:
        """Copy a shared field's value to the equivalent widgets on the other tabs so the
        pages stay in sync. Guarded by ``_syncing`` and driven by user-only signals, so it
        cannot feed back on itself (setValue/setCurrentIndex/setText don't re-fire them)."""
        entry = self._sync_map.get(widget)
        if entry is None or self._syncing:
            return
        kind, attrs = entry
        self._syncing = True
        try:
            for attr in attrs:
                sibling = getattr(self, attr, None)
                if sibling is None or sibling is widget:
                    continue
                if kind == "index":
                    sibling.setCurrentIndex(widget.currentIndex())
                elif kind == "value":
                    sibling.setValue(widget.value())
                elif kind == "text":
                    sibling.setText(widget.text())
        finally:
            self._syncing = False

    def _schedule_autosave(self, prefix: str) -> None:
        """Queue an autosave for a tab — skipped while populating, disconnected, or busy."""
        if self._suppress_autosave or not self._connected:
            return
        if self.worker_thread is not None and self.worker_thread.isRunning():
            return  # a measurement / stream is running — don't PATCH mid-action
        self._autosave_prefix = prefix
        self._autosave_timer.start()

    def _perform_autosave(self) -> None:
        """Debounce fired: PATCH the active tab's settings off-thread."""
        prefix = self._autosave_prefix
        if prefix is None or not self._connected:
            return
        # Re-check the busy guard: the 200 ms debounce can span an edit-then-trigger
        # sequence, and we must not PATCH concurrently with a running measurement/stream.
        if self.worker_thread is not None and self.worker_thread.isRunning():
            return
        pwl, pwl_error = self._tab_pwl(prefix)
        if pwl_error:
            self.status_bar.showMessage(f"Not saved — invalid PWL: {pwl_error}", 6000)
            return
        action = self._tab_action_dict(prefix)
        if pwl:
            action["pwl"] = pwl
        try:
            settings = AllSettings(action=ActionSettings(**action))
        except ValidationError as e:
            self.status_bar.showMessage(f"Not saved — invalid settings: {e}", 6000)
            return
        host, port = self._parse_host_port(self.ip_input.currentText())
        task = _SettingsSaveTask(host, port, settings)
        task.signals.done.connect(lambda: self.status_bar.showMessage("Settings saved.", 2000))
        task.signals.error.connect(lambda msg: self.status_bar.showMessage(f"Auto-save failed: {msg[:120]}", 6000))
        QThreadPool.globalInstance().start(task)

    def _populate_valve(self, prefix: str, a: ActionSettings) -> None:
        """Fill a tab's valve inputs (a0 / frequency / PWL) from the action settings."""
        getattr(self, f"{prefix}_a0").setValue(a.a0 or ActionSettings.ANALOG_VOLTAGE_MIN)
        frequency = getattr(self, f"{prefix}_frequency", None)
        if frequency is not None:
            frequency.setValue(a.frequency or ActionSettings.FREQUENCY_MIN)
        getattr(self, f"{prefix}_pwl").setText(a.pwl or "")
        self._sync_valve_frequency_enabled(prefix)

    @staticmethod
    def _parse_host_port(text: str, default_port: int = 80) -> tuple[str, int]:
        """Splits a ``host[:port]`` string into (host, port).

        Falls back to *default_port* when no numeric port is present. Bare IPv6
        literals (which themselves contain colons) are returned unsplit — wrap
        them in brackets if you need to attach a port.
        """
        text = text.strip()
        host, sep, port_str = text.rpartition(":")
        if sep and port_str.isdigit() and ":" not in host:
            return host, int(port_str)
        return text, default_port

    def _execute_worker_action(self, action_name: str, worker_starter_func: str, settings: AllSettings | None = None, sync: bool = False) -> None:
        """Manages the creation, configuration, and execution of a worker thread."""
        host, port = self._parse_host_port(self.ip_input.currentText())
        if not host:
            self.show_critical_error("Input Error", "Please provide a valid IP address or hostname.")
            return

        if (self.worker_thread and self.worker_thread.isRunning()) or (self._shot_thread and self._shot_thread.isRunning()):
            QMessageBox.warning(self, "Busy", "Another operation is already in progress.")
            return

        self.current_action_type = action_name
        self.set_ui_for_action(True, action_name)

        self.worker_thread = QThread()
        self.worker = GuiApiBridge(ip_address=host, api_port=port)
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
            self.worker_thread.started.connect(lambda: worker_method(settings, sync=sync))

        self.progress_dialog = QProgressDialog(f"Executing {action_name.replace('_', ' ')}...", "Cancel", 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        # Route Cancel through a GUI-thread slot: connecting straight to the worker's
        # cancel_action would be a *queued* call (the worker lives on worker_thread),
        # but during a measurement that thread is blocked in wait_for_measurement and
        # never runs its event loop — so the queued slot would never fire. Calling
        # cancel_action() directly from the GUI thread mutates the shared cancel flag
        # that the poll loop checks.
        self.progress_dialog.canceled.connect(self._cancel_worker_action)

        if action_name == "stream" or action_name == "connect":
            self.worker.handshake_finished_signal.connect(self.progress_dialog.accept)

        self.progress_dialog.show()
        self.worker_thread.start()

    def _stream_is_running(self) -> bool:
        """True while the image-stream worker holds the shared worker thread."""
        return (self.current_action_type == "stream"
                and self.worker_thread is not None and self.worker_thread.isRunning())

    def _execute_concurrent_shot(self, action_name: str, worker_starter_func: str,
                                 settings: AllSettings, sync: bool = False) -> None:
        """Run a single/multi shot on a SECOND, independent worker while the image stream keeps
        running (lab mode). The device delivers the shot's frames on the live stream; the shot
        worker also fetches them to populate the Single/Multi Shot result panel. Only one
        concurrent shot at a time — the device runs a single measurement at once."""
        if self._shot_thread is not None and self._shot_thread.isRunning():
            QMessageBox.warning(self, "Busy", "A shot is already running.")
            return
        host, port = self._parse_host_port(self.ip_input.currentText())
        if not host:
            return
        # One measurement at a time: lock both shot triggers until this one finishes.
        self.ss_trigger_button.setEnabled(False)
        self.ms_trigger_button.setEnabled(False)

        self._shot_thread = QThread()
        self._shot_worker = GuiApiBridge(ip_address=host, api_port=port)
        self._shot_worker.moveToThread(self._shot_thread)
        self._shot_worker.control_action_finished_signal.connect(self.on_control_action_finished)
        self._shot_worker.critical_error_signal.connect(self.show_critical_error)
        self._shot_worker.status_update_signal.connect(self.status_bar.showMessage)
        self._shot_worker.finished_signal.connect(self._on_shot_finished)
        worker_method = getattr(self._shot_worker, worker_starter_func)
        self._shot_thread.started.connect(lambda: worker_method(settings, sync=sync))
        # No modal dialog here — a modal would block the live stream the user is watching.
        self.status_bar.showMessage(f"Running {action_name.replace('_', ' ')} on the live stream…", 4000)
        self._shot_thread.start()

    def _on_shot_finished(self) -> None:
        """Tear down the concurrent shot worker; re-arm the shot triggers if the stream is still
        live in lab mode (otherwise set_ui_for_action already governs their state)."""
        if self._shot_thread is not None:
            self._shot_thread.quit()
            self._shot_thread.wait(2000)
        self._shot_thread = None
        self._shot_worker = None
        if self._stream_is_running() and self._current_mode() == "lab":
            self.ss_trigger_button.setEnabled(True)
            self.ms_trigger_button.setEnabled(True)

    def _cancel_worker_action(self) -> None:
        """Cancel the running worker from the GUI thread (see _execute_worker_action)."""
        if self.worker is not None:
            self.worker.cancel_action()
        # The connection handshake makes blocking HTTP calls with no cancellation checkpoint,
        # so the worker thread stays blocked until the request returns/times out. Don't make
        # the user wait for that: release the UI right away and let the orphaned worker finish
        # and self-clean in the background.
        if self.current_action_type == "connect":
            self._release_cancelled_connect()

    def _release_cancelled_connect(self) -> None:
        """Immediately return the UI to the disconnected state after the user cancels a
        connection, without waiting for the (uninterruptible, possibly timing-out) handshake."""
        if self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog = None
        # Detach the still-running handshake worker so its late signals never touch the UI and
        # it deletes itself once the blocked call returns.
        self._orphan_worker()
        self.current_action_type = None
        # Back to the fully-disconnected UI (device button re-enabled so the user can retry).
        self._connected = False
        self._set_inputs_enabled(False)
        self.ip_input.setEnabled(True)
        self.device_button.setText("Initialize Device")
        self.device_button.setEnabled(True)
        self.mode_combo.setEnabled(False)
        self.status_bar.showMessage("Connection cancelled.", 4000)

    def _orphan_worker(self) -> None:
        """Detach the current worker/thread so it finishes and cleans itself up off the GUI's
        critical path. Its UI-facing signals are disconnected first, so a late result from the
        cancelled work cannot mutate the UI; the thread quits + is deleted once its run() ends."""
        worker, thread = self.worker, self.worker_thread
        self.worker, self.worker_thread = None, None
        if worker is None or thread is None:
            return
        # Drop every UI-facing connection from this worker (best-effort — some may be unset).
        for signal_name in (
            "connection_successful_signal", "critical_error_signal", "status_update_signal",
            "handshake_finished_signal", "finished_signal", "new_frame_signal",
            "fps_update_signal", "production_mode_conflict", "control_action_finished_signal",
        ):
            signal = getattr(worker, signal_name, None)
            if signal is not None:
                try:
                    signal.disconnect()
                except (TypeError, RuntimeError):
                    pass
        # Keep the pair referenced until the thread finishes — otherwise Python would GC the
        # still-running QThread and abort ("QThread: Destroyed while thread is still running").
        pair = (worker, thread)
        self._orphaned_workers.append(pair)

        def _drop(p: tuple[QObject, QThread] = pair) -> None:
            try:
                self._orphaned_workers.remove(p)
            except ValueError:
                pass

        # Re-wire only the self-cleanup: when the blocked call finally returns, run() ends and
        # emits finished_signal → quit the thread's loop and delete both objects.
        worker.finished_signal.connect(thread.quit)
        worker.finished_signal.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(_drop)

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

    def _on_connection_successful(self, infos: Infos, all_settings: AllSettings, features: object = None) -> None:
        """Handles a successful connection by enabling and populating the UI."""
        logger.info("Successfully connected to device. Populating UI with settings.")
        # Build the featureId -> (name, unit) map so the streams show names/units, not ids.
        self._feature_map = {f.id: (f.name or f"F{f.id}", f.unit or "") for f in (features or [])}
        au = infos.analysisunit
        name = (au.order_number or au.serial_number or au.hardware_version) if au else None
        self.status_bar.showMessage(f"Connected to {name or 'device'}. Populating settings...", 10000)
        self._connected = True  # enable on-blur settings autosave
        self._populate_ui_with_settings(all_settings)
        self._set_inputs_enabled(True)  # unlock all inputs now that a device is initialized
        # Device is initialized: lock the URL field and flip the button to "Change Device".
        self.ip_input.setEnabled(False)
        self.device_button.setText("Change Device")
        # Reflect + enable the operating-mode switch (from the device's reported mode),
        # (re-)apply that mode so the device state is consistent (the image stream
        # needs a mode set), and gate the tabs accordingly.
        mode = (infos.system.mode if infos.system else None) or "streaming"
        self._set_mode_combo(mode)
        self.mode_combo.setEnabled(True)
        self._post_mode(mode)
        self._apply_mode_to_tabs(mode)
        # Machine tab: populate what we already fetched (infos + features) for free; GPIO is
        # read lazily when the tab is opened (or on Refresh). Presets load lazily too.
        self._reset_machine()
        self._update_machine_info(infos)
        self._update_features(features or [])
        self._reset_presets()
        self._reset_history()  # fresh device -> the history reloads lazily when its tab is opened
        self._reset_measurements()  # fresh device -> the measurement list reloads lazily on tab open
        self._reset_jobs()  # fresh device -> the export jobs reload lazily when the tab is opened
        # Connecting fires no currentChanged, so if a lazily-loaded tab is already current, load it now.
        current = self.tabs.currentWidget()
        if current is self.history_tab:
            self._reload_history()
        elif current is self.presets_tab:
            self._reload_presets()
        elif current is self.machine_tab:
            self._refresh_machine()
        # Optionally layer realtime events on top of polling (no-op if Reverb is unreachable).
        self._start_event_bridge()

    def _populate_ui_with_settings(self, settings: AllSettings) -> None:
        """Fills the UI input fields from the settings payload.

        v2 has a single ``action`` settings block (the measurement *type* is chosen
        at trigger time), so all three control tabs are populated from it.
        """
        a = settings.action
        if a is None:
            return

        # Velocity feature (id 7) gates the exposure controls;
        # the exposure-mode handlers called below read this flag.
        vel = (settings.features or {}).get(7)
        self._velocity_enabled = bool(vel is not None and vel.enabled)

        # Guard: the setValue/setCurrentIndex calls below would otherwise trip the
        # autosave / mirroring. try/finally so the flag is always cleared.
        self._suppress_autosave = True
        try:
            ext = 1 if a.use_external_trigger else 0
            exposure = 1 if a.double_snap else 0

            # Single-shot tab
            self.ss_trigger_mode.setCurrentIndex(ext)
            self.ss_exposure_mode.setCurrentIndex(exposure)
            self._on_ss_exposure_changed()
            self.ss_flash_delay.setValue(a.flash_delay or ActionSettings.FLASH_DELAY_MIN)
            self.ss_flash_delay2.setValue(a.flash_delay2 or ActionSettings.FLASH_DELAY2_MIN)
            self.ss_exit_delay.setValue(a.exit_delay or ActionSettings.EXIT_DELAY_MIN)
            self._populate_valve("ss", a)

            # Multi-shot tab
            self.ms_trigger_mode.setCurrentIndex(ext)
            self.ms_exposure_mode.setCurrentIndex(exposure)
            self._on_ms_exposure_changed()
            self.ms_save_all_images.setCurrentIndex(1 if a.save_all_images else 0)
            self.ms_count_mode.setCurrentText("Image count" if a.capture_mode_on else "Trigger count")
            self.ms_trigger_count.setValue(a.trigger_count or ActionSettings.TRIGGER_COUNT_MIN)
            self.ms_flash_delay.setValue(a.flash_delay or ActionSettings.FLASH_DELAY_MIN)
            self.ms_flash_delay2.setValue(a.flash_delay2 or ActionSettings.FLASH_DELAY2_MIN)
            self.ms_exit_delay.setValue(a.exit_delay or ActionSettings.EXIT_DELAY_MIN)
            self._populate_valve("ms", a)

            # Video tab (0 = Increment, 1 = Constant)
            self.vid_trigger_mode.setCurrentIndex(ext)
            self.vid_mode_tabs.setCurrentIndex(1 if a.use_constant_mode else 0)
            self.vid_save_all_images.setCurrentIndex(1 if a.save_all_images else 0)
            self.vid_stitch_count.setValue(a.stitch_count or ActionSettings.STITCH_COUNT_MIN)
            self.vid_export_fps.setValue(a.fps or ActionSettings.FPS_MIN)
            self.vid_const_exposure_mode.setCurrentIndex(exposure)
            self._on_vid_exposure_changed()
            self.vid_const_flash_delay.setValue(a.flash_delay or ActionSettings.FLASH_DELAY_MIN)
            self.vid_const_flash_delay2.setValue(a.flash_delay2 or ActionSettings.FLASH_DELAY2_MIN)
            self.vid_const_exit_delay.setValue(a.exit_delay or ActionSettings.EXIT_DELAY_MIN)
            self.vid_const_image_count.setValue(a.image_count or ActionSettings.IMAGE_COUNT_MIN)
            self.vid_inc_start_time.setValue(a.start_time or ActionSettings.START_TIME_MIN)
            self.vid_inc_end_time.setValue(a.end_time or ActionSettings.END_TIME_MIN)
            self.vid_inc_time_increment.setValue(a.time_increment or ActionSettings.TIME_INCREMENT_MIN)
            self._populate_valve("vid", a)
            self._update_video_image_count()

            # Parameters (shared action block) — split "key: value" back into the two
            # fields on every tab.
            params = a.parameters
            for prefix in ("ss", "ms", "vid"):
                for i in range(1, 4):
                    raw = getattr(params, f"parameter{i}", None) if params else None
                    key, _, value = (raw or "").partition(":")
                    getattr(self, f"{prefix}_param{i}_key").setText(key.strip())
                    getattr(self, f"{prefix}_param{i}_value").setText(value.strip())
        finally:
            self._suppress_autosave = False

    def _on_device_button(self) -> None:
        """Single device button: connect when idle, change device when connected."""
        if self._connected:
            self.disconnect_from_device()
        else:
            self.connect_to_device()

    def connect_to_device(self) -> None:
        """Starts the connection and settings-fetching process."""
        self._execute_worker_action(action_name="connect", worker_starter_func="run_connection_handshake")

    def start_stream_process(self) -> None:
        """Initiates the process to start a live video stream."""
        logger.info("Start stream process initiated.")
        # The value stream and the live stream are not run at the same time: tear the
        # value stream down cleanly before the live stream starts.
        self._stop_value_stream()

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
        self._connected = False  # stop on-blur autosave (also blocks the event-bridge retry)
        self._stop_event_bridge()  # tear down the realtime event listener if running
        self._stop_value_stream()  # tear down the value-stream listener if running
        if self._shot_worker is not None:
            self._shot_worker.cancel_action()  # ask a concurrent lab-mode shot to stop
        self._vs_unseen = 0
        self._update_vs_badge()
        self._reset_history()  # clear the frame history + its paging state
        self._reset_presets()  # clear the preset list + its loaded flag
        self._reset_machine()  # clear the machine info / GPIO / features
        self._reset_measurements()  # clear the measurement list + its paging state
        self._reset_jobs()  # clear the export-job list + its loaded flag
        self._set_inputs_enabled(False)  # re-lock inputs; tabs stay navigable
        # Back to the disconnected state: URL editable again, button offers to initialize.
        self.ip_input.setEnabled(True)
        self.device_button.setText("Initialize Device")
        self.device_button.setEnabled(True)
        self.mode_combo.setEnabled(False)
        self._set_mode_combo("streaming")
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
        fetcher.error_occurred.connect(lambda error_msg: self._safe_label_text(target_label, f"Error:\n{error_msg[:100]}"))
        fetcher.finished.connect(thread.quit)
        thread.finished.connect(fetcher.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(_cleanup_worker)
        thread.start()

    def run_single_shot(self) -> None:
        """Gathers settings from the UI and executes a single shot action."""
        self.ss_output.setText("Validating settings…")
        pwl, pwl_error = self._tab_pwl("ss")
        if pwl_error:
            self.show_critical_error("PWL Error", f"Invalid PWL string:\n{pwl_error}")
            self.ss_output.setText("Action failed.")
            return
        action = self._tab_action_dict("ss")
        if pwl:
            action["pwl"] = pwl
        try:
            settings = AllSettings(action=ActionSettings(**action))
            self.ss_output.setText("Executing single shot…")
            # An internal-trigger single shot fires immediately, so run it synchronously;
            # an external trigger may wait indefinitely for its signal, so keep it async.
            internal_trigger = self.ss_trigger_mode.currentIndex() == 0
            if self._stream_is_running():
                # Lab mode: fire on a second worker so the running image stream is untouched.
                self._execute_concurrent_shot("single_shot", "run_single_shot", settings, sync=internal_trigger)
            else:
                self._execute_worker_action("single_shot", "run_single_shot", settings, sync=internal_trigger)
        except ValidationError as e:
            self.show_critical_error("Settings Error", f"Invalid single shot settings:\n{e}")
            self.ss_output.setText("Action failed.")

    def run_multi_shot(self) -> None:
        """Gathers settings from the UI and executes a multi shot action."""
        self.ms_output.clear()
        while (child := self.ms_image_layout.takeAt(0)) is not None:
            if widget := child.widget():
                widget.deleteLater()
        self.ms_output.setText("Validating settings...")
        pwl, pwl_error = self._tab_pwl("ms")
        if pwl_error:
            self.show_critical_error("PWL Error", f"Invalid PWL string:\n{pwl_error}")
            self.ms_output.setText("Action failed.")
            return
        action = self._tab_action_dict("ms")
        if pwl:
            action["pwl"] = pwl
        try:
            settings = AllSettings(action=ActionSettings(**action))
            self.ms_output.setText("Executing multi shot...")
            if self._stream_is_running():
                self._execute_concurrent_shot("multi_shot", "run_multi_shot", settings)
            else:
                self._execute_worker_action("multi_shot", "run_multi_shot", settings)
        except ValidationError as e:
            self.show_critical_error("Settings Error", f"Invalid multi shot settings:\n{e}")
            self.ms_output.setText("Action failed.")

    def run_video(self) -> None:
        """Gathers settings from the UI and executes a video capture action."""
        self.vid_output.clear()
        self.vid_output.setText("Validating settings...")
        self.video_player.setSource(QUrl())
        self.vid_stitched_label.setText("Stitched image will be displayed here")
        self.vid_stitched_label.setPixmap(QPixmap())

        pwl, pwl_error = self._tab_pwl("vid")
        if pwl_error:
            self.show_critical_error("PWL Error", f"Invalid PWL string:\n{pwl_error}")
            self.vid_output.setText("Action failed.")
            return
        action = self._tab_action_dict("vid")
        if pwl:
            action["pwl"] = pwl
        try:
            settings = AllSettings(action=ActionSettings(**action))
            self.vid_output.setText("Executing video capture...")
            self._execute_worker_action("video", "run_video", settings)
        except ValidationError as e:
            self.show_critical_error("Settings Error", f"Invalid video settings:\n{e}")
            self.vid_output.setText("Action failed.")

    def set_ui_for_action(self, is_running: bool, action_type: str) -> None:
        """Toggle controls while an action runs. Never changes connection state — a
        finished/failed action leaves the device initialized."""
        save_groupbox = self.findChild(QGroupBox, "save_groupbox")
        if save_groupbox:
            save_groupbox.setEnabled(not is_running)

        if action_type == "stream":
            self.start_button.setEnabled(not is_running)
            # URL stays locked while connected; only editable when fully disconnected.
            self.ip_input.setEnabled((not is_running) and not self._connected)
            self.stop_button.setEnabled(is_running)
            self.device_button.setEnabled(not is_running)
            # The mode switch is locked while streaming (the mode must not change mid-stream).
            self.mode_combo.setEnabled((not is_running) and self._connected)
            # In lab mode the device accepts a single/multi shot while the image stream runs —
            # the shot's frames arrive on the same live stream. Keep those controls usable then
            # (the shot runs on its own worker, see _execute_concurrent_shot); video stays
            # exclusive. In streaming/production the stream worker holds the device, so every
            # trigger control is disabled while streaming. Tabs stay navigable either way.
            lab_stream = is_running and self._current_mode() == "lab"
            self.ss_input_panel.setEnabled((not is_running) or lab_stream)
            self.ms_input_panel.setEnabled((not is_running) or lab_stream)
            self.vid_input_panel.setEnabled(not is_running)
            self.ss_trigger_button.setEnabled((not is_running) or lab_stream)
            self.ms_trigger_button.setEnabled((not is_running) or lab_stream)
            self.vid_trigger_button.setEnabled(not is_running)
            # Tab navigation follows the current operating mode in both states — it is NOT
            # locked to the Live Stream tab while streaming.
            self._apply_mode_to_tabs(self._current_mode())
            # UI FPS is only meaningful while streaming (Save FPS is driven live in
            # refresh_display, shown only while frames are actually being saved).
            self.ui_fps_label.setVisible(is_running)
            if not is_running:
                self.display_update_timer.stop()
                self.save_button.setEnabled(False)
                self.video_display_label.setText("No Video Signal")
                self.video_display_label.setPixmap(QPixmap())
                self.stream_results_table.setRowCount(0)
                self.current_pixmap = None
                self.save_fps_label.setVisible(False)
                self.ui_fps_label.setText("UI FPS: --")
                self.save_fps_label.setText("Save FPS: --")
                if self.stream_info_label:
                    self.stream_info_label.setText("Not streaming")
                    self.stream_info_label.hide()
        else:
            self.ss_trigger_button.setEnabled(not is_running)
            self.ms_trigger_button.setEnabled(not is_running)
            self.vid_trigger_button.setEnabled(not is_running)
            self.stream_tab.setEnabled(not is_running)
            self.device_button.setEnabled(not is_running)
            self.mode_combo.setEnabled((not is_running) and self._connected)
            # URL stays locked while connected; only editable when fully disconnected.
            self.ip_input.setEnabled((not is_running) and not self._connected)

    def _result_cells(self, res: object) -> tuple[str, str, object]:
        """Resolve a stream FeatureValue into (feature name, value+unit, status), using the
        feature catalogue (falls back to F<id> when the catalogue is unknown)."""
        fid = getattr(res, "feature_id", None)
        name, unit = self._feature_map.get(fid, (f"F{fid}", ""))
        value = getattr(res, "value", None)
        return name, f"{value}{(' ' + unit) if unit else ''}", getattr(res, "status", None)

    def _populate_stream_results_table(self, metadata: object) -> None:
        """Rebuild the live image-stream results table from the current frame's ValueMessage
        (ROI-level results + one row per drop result); clears it when there is none."""
        rows: list[tuple[object, ...]] = []
        for frame in getattr(metadata, "frames", None) or []:
            for roi in getattr(frame, "rois", None) or []:
                for res in getattr(roi, "results", None) or []:
                    rows.append(("ROI", *self._result_cells(res)))
                for drop in getattr(roi, "drops", None) or []:
                    label = f"Drop {getattr(drop, 'index', '?')}"
                    for res in getattr(drop, "results", None) or []:
                        rows.append((label, *self._result_cells(res)))
        table = self.stream_results_table
        table.setRowCount(len(rows))
        for i, cells in enumerate(rows):
            for c, value in enumerate(cells):
                item = table.item(i, c)
                if item is None:
                    item = QTableWidgetItem()
                    table.setItem(i, c, item)
                item.setText("" if value is None else str(value))

    def update_video_display(
        self,
        image: QImage,
        raw_data: bytes,
        index: int,
        timestamp: str,
        width: int,
        height: int,
        comp_val: int,
        color_val: int,
        depth_val: int,
        metadata: object = None,
    ) -> None:
        """
        Receives frame data, formats it for the overlay, and stores the latest image.
        The actual display rendering is handled by the `refresh_display` slot. ``metadata``
        is a per-frame ValueMessage (present in lab/production, None in streaming mode).
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
        self._populate_stream_results_table(metadata)

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
            self.save_fps_label.setVisible(True)  # shown only while actively saving
            if save_elapsed >= 1.0:
                save_fps = self.save_fps_frame_counter / save_elapsed
                self.save_fps_label.setText(f"Save FPS: {save_fps:.1f}")
                self.save_fps_frame_counter, self.save_fps_last_time = 0, now
        elif self.save_fps_label.isVisible():
            self.save_fps_label.setVisible(False)
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

    def on_control_action_finished(self, action_type: str, measurement: Measurement, frames: list[MeasurementFrame]) -> None:
        """Show a finished measurement: fixed meta labels + one card per captured frame
        (image with its results), and — for video — the produced video + stitched image.
        A frame only has an image when its url (backend path) is set."""
        host, port = self._parse_host_port(self.ip_input.currentText())
        base_url = f"http://{host}:{port}"
        attachments = measurement.attachments

        if action_type == "single_shot":
            self._update_meta("ss", measurement)
            self._clear_layout(self.ss_result_layout)
            if frames:
                # Always show the frame's card (image if stored, plus its results).
                self.ss_result_layout.addWidget(self._make_frame_card(frames[0], base_url, title="Frame"))
                self.ss_output.setText("Done." if frames[0].url else "Done — results only (no stored image).")
            else:
                self.ss_result_layout.addWidget(QLabel("No frames in measurement."))
                self.ss_output.setText("Done — no frames.")
            self.ss_result_layout.addStretch()

        elif action_type == "multi_shot":
            self._update_meta("ms", measurement)
            self._clear_layout(self.ms_image_layout)
            if not frames:
                self.ms_image_layout.addWidget(QLabel("No frames in measurement."))
                self.ms_output.setText("Done — no frames.")
            else:
                # A card per frame — results are shown for every frame, with or without
                # a stored image (the image area just says "No stored image" if absent).
                for frame in frames:
                    self.ms_image_layout.addWidget(self._make_frame_card(frame, base_url))
                stored = sum(1 for f in frames if f.url)
                self.ms_output.setText(f"Done — {len(frames)} frame(s), {stored} with a stored image.")
            self.ms_image_layout.addStretch()

        elif action_type == "video":
            self._update_meta("vid", measurement)
            # Video attachment → stream it straight into the media player.
            if attachments and attachments.video and attachments.video.download_url:
                self.video_player.setSource(QUrl(attachments.video.download_url))
                self.vid_output.setText("Video ready — press Play.")
            else:
                self.video_player.setSource(QUrl())
                self.vid_output.setText("No video attachment available for this measurement.")
            # setSource() does not emit playbackStateChanged in Qt6, so refresh the
            # play/pause/stop button state explicitly (else Play stays disabled).
            self.update_video_button_state(self.video_player.playbackState())
            # Stitched-image attachment → show it, falling back to the first frame.
            if attachments and attachments.stitched_image and attachments.stitched_image.download_url:
                self.vid_stitched_label.setText("Fetching stitched image…")
                self.start_image_fetch(attachments.stitched_image.download_url, self.vid_stitched_label)
            elif frames and frames[0].url:
                self.vid_stitched_label.setText("Fetching first frame…")
                self.start_image_fetch(f"{base_url}/api/v2/frames/{frames[0].id}/image", self.vid_stitched_label)
            else:
                self.vid_stitched_label.setText("No stitched image or stored frames.")

        self.status_bar.showMessage(f"{action_type.replace('_', ' ').title()} finished — status: {measurement.status}.", 5000)

    @staticmethod
    def _safe_label_text(label: QLabel, text: str) -> None:
        """Set label text unless the label's C++ object was already destroyed (its card may
        have been torn down while an image fetch was still in flight)."""
        if not _is_deleted(label):
            label.setText(text)

    def display_image_on_label(self, image_data: QByteArray, label: QLabel) -> None:
        """Displays image data on a given QLabel, scaling it to fit."""
        if _is_deleted(label):  # the card was torn down (Refresh/disconnect/reload) mid-fetch
            return
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
        """Show a critical error and reset only the *action* UI. The device stays
        initialized — an error must not silently disconnect it."""
        if self.progress_dialog:
            self.progress_dialog.close()

        QMessageBox.critical(self, title, message)
        if self.current_action_type:
            self.set_ui_for_action(False, self.current_action_type)
        self.status_bar.showMessage("Error — device still connected.", 6000)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """Handles the window close event, ensuring all threads are stopped."""
        logger.info("Close event triggered. Stopping worker if active.")
        self._jobs_poll_timer.stop()
        self.video_player.stop()
        self._stop_event_bridge()
        if self._events_thread is not None and self._events_thread.isRunning():
            self._events_thread.quit()
            self._events_thread.wait(1500)
        self._stop_value_stream()
        if self._vs_thread is not None and self._vs_thread.isRunning():
            self._vs_thread.wait(1500)
        if self.worker:
            self.worker.cancel_action()
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.wait(1000)
        if self._shot_worker is not None:
            self._shot_worker.cancel_action()
        if self._shot_thread is not None and self._shot_thread.isRunning():
            self._shot_thread.quit()
            self._shot_thread.wait(1500)
        # Orphaned (cancelled-but-uninterruptible) workers may still be draining a blocked
        # request; give each a brief bounded wait so we don't tear down a live QThread.
        for _worker, thread in list(self._orphaned_workers):
            if thread.isRunning():
                thread.wait(1000)
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


def _user_log_file(app_name: str = "Droptical API Example Client", file_name: str = "client.log") -> str | None:
    """A per-user, writable log path. A frozen app launched from Finder/Explorer
    starts with a read-only working directory (macOS uses ``/``), so a relative
    filename fails — resolve an absolute per-user location instead. Returns None
    if no writable directory can be created."""
    home = pathlib.Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Logs" / app_name
    elif sys.platform == "win32":
        base = pathlib.Path(os.environ.get("LOCALAPPDATA", str(home))) / app_name / "logs"
    else:
        base = pathlib.Path(os.environ.get("XDG_STATE_HOME", str(home / ".local" / "state"))) / app_name
    try:
        base.mkdir(parents=True, exist_ok=True)
        return str(base / file_name)
    except OSError:
        return None


def setup_client_logging(log_file: str | None = None) -> None:
    """Configures logging: a per-user log file plus stdout. A failing file handler
    never prevents the app from starting (falls back to console-only)."""
    if log_file is None:
        log_file = _user_log_file()

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        try:
            handlers.insert(0, logging.FileHandler(log_file, encoding="utf-8"))
        except OSError:
            log_file = None  # keep console logging only; never crash on the log file

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-8s] %(name)-14s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    if log_file:
        logging.getLogger("ClientGUI").info("Logging to %s", log_file)


if __name__ == "__main__":
    setup_client_logging()
    app = QApplication(sys.argv)
    # Force Fusion: the native macOS style ignores QSS sub-control rules, so spin/combo
    # arrows never render there. Fusion honors them (and looks flatter). Pair it with a
    # dark palette for non-stylesheet-covered widgets.
    app.setStyle("Fusion")
    _apply_dark_palette(app)
    app.setStyleSheet(STYLESHEET + _arrow_stylesheet())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
