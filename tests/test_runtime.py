import socket
from pathlib import Path

from core.config import Paths
from core.runtime import RuntimeState, find_free_port


def test_find_free_port():
    port = find_free_port("127.0.0.1", 18710, span=5)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_runtime_snapshot(tmp_path: Path):
    state = RuntimeState(Paths(tmp_path), "0.1.0", port=8710)
    snap = state.snapshot()
    assert snap["version"] == "0.1.0"
    assert snap["port"] == 8710
