"""Smoke tests that actually launch the shipped examples and assert they run
without raising (clean exit / no traceback) — a guard against an example
silently breaking, e.g. after an API rename.

Scope:
  * ``general/rest`` — run for real against a live backend (the ``backend`` fixture).
  * ``general/burst`` & ``live_stream`` — need the TCP streams (the ``streams`` fixture); they
                      skip when the streams are not being served (see conftest).
  * ``cv2/*``       — a ``--help`` smoke only: it exercises the imports + CLI
                      without a display or the stream (the windowed loop can't run
                      head-less).
  * ``gui/main.py`` — constructed head-less (``QT_QPA_PLATFORM=offscreen``).

The backend target comes from ``DROPTICAL_TEST_HOST`` / ``DROPTICAL_TEST_PORT`` (see conftest).
The cv2/gui tests are network-free and skip automatically when their optional extra
(opencv / PySide6) is absent.
"""

from __future__ import annotations

import os
import pathlib
import signal
import subprocess
import sys
import time

import pytest

from tests.conftest import HOST
from tests.conftest import PORT as _PORT

REPO = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"
_TRACEBACK = "Traceback (most recent call last)"

# The backend target (from conftest; env-configurable, default 127.0.0.1:80). Passed to each
# spawned example so it talks to the live backend. The `backend`/`streams` fixtures gate them.
PORT = str(_PORT)


def _run(*path_parts: str, cwd: pathlib.Path, timeout: float, args: tuple[str, ...] = ()) -> subprocess.CompletedProcess[str]:
    """Run an example by file path (each example bootstraps ``sys.path`` itself)."""
    return subprocess.run(
        [sys.executable, str(EXAMPLES.joinpath(*path_parts)), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# --- general examples (real run against a live backend) ---------------------------


def test_rest_example_runs_clean(backend: str, tmp_path: pathlib.Path) -> None:
    proc = _run("general", "rest_example.py", cwd=tmp_path, timeout=60, args=(HOST, PORT))
    assert proc.returncode == 0, proc.stderr
    assert _TRACEBACK not in proc.stderr, proc.stderr
    assert "Unit status:" in proc.stdout, proc.stdout


def test_burst_capture_example_runs_clean(streams: None, tmp_path: pathlib.Path) -> None:
    pytest.importorskip("PIL")  # frame.save() needs Pillow (the 'image' extra)
    proc = _run("general", "burst_capture_example.py", cwd=tmp_path, timeout=120, args=(HOST, PORT))
    assert proc.returncode == 0, proc.stderr
    assert _TRACEBACK not in proc.stderr, proc.stderr
    assert (tmp_path / "burst_session").is_dir(), "burst example produced no images"


def test_live_stream_example_streams_without_error(streams: None, tmp_path: pathlib.Path) -> None:
    """The live stream is infinite by design: let it connect and pull a few frames,
    then send SIGINT (the same signal CTRL+C raises) and assert a clean shutdown."""
    proc = subprocess.Popen(
        [sys.executable, str(EXAMPLES / "general" / "live_stream_example.py"), HOST, PORT],
        cwd=str(tmp_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(4)  # connect + receive a few frames
    finally:
        proc.send_signal(signal.SIGINT)  # the example catches this as KeyboardInterrupt
    try:
        out, err = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, err = proc.communicate()
        pytest.fail(f"live_stream_example did not stop on interrupt:\n{err}")
    assert _TRACEBACK not in err, err
    assert "Live frame received" in out, f"no frames received\nSTDOUT:\n{out}\nSTDERR:\n{err}"


# --- cv2 examples (import + CLI smoke; no display / no stream) ---------------


@pytest.mark.parametrize("script", ["cv2_capture_example.py", "cv2_droplet_detection_example.py"])
def test_cv2_example_imports_and_parses(script: str) -> None:
    """``-h`` exercises the top-level imports (incl. the client symbols) and the
    argparse CLI, then exits 0 before any window/stream code — a head-less-safe check."""
    pytest.importorskip("cv2")  # the 'opencv' extra
    proc = _run("cv2", script, cwd=REPO, timeout=60, args=("-h",))
    assert proc.returncode == 0, proc.stderr
    assert _TRACEBACK not in proc.stderr, proc.stderr
    assert "usage" in proc.stdout.lower(), proc.stdout


# --- PyQt GUI (head-less construction) --------------------------------------


def test_gui_example_constructs_headless() -> None:
    pytest.importorskip("PySide6")  # the 'gui' extra
    driver = (
        "import sys, os;"
        "sys.path.insert(0, os.path.join('examples', 'gui'));"
        "from PySide6.QtWidgets import QApplication;"
        "import main;"
        "app = QApplication([]);"
        "main.MainWindow();"
        "print('GUI_OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", driver],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert proc.returncode == 0, proc.stderr
    assert _TRACEBACK not in proc.stderr, proc.stderr
    assert "GUI_OK" in proc.stdout, proc.stdout
