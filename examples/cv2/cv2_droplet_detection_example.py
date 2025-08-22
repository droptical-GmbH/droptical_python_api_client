import argparse
import math
import os
import sys
import time

# This block allows the example to be run without installing the package.
# It adds the project's 'src' directory to the Python path.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(project_root, "src"))


import cv2  # noqa: E402

from droptical_api_client import DeviceError, dropticalAPIClientCapture  # noqa: E402

# --- Set up command-line arguments ---
parser = argparse.ArgumentParser(description="Connects to a Droptical device, detects a droplet, and draws its contour and bounding box.")
parser.add_argument(
    "ip_address",
    type=str,
    nargs="?",
    default="127.0.0.1",
    help="The IP address or hostname of the Droptical device. Defaults to 127.0.0.1 (for the mock server).",
)
args = parser.parse_args()

print(f"Attempting to connect to the device at {args.ip_address}...")

try:
    # The 'with' statement ensures that resources are released at the end.
    with dropticalAPIClientCapture(args.ip_address) as cap:
        if not cap.isOpened():
            print("Error: Could not open the video stream.")
            exit()

        # Initialization for speed calculation
        last_time = time.time()
        previous_droplets: list[tuple[int, int]] = []  # Stores the center points (cx, cy) of the droplets from the last frame

        print("Stream opened. Press 'q' to quit.")

        while True:
            # The .read() method works exactly like in OpenCV!
            ret, frame = cap.read()

            # Check if the stream has been closed
            if not cap.isOpened():
                print("Stream was closed.")
                break

            # If a frame is available (ret is True) and it is not empty
            if ret and frame is not None:
                # --- Get the time difference for speed calculation ---
                current_time = time.time()
                dt = current_time - last_time
                last_time = current_time

                # --- Image processing for droplet detection ---

                # 1. Convert to grayscale if the image is in color
                # The mock server sends grayscale images by default, so this check is important.
                if len(frame.shape) == 3 and frame.shape[2] == 3:
                    # The image is 3-channel (BGR), so we convert it.
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                else:
                    # The image is already 1-channel (grayscale).
                    gray = frame

                # 2. Blur to reduce noise
                blurred = cv2.GaussianBlur(gray, (5, 5), 0)

                # 3. Apply a threshold to create a binary image.
                # This value may need to be adjusted for lighting conditions.
                # We assume the droplet is brighter than the background.

                _, binary_img = cv2.threshold(blurred, 100, 255, cv2.THRESH_BINARY)

                # 4. Find contours in the binary image
                contours, _ = cv2.findContours(binary_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)  # type: ignore[assignment]

                # 5. Convert the frame to a BGR image if it's grayscale,
                #    so we can draw colored contours/boxes.
                #    The detection itself was performed on the grayscale image.
                if len(frame.shape) == 2 or frame.shape[2] == 1:
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

                current_droplets = []
                # 6. Iterate through the found contours and draw on the (now colored) frame
                for contour in contours:
                    # Ignore small contours (noise)
                    if cv2.contourArea(contour) > 100:
                        x, y, w, h = cv2.boundingRect(contour)

                        # --- Calculate properties ---
                        area = cv2.contourArea(contour)
                        # Calculate the center point (Center of Mass) of the contour
                        M = cv2.moments(contour)
                        if M["m00"] != 0:
                            cx = int(M["m10"] / M["m00"])
                            cy = int(M["m01"] / M["m00"])
                        else:
                            # Fallback if the center point cannot be calculated
                            cx, cy = x + w // 2, y + h // 2

                        # --- Calculate velocity ---
                        velocity_pps = 0.0  # Pixels per second
                        if previous_droplets and dt > 0:
                            # Find the closest droplet from the previous frame
                            # Note: This is a simple nearest-neighbor tracking approach.
                            # For more complex scenarios with many crossing droplets,
                            # a more robust tracker like a Kalman filter might be needed.
                            min_dist = float("inf")
                            for prev_cx, prev_cy in previous_droplets:
                                dist = math.hypot(cx - prev_cx, cy - prev_cy)
                                if dist < min_dist:
                                    min_dist = dist

                            # If a nearby droplet was found (max 50px away), calculate the velocity
                            if min_dist < 50:
                                velocity_pps = min_dist / dt

                        current_droplets.append((cx, cy))

                        # --- Drawing ---
                        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                        cv2.drawContours(frame, [contour], -1, (0, 0, 255), 2)
                        info_text = f"Pos:({x},{y}) Area:{int(area)} Vel:{int(velocity_pps)}px/s"
                        cv2.putText(frame, info_text, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

                # Update the list of droplets for the next frame
                previous_droplets = current_droplets

                cv2.imshow("Droplet Detection", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

except DeviceError as e:
    print(f"A device error has occurred: {e}")
except Exception as e:
    print(f"An unexpected error has occurred: {e}")
finally:
    cv2.destroyAllWindows()
    print("Program terminated.")
