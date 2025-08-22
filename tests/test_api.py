import os
import socket
import subprocess
import time
from collections.abc import Generator
from contextlib import closing
from typing import Any

import numpy as np
import pytest

from droptical_api_client import (
    HTTP_API_PORT,
    TCP_STREAM_PORT,
    CameraSettings,
    DeviceCommandError,
    Frame,
    MachineInfo,
    SingleShotResponse,
    SingleShotSettings,
    dropticalAPIClient,
    dropticalAPIClientCapture,
)

# --- Pytest Fixtures to manage server and client ---


@pytest.fixture(scope="session")
def mock_server() -> Generator[dict[str, str | int], None, None]:
    """
    Starts the mock_server.py in a subprocess for the entire test session.
    Waits until the server's API and TCP ports are open before yielding.
    This ensures the server is started only once for all tests.
    """
    # For simplicity, we use fixed ports as defined in the mock server
    api_port = HTTP_API_PORT
    tcp_port = TCP_STREAM_PORT
    server_host = "127.0.0.1"

    # Command to run the mock server as a module from the project root.
    # This assumes pytest is run from the project's root directory.
    command = ["python", "-m", "tests.mock_server", "--algo", "LZ4", "--fps", "100", "--stats-interval", "0"]

    # When running under pre-commit, the subprocess might not inherit the correct
    # PYTHONPATH to find the 'src' directory. We explicitly add it to the
    # environment of the subprocess to make the test execution robust.
    env = os.environ.copy()
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_path = os.path.join(project_root, "src")
    # Prepend our src_path to ensure it's checked first.
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}"

    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    # Wait for the server to be ready by polling the ports
    max_wait_seconds = 10
    start_time = time.time()
    api_ready = False
    tcp_ready = False

    print("\nWaiting for mock server to start...")
    while time.time() - start_time < max_wait_seconds:
        # Check API port
        if not api_ready:
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
                if sock.connect_ex((server_host, api_port)) == 0:
                    api_ready = True
                    print(f"Mock API server is up on port {api_port}.")

        # Check TCP port
        if not tcp_ready:
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
                if sock.connect_ex((server_host, tcp_port)) == 0:
                    tcp_ready = True
                    print(f"Mock TCP server is up on port {tcp_port}.")

        if api_ready and tcp_ready:
            break
        time.sleep(0.2)

    if not (api_ready and tcp_ready):
        # If server failed to start, terminate process and show logs
        proc.terminate()
        stdout, stderr = proc.communicate()
        pytest.fail(f"Mock server failed to start within the timeout period.\nSTDOUT:\n{stdout.decode()}\nSTDERR:\n{stderr.decode()}")

    yield {"host": server_host, "api_port": api_port, "tcp_port": tcp_port}

    # Teardown: stop the server after all tests in the session are done
    print("\nShutting down mock server...")
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def api_client(mock_server: dict[str, Any]) -> dropticalAPIClient:
    """
    Provides a connected dropticalAPIClient client instance for each test function.
    This fixture depends on `mock_server` to ensure the server is running.
    """
    api = dropticalAPIClient()
    api.connect(mock_server["host"], api_port=mock_server["api_port"])
    return api


@pytest.fixture
def clean_api_client(api_client: dropticalAPIClient) -> dropticalAPIClient:
    """
    Provides an API client and ensures the mock server is in a default
    state before the test runs by calling factory_reset. This is useful
    for tests that modify the server's state.
    """
    api_client.factory_reset()
    time.sleep(0.1)  # Give the server a moment to process the reset
    return api_client


# --- Test Cases ---


def test_connection_and_machine_info(api_client: dropticalAPIClient) -> None:
    """Tests basic connection and retrieval of machine information."""
    assert api_client._api_url is not None
    info = api_client.get_machine_info()
    assert isinstance(info, MachineInfo)
    assert info.analysisunit.production_mode is False  # Default from mock server


def test_read_write_settings(api_client: dropticalAPIClient) -> None:
    """Tests getting and setting a block of settings (e.g., CameraSettings)."""
    # 1. Get initial settings
    initial_settings = api_client.camera_settings
    assert isinstance(initial_settings, CameraSettings)
    assert initial_settings.flip_image is False

    # 2. Modify and set new settings
    new_settings = CameraSettings.default()
    new_settings.flip_image = True
    assert new_settings.exposure_time is not None
    new_settings.exposure_time.uz = 2.5
    api_client.camera_settings = new_settings

    # 3. Get settings again and verify the change
    updated_settings = api_client.camera_settings
    assert updated_settings.flip_image is True
    assert updated_settings.exposure_time is not None
    assert updated_settings.exposure_time.uz == 2.5


def test_streaming_get_frames(api_client: dropticalAPIClient) -> None:
    """Tests the get_frames() convenience method for burst capture."""
    frames_to_capture = 10
    frames = api_client.get_frames(count=frames_to_capture)

    assert len(frames) == frames_to_capture
    assert all(isinstance(f, Frame) for f in frames)
    assert frames[0].width == 1400  # From mock server default


def test_streaming_session_context_manager(api_client: dropticalAPIClient) -> None:
    """Tests the streaming_session() context manager."""
    received_frames = 0
    with api_client.streaming_session() as frame_stream:
        for frame in frame_stream:
            assert isinstance(frame, Frame)
            received_frames += 1
            if received_frames >= 5:
                break
    assert received_frames == 5
    assert not api_client._is_streaming


def test_opencv_capture_wrapper(mock_server: dict[str, Any]) -> None:
    """Tests the dropticalAPIClientCapture wrapper."""
    with dropticalAPIClientCapture(mock_server["host"], api_port=mock_server["api_port"]) as cap:
        assert cap.isOpened()
        ret, frame = cap.read()
        assert ret is True
        assert isinstance(frame, np.ndarray)
    assert not cap.isOpened()


def test_state_change_production_mode(clean_api_client: dropticalAPIClient) -> None:
    """Tests changing a state on the server (production_mode) and reading it back."""
    # 1. Check initial state (from mock server's default)
    initial_info = clean_api_client.get_machine_info()
    assert initial_info.analysisunit.production_mode is False

    # 2. Change the state to True
    clean_api_client.set_production_mode(True)

    # 3. Read back and verify
    updated_info = clean_api_client.get_machine_info()
    assert updated_info.analysisunit.production_mode is True


def test_trigger_single_shot(api_client: dropticalAPIClient) -> None:
    """Tests the single shot action command."""
    settings = SingleShotSettings.default()
    response = api_client.trigger_single_shot(settings)
    assert isinstance(response, SingleShotResponse)
    assert response.value_name == "Default Value"


def test_unknown_command_raises_error(api_client: dropticalAPIClient) -> None:
    """Tests that sending an unknown command raises a DeviceCommandError."""
    with pytest.raises(DeviceCommandError, match="Unknown or unimplemented command"):
        api_client.send_command("this-command-does-not-exist")
