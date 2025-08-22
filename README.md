# Python droptical API Client

## Overview

This repository contains a Python client for interacting with the droptical Analysis Unit. The library provides a high-level   interface for controlling the device via its HTTP API and for consuming its high-performance TCP video stream.

The project includes:

  * `src/droptical_api_client/client.py`: The core API module containing the main client classes.
  * `src/droptical_api_client/models.py`: Pydantic models that ensure type-safe communication with the device's API.
  * A set of custom exceptions for predictable error handling.
  * A convenience wrapper to make the video stream compatible with OpenCV's `VideoCapture` interface.
  * A mock server for development and testing.
  * Multiple example applications (`cv2`, `PyQt6`, etc.).

## Features

  * **Dual API Interface**: Separate, optimized channels for device control (HTTP REST) and data streaming (TCP).
  * **Comprehensive Command Support**: Full coverage of the device's API, from reading settings to triggering actions and managing presets.
  * **Type-Safe Communication**: Leverages Pydantic models for request and response validation, reducing runtime errors.
  * **High-Performance Streaming**: A multi-threaded TCP client designed to handle high-throughput video streams with various compression codecs (LZ4, ZSTD, Zlib).
  * **Convenience Helpers**:
      * The `Frame` dataclass includes methods to instantly convert raw image data to Pillow (`PIL`) or NumPy (`OpenCV`) formats.
      * The `dropticalAPIClientCapture` class provides a familiar `cv2.VideoCapture`-like interface for easy integration.
  * **Robust Error Handling**: A clear hierarchy of custom exceptions (`DeviceConnectionError`, `DeviceCommandError`, `StreamDisconnectedError`) allows for fine-grained error management.

## Prerequisites

  * Python 3.10 or newer
  * `pip` and `venv` (usually included with Python)

## Installation

1.  **Clone the Repository**

    ```bash
    git clone git@github.com:droptical-GmbH/droptical_python_api_client.git
    cd git@github.com:droptical-GmbH/droptical_python_api_client.git
    ```

2.  **Create and Activate a Virtual Environment**
    Using a virtual environment is strongly recommended.

      * On macOS / Linux:
        ```bash
        python3 -m venv .venv
        source .venv/bin/activate
        ```
      * On Windows:
        ```bash
        python -m venv .venv
        .\.venv\Scripts\activate
        ```

3.  **Install Dependencies**
    This project uses `pyproject.toml` to manage dependencies. Install the package from your local clone using `pip`.

    **Core Installation (minimal):**
    Installs only the essential packages for API control (e.g., `requests`).
    ```bash
    pip install .
    ```

    **Installation with Optional Features:**
    You can install optional features by specifying "extras". You can combine them as needed.

    *   **Image Processing (`image`):** For converting frames to Pillow formats.
        ```bash
        pip install '.[image]'
        ```
    *   **All Stream Codecs (`stream`):** Adds support for all compression algorithms (LZ4, ZSTD).
        ```bash
        pip install '.[stream]'
        ```
    *   **OpenCV Wrapper (`opencv`):** For the `cv2.VideoCapture`-like interface. Requires `image`.
        ```bash
        pip install '.[image,opencv]'
        ```
    *   **GUI Example (`gui`):** For running and building the PyQt6 GUI example.
        ```bash
        pip install '.[gui]'
        ```

    **Full Installation (for running all examples):**
    To install everything needed to run all examples and use all features:
    ```bash
    pip install '.[image,stream,opencv,gui]'
    ```

## Getting Started: Running the Mock Server & Examples

To test the client without a physical device, you can use the included mock server. The examples are pre-configured to connect to this server.

The process involves two steps: running the server in one terminal, and running a client example in another.

### Step 1: Start the Mock Server

The mock server simulates the device's API and video stream. Open a terminal, activate the virtual environment, and run the following command from the project's root directory:

```bash
# Make sure your virtual environment is activated
python -m tests.mock_server
```

The server will start and print its configuration. It listens on `127.0.0.1`. You can customize the stream with command-line arguments (e.g., `--fps 60`, `--algo ZSTD`). Leave this terminal window open.

### Step 2: Run an Example Client

Now, **open a second terminal window**, activate the same virtual environment, and run one of the client examples.

The command-line examples accept the device's IP address as an argument. **If you don't provide one, they will default to `127.0.0.1`** to connect to the mock server automatically.

#### Option A: Simple OpenCV Client (`cv2_capture_example`)

