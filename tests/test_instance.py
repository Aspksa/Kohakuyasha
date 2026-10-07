import json
from pathlib import Path

from core import updater
from core.config import Paths
from core.instance import STOPPING, InstanceLock, acquire_or_wait, holder_is_healthy


class FakeLock:
    def __init__(self, free_after: int) -> None:
        self.calls, self.free_after = 0, free_after

    def acquire(self) -> bool:
        self.calls += 1
        return self.calls > self.free_after


def waiter(lock, paths, healthy, timeout=10.0):
    ticks = {"t": 0.0}
    slept = []

    def sleep(s):
        slept.append(s)
        ticks["t"] += s

    result = acquire_or_wait(lock, paths, timeout=timeout, interval=0.5, healthy=healthy, sleep=sleep, clock=lambda: ticks["t"])
    return result, slept


def test_waits_for_a_shutting_down_instance_instead_of_giving_up(tmp_path: Path):
    paths = Paths(tmp_path)
    result, slept = waiter(FakeLock(free_after=6), paths, healthy=lambda p: False)  # lock released after ~3 s
    assert result == "acquired" and len(slept) == 6


def test_a_healthy_running_instance_is_reported_immediately(tmp_path: Path):
    paths = Paths(tmp_path)
    result, slept = waiter(FakeLock(free_after=99), paths, healthy=lambda p: True)
    assert result == "running" and slept == []


def test_gives_up_after_the_timeout(tmp_path: Path):
    result, slept = waiter(FakeLock(free_after=10**6), Paths(tmp_path), healthy=lambda p: False, timeout=3.0)
    assert result == "timeout" and sum(slept) >= 3.0


def test_holder_health_uses_runtime_state(tmp_path: Path, monkeypatch):
    import os
    import socket
    paths = Paths(tmp_path)
    paths.ensure()
    assert holder_is_healthy(paths) is False  # no runtime.json
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        paths.runtime_state.write_text(json.dumps({"pid": os.getpid(), "port": port, "status": "Наблюдает"}))
        assert holder_is_healthy(paths) is True
        paths.runtime_state.write_text(json.dumps({"pid": os.getpid(), "port": port, "status": STOPPING}))
        assert holder_is_healthy(paths) is False  # shutting down: wait for it instead
        paths.runtime_state.write_text(json.dumps({"pid": 2**22, "port": port, "status": "Наблюдает"}))
        assert holder_is_healthy(paths) is False  # stale file of a dead process
        paths.runtime_state.write_text("garbage")
        assert holder_is_healthy(paths) is False
    finally:
        sock.close()


def test_instance_lock_is_exclusive_and_releases(tmp_path: Path):
    a, b = InstanceLock(tmp_path / "x.lock"), InstanceLock(tmp_path / "x.lock")
    assert a.acquire() is True
    assert b.acquire() is False and b.handle is None  # failed attempts do not keep a handle open
    a.release()
    assert b.acquire() is True
    b.release()


def test_relaunch_script_waits_for_the_pid_and_survives_odd_paths(tmp_path: Path):
    root = tmp_path / "Мой диск' 1"
    script = updater.relaunch_script(root, 4242)
    assert "Wait-Process -Id 4242" in script and "KOHAKUYASHA_RELAUNCH" in script and "relaunch.log" in script
    assert "Мой диск'' 1" in script  # single quotes are doubled for PowerShell literals
    assert script.startswith("try {") and script.rstrip().endswith("}")


def test_batch_files_from_a_zipball_get_crlf():
    from tests.test_updater import BASE, make_zip
    files = updater.read_zip(make_zip({**BASE, "Kohakuyasha.bat": "@echo off\nexit /b 0\n", "scripts/x.cmd": "a\r\nb\n", "core/y.py": "a\nb\n"}))
    assert files["Kohakuyasha.bat"] == b"@echo off\r\nexit /b 0\r\n" and files["scripts/x.cmd"] == b"a\r\nb\r\n"
    assert files["core/y.py"] == b"a\nb\n"  # only batch files are converted
