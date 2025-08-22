import argparse
import logging
import os
import sys

# This block allows the example to be run without installing the package.
# It adds the project's 'src' directory to the Python path.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(project_root, "src"))


from droptical_api_client import DeviceConnectionError, dropticalAPIClient  # noqa: E402

# Configure logging for clear output
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# --- Setup Command-Line Argument Parsing ---
parser = argparse.ArgumentParser(description="Stream live frames from a droptical device to the console.")
parser.add_argument("ip_address", type=str, nargs="?", default="127.0.0.1", help="The IP address or hostname of the droptical device. Defaults to 127.0.0.1 (mock server).")
args = parser.parse_args()

api = dropticalAPIClient()

try:
    print(f"Connecting to device at: {args.ip_address}")
    api.connect(args.ip_address)

    print("Starting live stream. Press CTRL+C to stop.")

    # The 'with' statement ensures the stream is always started cleanly
    # and stopped at the end, even if errors occur.
    with api.streaming_session() as frame_stream:
        # The 'for' loop elegantly waits for the next frame.
        # The code is non-blocking for the CPU while waiting for I/O.
        for frame in frame_stream:
            print(f"Live frame received: ID={frame.id1}, Latency={frame.latency_ms:.1f}ms, Size={frame.width}x{frame.height}")

            # This is where the processing would happen, e.g.,
            # displaying the image in a GUI.

except DeviceConnectionError as e:
    logging.error(f"Could not connect to the device: {e}")
except KeyboardInterrupt:
    # Allows the user to terminate cleanly
    logging.info("\nStream stopped by user.")
finally:
    logging.info("Program terminated.")