This example uses the `dropticalAPIClientCapture` wrapper for a simple OpenCV loop.

```bash
# To connect to the mock server (uses default 127.0.0.1)
python -m examples.cv2.cv2_capture_example

# To connect to a real device at a specific IP
python -m examples.cv2.cv2_capture_example 192.168.1.100
```

#### Option B: Live Stream Console Client (`live_stream_example`)

This example demonstrates the core `streaming_session` and prints frame info to the console.

```bash
# To connect to the mock server (uses default 127.0.0.1)
python -m examples.general.live_stream_example

# To connect to a real device at a specific IP
python -m examples.general.live_stream_example 192.168.1.100
```

#### Option C: Full-Featured GUI Client

This example is a more complex application built with PyQt6. It does not take command-line arguments; you enter the IP address directly into the GUI window.

```bash
# In your second terminal (with .venv activated)
python -m examples.gui.main
```

-----

## API Documentation & Usage

The library offers two primary ways to interact with the device, catering to different use cases.

1.  **`dropticalAPIClient`**: The main class for full control over all device functions.
2.  **`dropticalAPIClientCapture`**: A simplified, OpenCV-style wrapper for easily grabbing video frames.

### 1\. The `dropticalAPIClient` Class (Full Control)

This is the core class for sending commands and managing the device.

#### 1.1. Connecting to the Device

First, instantiate the class and connect it to the device's IP address.

```python
from droptical_api_client import dropticalAPIClient, DeviceConnectionError, MachineInfo

api = dropticalAPIClient()
try:
    api.connect("192.168.1.100") # Use the device's IP address
    info: MachineInfo = api.get_machine_info()
    # Note: hostname is in info.network, serial number is info.analysisunit.snr
    print(f"Successfully connected to {info.network.hostname} (Serial: {info.analysisunit.snr})")
except DeviceConnectionError as e:
    print(f"Connection failed: {e}")
```

#### 1.2. HTTP Command Reference

All methods that interact with the HTTP control API will raise a `DeviceCommandError` if the device reports a functional error.

##### **Read-Only Methods**

These methods retrieve settings or status information. They return Pydantic models for easy data access.

  * `get_single_shot_settings() -> SingleShotSettings`: Retrieves settings for single measurements.
  * `get_multi_shot_settings() -> MultiShotSettings`: Retrieves settings for multi-shot operations.
  * `get_video_settings() -> VideoSettings`: Retrieves settings for video recordings.
  * `get_all_settings() -> AllSettings`: Retrieves all device settings in a single call.
  * `get_machine_info() -> MachineInfo`: Gets hardware, software, and network information.
  * `get_preset_info() -> PresetInfo`: Gets information about the currently loaded preset.
  * `get_gpio_levels() -> GpioLevels`: Reads the current state of General Purpose I/O pins.

##### **Read/Write Properties**

These Python properties provide a convenient way to get and set blocks of settings.

  * `calculatory_settings`: Gets or sets calculation and image processing settings.
    ```python
    # Get
    calc_settings = api.calculatory_settings
    # Modify and set
    calc_settings.blur_radius = 5
    api.calculatory_settings = calc_settings
    ```
  * `camera_settings`: Gets or sets camera parameters like exposure, gain, and frame rate.
  * `machine_settings`: Gets or sets general machine configuration.

##### **Action Methods**

These methods trigger a specific action on the device.

  * `trigger_single_shot(settings: SingleShotSettings, ...) -> SingleShotResponse`: Executes a single measurement.
  * `trigger_multi_shot(settings: MultiShotSettings, ...) -> MultiShotResponse`: Executes a multi-shot sequence.
  * `trigger_video(settings: VideoSettings, ...) -> VideoResponse`: Records a video.

##### **State-Changing & Simple Methods**

These methods perform simple actions, typically without a payload.

  * `reset_errors()`: Resets device errors.
  * `reboot()`: Reboots the device.
  * `shutdown()`: Shuts down the device.
  * `power_on_camera()` / `power_off_camera()`: Controls camera power.
  * `set_production_mode(enabled: bool)`: Enables or disables production mode.
  * `set_streaming_mode(enabled: bool)`: Enables or disables the TCP video stream.

