from pathlib import Path
import socket

from core.database import Database
from core.diagnostics import Diagnostics


def test_diagnostics_does_not_need_to_initialize_database(tmp_path: Path):
    db = Database(tmp_path / "data" / "test.db")
    db.initialize()
    before = db.path.stat().st_mtime_ns
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        result = Diagnostics(tmp_path, db, "127.0.0.1", sock.getsockname()[1]).run("quick")
    finally:
        sock.close()
    assert result["total"] == 6
    assert result["passed"] == 6
    assert db.path.stat().st_mtime_ns == before
