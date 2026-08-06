import argparse
import os
import sys

# This block allows the example to be run without installing the package.
# It adds the project's 'src' directory to the Python path.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(project_root, "src"))

import cv2  # noqa: E402

from droptical_api_client import dropticalAPIClient, dropticalImageStreamCapture  # noqa: E402

# --- Setup Command-Line Argument Parsing ---
parser = argparse.ArgumentParser(description="Connect to a droptical device stream using an OpenCV-like interface.")
parser.add_argument(
    "ip_address",
    type=str,
    nargs="?",
    default="127.0.0.1",
    help="The IP address or hostname of the droptical device. Defaults to 127.0.0.1.",  # Makes the argument optional
)
parser.add_argument("port", type=int, nargs="?", default=80, help="Device API port. Default: 80.")
args = parser.parse_args()

print(f"Attempting to connect to device at: {args.ip_address}")

# The capture wrapper is mode-neutral, so put the device into streaming mode first
# via a short-lived control client before opening the stream.
control = dropticalAPIClient()
control.connect(args.ip_address, api_port=args.port)
control.set_streaming_mode()

# Simply replace cv2.VideoCapture(0) with the 'dropticalImageStreamCapture' wrapper class
# The IP address is passed from the command line.
cap = dropticalImageStreamCapture(args.ip_address, api_port=args.port)

while True:
    # The .read() method works exactly like in OpenCV!
    ret, frame = cap.read()

    # If a frame exists (ret is True) and it's not empty
    if ret and frame is not None:
        cv2.imshow("Device Stream via OpenCV Adapter", frame)

    # Check if the stream has been closed
    if not cap.isOpened():
        print("Stream closed.")
        break

    # Exit with 'q'
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# Release resources
cap.release()
cv2.destroyAllWindows()
print("Program terminated.")
