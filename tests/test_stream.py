"""Tests for the CSP v2 TCP streams (against a live backend when the streams are served).

Covers the two independent streams introduced in protocol v2:
  * the CSP-binary IMAGE stream (new frame header + optional per-frame metadata),
  * the raw-JSON VALUE stream (measurement results pushed on every trigger).

Every socket-touching test is bounded by a thread + join(timeout=...) so a missing
frame/value FAILS FAST instead of hanging the suite.
"""

from __future__ import annotations

import json
import logging
import socket
import struct
import threading
import time

import requests

from droptical_api_client import ValueMessage, dropticalAPIClient
from droptical_api_client.client import CSP_PROTOCOL_MAJOR, PROTOCOL_HEADER_FORMAT, PROTOCOL_MAGIC_BYTES
from tests.conftest import BASE  # backend target (env-configurable; default 127.0.0.1:80)

# --- value-stream JSON carving (pure unit test, no sockets) ------------------


def test_carve_value_messages_back_to_back_and_split() -> None:
    """The buffered carver must handle several docs in one chunk AND a doc split
    across chunks, keeping the incomplete tail for the next chunk."""
    decoder = json.JSONDecoder()
    d1 = json.dumps({"id": 1, "frameCount": 1, "frames": []})
    d2 = json.dumps({"id": 2, "frameCount": 1, "frames": []})

    # Two complete documents back-to-back in one buffer -> both carved, no tail.
    got: list[ValueMessage] = []
    tail = dropticalAPIClient._carve_value_messages(d1 + d2, decoder, got.append)
    assert [m.id for m in got] == [1, 2]
    assert tail == ""

    # One document split across two chunks -> nothing until it is complete.
    got.clear()
    cut = len(d1) // 2
    tail = dropticalAPIClient._carve_value_messages(d1[:cut], decoder, got.append)
    assert got == [] and tail == d1[:cut]
    tail = dropticalAPIClient._carve_value_messages(tail + d1[cut:], decoder, got.append)
    assert len(got) == 1 and got[0].id == 1 and tail == ""


# --- value stream (integration) ---------------------------------------------


def test_value_stream_receives_measurement_push(client: dropticalAPIClient, value_stream_served: None) -> None:
    """Triggering a measurement pushes exactly one ValueMessage on the value stream.

    The value stream only emits in lab/production mode (streaming mode is silent), so put the unit
    in lab mode first — mirroring the image-stream test, which switches modes to see metadata.
    """
    client.set_lab_mode()
    received: list[ValueMessage] = []

    def consume() -> None:
        try:
            for msg in client.value_stream():
                received.append(msg)
                break
        except Exception:  # noqa: BLE001 - surfaced via the assertion below
            pass

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    time.sleep(0.8)  # let the listener connect before the push (no backlog for late joiners)
    client.trigger_singleshot()
    t.join(timeout=6)
    client.stop_value_stream()

    assert received, "no ValueMessage received on the value stream"
    m = received[0]
    assert isinstance(m, ValueMessage)
    assert m.frames and m.frames[0].rois and m.frames[0].rois[0].results
    assert m.frames[0].rois[0].results[0].feature_id == 1


# --- image stream: metadata absent in streaming, present in production -------


def test_image_stream_metadata_toggle(client: dropticalAPIClient, image_stream_served: None) -> None:
    """A streaming-mode frame carries no metadata (metadata_len == 0 -> None); after
    switching to production mode the frames carry a parsed ValueMessage.

    The caller sets the device mode explicitly: streaming first (image stream on, no
    values), then production (values attached)."""
    requests.post(f"{BASE}/machine/mode/streaming", timeout=2)
    out: dict[str, object] = {"first_meta": "unset", "with_meta": None}

    def consume() -> None:
        try:
            for i, frame in enumerate(client.image_stream()):
                if i == 0:
                    out["first_meta"] = frame.metadata  # streaming mode -> expected None
                    requests.post(f"{BASE}/machine/mode/production", timeout=2)
                elif frame.metadata is not None:
                    out["with_meta"] = frame
                    break
                if i > 150:
                    break
        except Exception:  # noqa: BLE001 - surfaced via the assertions below
            pass

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    t.join(timeout=10)
    client.stop_image_stream()

    assert out["first_meta"] is None, "a streaming-mode frame must have no metadata"
    frame = out["with_meta"]
    assert frame is not None, "no frame carried metadata after switching to production mode"
    assert isinstance(frame.metadata, ValueMessage)
    assert frame.metadata.frames and frame.metadata.frames[0].rois
    assert frame.raw_data, "the image payload must still be present alongside metadata"


# --- protocol-major validation ----------------------------------------------


def test_major_version_mismatch_rejected(caplog) -> None:  # noqa: ANN001 - pytest fixture
    """A stream announcing a different CSP major version is rejected: no frames are
    delivered and the listener terminates (does not hang)."""
    assert CSP_PROTOCOL_MAJOR == 2
    proto = struct.pack(PROTOCOL_HEADER_FORMAT, PROTOCOL_MAGIC_BYTES, 1, 0, 1)  # major=1

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    fake_port = server.getsockname()[1]

    def serve_once() -> None:
        try:
            conn, _ = server.accept()
            conn.sendall(proto)
            time.sleep(0.3)
            conn.close()
        except OSError:
            pass
        finally:
            server.close()

    threading.Thread(target=serve_once, daemon=True).start()

    c = dropticalAPIClient()
    c._ip_address = "127.0.0.1"  # _listen_for_image_frames connects here; no REST needed
    got: list[object] = []

    with caplog.at_level(logging.WARNING):
        t = threading.Thread(target=lambda: c._listen_for_image_frames(fake_port, got.append), daemon=True)
        t.start()
        t.join(timeout=5)

    assert not t.is_alive(), "listener did not terminate on an unsupported major version"
    assert got == [], "no frames should be delivered on a protocol-major mismatch"
    assert any("major" in r.getMessage().lower() for r in caplog.records), "expected a logged ProtocolError about the major version"
