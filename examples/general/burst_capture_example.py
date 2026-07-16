import argparse
import logging
import os
import sys

# This block allows the example to be run without installing the package.
# It adds the project's 'src' directory to the Python path.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(project_root, "src"))


from droptical_api_client import DeviceConnectionError, dropticalAPIClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# --- Setup Command-Line Argument Parsing ---
parser = argparse.ArgumentParser(description="Capture a burst of frames from a droptical device.")
parser.add_argument("ip_address", type=str, nargs="?", default="127.0.0.1", help="The IP address or hostname of the droptical device. Defaults to 127.0.0.1.")
parser.add_argument("port", type=int, nargs="?", default=80, help="The device API port. Default: 80.")
args = parser.parse_args()

FRAMES_TO_CAPTURE = 50

api = dropticalAPIClient()

try:
    print(f"Connecting to device at: {args.ip_address}")
    api.connect(args.ip_address, api_port=args.port)

    # The image stream is mode-neutral: put the device into a streaming-capable
    # mode explicitly before capturing a burst of frames.
    api.set_streaming_mode()

    print(f"Collecting a burst of {FRAMES_TO_CAPTURE} frames. This may take a moment...")

    # This function is blocking and will only return once all
    # frames have been collected or an error occurs.
    frames_list = api.capture_frames(count=FRAMES_TO_CAPTURE)

    if not frames_list:
        print("No frames received.")
    else:
        print(f"\n{len(frames_list)} frames successfully collected.")

        # Example of post-capture analysis:
        latencies = [f.latency_ms for f in frames_list]
        avg_latency = sum(latencies) / len(latencies)
        print(f"Average latency over the burst: {avg_latency:.1f}ms")

        # Save all captured images
        for frame in frames_list:
            frame.save(f"burst_session/frame_{frame.index:04d}.png")
        print(f"All {len(frames_list)} images saved in the 'burst_session/' directory.")

except DeviceConnectionError as e:
    logging.error(f"Connection failed: {e}")
except Exception as e:
    logging.error(f"An unexpected error occurred: {e}")
