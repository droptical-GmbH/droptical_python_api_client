"""Shared pytest fixtures for the client's INTEGRATION tests.

These run against a droptical device or test backend reachable at
``DROPTICAL_TEST_HOST`` / ``DROPTICAL_TEST_PORT`` (default ``127.0.0.1:80``). If no backend is
reachable, the whole integration suite skips — the backend-free unit tests in ``test_models.py``
still run.

The TCP image/value streams are served by the analysis unit (ports 51222/51223), not the REST
API; the ``streams`` fixture skips stream tests when those ports are not being served.
"""

from __future__ import annotations

import os
import socket
import time

import pytest
import requests

from droptical_api_client import dropticalAPIClient

HOST = os.environ.get("DROPTICAL_TEST_HOST", "127.0.0.1")
PORT = int(os.environ.get("DROPTICAL_TEST_PORT", "80"))
BASE = f"http://{HOST}:{PORT}/api/v2"

TCP_STREAM_PORT = 51222
VALUE_STREAM_PORT = 51223


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def backend() -> str:
    """Require a reachable backend; skip the whole integration suite otherwise.

    Establishes ONE clean baseline per session via factory-reset (not per test — the tests are
    self-contained). WARNING: this wipes measurement data and resets settings, so only ever point
    ``DROPTICAL_TEST_HOST/PORT`` at a test backend, never a production device."""
    try:
        if not requests.get(f"{BASE}/infos", timeout=3).ok:
            pytest.skip(f"backend at {BASE} did not return OK")
    except requests.RequestException:
        pytest.skip(f"no backend reachable at {BASE} (set DROPTICAL_TEST_HOST/PORT)")
    c = dropticalAPIClient()
    c.connect(HOST, api_port=PORT)
    serial = c.get_infos().analysisunit.serial_number if c.get_infos().analysisunit else None
    if serial:
        c.factory_reset(serial)  # session baseline
    return BASE


@pytest.fixture
def client(backend: str) -> dropticalAPIClient:
    """A client connected to the live backend. No per-test reset — integration tests are written
    to be self-contained (create their own data and assert on it), tolerant of pre-existing state."""
    c = dropticalAPIClient()
    c.connect(HOST, api_port=PORT)
    return c


@pytest.fixture(autouse=True)
def _ensure_idle_between_tests(client: dropticalAPIClient):
    """The analysis unit runs ONE measurement at a time (a second create → 500 "already in
    progress"). After each test, if a measurement was left running (an async create that didn't
    finish), abort it and wait for idle, so the next test's create is never rejected."""
    yield
    try:
        infos = client.get_infos()
        if not infos.system or infos.system.status == "idle":
            return
        for m in client.list_measurements(per_page=50).data:
            if m.status in ("in_progress", "waiting"):
                try:
                    client.abort()
                except Exception:  # noqa: BLE001
                    pass
        for _ in range(60):  # wait up to ~3s for the unit to report idle again
            s = client.get_infos().system
            if s and s.status == "idle":
                break
            time.sleep(0.05)
    except Exception:  # noqa: BLE001 — cleanup must never fail a test
        pass


@pytest.fixture(scope="session")
def streams(backend: str) -> None:
    """Skip a test that needs EITHER stream (e.g. the example-script tests that may touch image
    and/or value) unless at least one of the image/value stream ports is served."""
    if not (_port_open(HOST, TCP_STREAM_PORT) or _port_open(HOST, VALUE_STREAM_PORT)):
        pytest.skip(f"no TCP stream served on {HOST}:{TCP_STREAM_PORT}/{VALUE_STREAM_PORT}")


@pytest.fixture(scope="session")
def image_stream_served(backend: str) -> None:
    """Skip an IMAGE-stream test unless the image stream port is actually served."""
    if not _port_open(HOST, TCP_STREAM_PORT):
        pytest.skip(f"image stream not served on {HOST}:{TCP_STREAM_PORT}")


@pytest.fixture(scope="session")
def value_stream_served(backend: str) -> None:
    """Skip a VALUE-stream test unless the value stream port is actually served — so a closed
    value port SKIPS honestly instead of failing with 'no ValueMessage received' (the old combined
    `streams` fixture used OR, so it ran the value test even when only the image port was open)."""
    if not _port_open(HOST, VALUE_STREAM_PORT):
        pytest.skip(f"value stream not served on {HOST}:{VALUE_STREAM_PORT}")
