import logging

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal
from PyQt6.QtGui import QImage

logger = logging.getLogger("FrameSaver")


class FrameSaverSignals(QObject):
    """
    Defines the signals available from a FrameSaver task.
    """

    error = pyqtSignal(str)
    finished = pyqtSignal()


class FrameSaver(QRunnable):
    """
    A QRunnable task to save an image to a file in a separate thread.
    This version is more efficient as it saves the QImage directly.
    """

    def __init__(self, raw_data: bytes, width: int, height: int, img_format: QImage.Format, file_path: str):
        super().__init__()
        self.raw_data = raw_data
        self.width = width
        self.height = height
        self.img_format = img_format
        self.file_path = file_path
        self.signals = FrameSaverSignals()

    def run(self) -> None:
        """
        The main task logic. It creates a QImage and saves it directly.
        """
        try:
            image = QImage(self.raw_data, self.width, self.height, self.img_format)

            if not image.save(self.file_path):
                raise OSError(f"QImage.save() failed for path: {self.file_path}")

        except Exception as e:
            error_msg = f"Could not save frame to {self.file_path}: {e}"
            logger.error(error_msg)
            self.signals.error.emit(error_msg)
        finally:
            self.signals.finished.emit()
