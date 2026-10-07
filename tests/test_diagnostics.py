from pathlib import Path

from core.database import Database
from core.diagnostics import Diagnostics


def test_diagnostics_local_checks(tmp_path: Path):
    db = Database(tmp_path / "data" / "test.db")
    db.initialize()
    # Use a bound local socket so the port check is deterministic.
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        port = sock.getsockname()[1]
        result = Diagnostics(tmp_path, db, "127.0.0.1", port).run("quick")
    finally:
        sock.close()
    assert result["total"] == 6
    assert result["passed"] == 6
