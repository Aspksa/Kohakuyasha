import socket
from pathlib import Path

from core.config import Paths
from core.runtime import RuntimeState, find_free_port, port_is_open


def test_find_free_port():
    port = find_free_port("127.0.0.1", 18710, span=5)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_runtime_snapshot_and_cleanup(tmp_path: Path):
    paths = Paths(tmp_path)
    paths.ensure()
    state = RuntimeState(paths, "0.1.1", port=8710)
    state.persist()
    snap = state.snapshot()
    assert snap["version"] == "0.1.1"
    assert snap["port"] == 8710
    assert paths.runtime_state.exists()
    state.clear_persisted()
    assert not paths.runtime_state.exists()


def test_port_is_open():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        assert port_is_open("127.0.0.1", sock.getsockname()[1])
    finally:
        sock.close()


def test_find_free_port_single_span_fails_when_taken():
    import pytest
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        with pytest.raises(RuntimeError):
            find_free_port("127.0.0.1", sock.getsockname()[1], span=1)
    finally:
        sock.close()
