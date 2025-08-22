import logging

import requests
from PyQt6.QtCore import QByteArray, QObject, pyqtSignal

logger = logging.getLogger("MediaFetcher")


class MediaFetcher(QObject):
    """
    A worker object that fetches media from a URL in a separate thread.
    """

    # Signal emitted when the media content has been successfully fetched.
    media_fetched = pyqtSignal(QByteArray)
    # Signal emitted if an error occurs during fetching.
    error_occurred = pyqtSignal(str)
    # Signal to indicate the worker has finished its job.
    finished = pyqtSignal()

    def __init__(self, url: str):
        super().__init__()
        self.url = url
        logger.info(f"MediaFetcher initialized for URL: {self.url}")

    def run(self) -> None:
        """
        Executes the media download. This method should be called when the
        thread starts.
        """
        try:
            logger.info(f"Attempting to fetch media from {self.url}...")
            # Use requests to get the content from the URL with a 10-second timeout.
            response = requests.get(self.url, timeout=10)
            # Raise an exception for bad status codes (like 404 or 500).
            response.raise_for_status()

            # Emit the fetched content as a QByteArray.
            self.media_fetched.emit(QByteArray(response.content))
            logger.info(f"Successfully fetched media from {self.url}.")

        except requests.RequestException as e:
            # If any network-related error occurs, emit the error signal.
            error_message = f"Failed to fetch {self.url}: {e}"
            logger.error(error_message)
            self.error_occurred.emit(str(e))

        finally:
            # Always emit the finished signal to allow for thread cleanup.
            self.finished.emit()