##### **Preset Management**

  * `list_presets(...) -> List[Preset]`: Returns a list of all available presets.
  * `load_preset(gid: int, version: int)`: Loads a specific preset.
  * `create_preset(name: str, ...) -> Preset`: Creates a new preset from the current settings.
  * `create_preset_version(gid: int, ...) -> Preset`: Creates a new version of an existing preset.
  * `edit_preset(preset_id: int, name: str, ...)`: Edits a preset's metadata.
  * `delete_preset(preset_id: int)`: Marks a preset as deleted.

##### **Destructive Operations**

These operations permanently delete data. Use with caution.

  * `factory_reset()`: **WARNING:** Resets all settings and data to factory defaults.
  * `clear_data()`: **WARNING:** Deletes all measurement data and images.

#### 1.3. TCP Video Streaming

The TCP stream provides a low-latency feed of raw image frames. The recommended way to use it is with the `streaming_session` context manager, which handles starting and stopping the stream automatically.

The stream yields `Frame` objects, which contain the image data and metadata.

```python
from droptical_api_client import dropticalAPIClient, Frame
import cv2

api = dropticalAPIClient()
api.connect("192.168.1.100")

# The streaming_session context manager ensures the stream is properly closed
with api.streaming_session() as frame_generator:
    print("Streaming started. Press 'q' to quit.")
    for frame in frame_generator:
        print(f"Received Frame ID: {frame.id}, Latency: {frame.latency_ms:.2f} ms")

        # Convert to an OpenCV-compatible format (BGR)
        cv_image = frame.to_numpy_array(bgr=True)

        cv2.imshow("Live Stream", cv_image)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

cv2.destroyAllWindows()
print("Stream stopped.")
```

##### **The `Frame` Dataclass**

Each object yielded by the stream is an instance of `Frame`, which has the following useful attributes and methods:

  * **Attributes**:
      * `id: int`: Unique frame counter.
      * `server_timestamp: datetime`: Timestamp when the frame was captured on the device.
      * `reception_timestamp: datetime`: Timestamp when the frame was received by the client.
      * `width: int`, `height: int`: Dimensions of the image.
      * `compression: CompressionAlgorithm`: The compression format used (e.g., `LZ4`, `ZSTD`).
      * `color_mode: ColorMode`: `GRAYSCALE` or `RGB`.
      * `raw_data: bytes`: The decompressed, raw image pixel data.
  * **Properties & Methods**:
      * `latency_ms: float`: Calculates the network latency for the frame.
      * `to_pil_image() -> PIL.Image`: Converts the frame to a Pillow Image object.
      * `to_numpy_array(bgr: bool = True) -> numpy.ndarray`: Converts the frame to a NumPy array. By default, it returns a BGR image suitable for OpenCV.
      * `save(path_template: str)`: Saves the frame to a file.

### 2\. The `dropticalAPIClientCapture` Class (OpenCV-Style)

This class is a convenience wrapper that makes the `dropticalAPIClient` stream behave like OpenCV's `cv2.VideoCapture`. It is perfect for quick integrations or applications already built around OpenCV's capture loop.

It handles connecting, starting the stream, and fetching frames in a background thread.

```python
from droptical_api_client import dropticalAPIClientCapture
import cv2

IP_ADDRESS = "192.168.1.100"

# The 'with' statement ensures release() is called automatically
with dropticalAPIClientCapture(IP_ADDRESS) as cap:
    if not cap.isOpened():
        print("Error: Could not open video stream.")
        exit()

    while True:
        # read() mimics the cv2.VideoCapture.read() method
        ret, frame = cap.read()

        if not ret:
            print("Stream ended or an error occurred.")
            break

        cv2.imshow('droptical Stream', frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

cv2.destroyAllWindows()
```

#### **Class Methods**

  * `__init__(ip_address: str, ...)`: Creates the object and connects to the device.
  * `read() -> tuple[bool, numpy.ndarray | None]`: Reads the next available frame. Returns a boolean (`True` on success) and the frame as a BGR NumPy array.
  * `isOpened() -> bool`: Returns `True` if the stream is active and frames can be read.
  * `release()`: Stops the stream and cleans up resources.

### 3\. Error Handling

The library uses custom exceptions to signal specific problems:

  * `DeviceConnectionError`: Raised for network-level issues, such as being unable to connect to the device's HTTP or TCP port.
  * `DeviceCommandError`: Raised when the device's API returns a specific error for a command (e.g., invalid parameters). The `details` attribute may contain extra information from the device.
  * `StreamDisconnectedError`: Raised when the TCP video stream is unexpectedly closed by the server.
