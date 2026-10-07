import io
import json
import zipfile
from pathlib import Path

import pytest

from core import updater


def make_zip(files: dict[str, str], top: str = "Aspksa-Kohakuyasha-abc1234") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(f"{top}/{name}", content)
    return buf.getvalue()


BASE = {"VERSION": "0.9.0\n", "main.py": "print('new')\n", "launcher.pyw": "# new\n", "core/__init__.py": "", "core/x.py": "x = 2\n", "README.md": "new readme"}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "app"
    (r / "core").mkdir(parents=True)
    (r / "data").mkdir()
    (r / "logs").mkdir()
    (r / "VERSION").write_text("0.8.0\n")
    (r / "main.py").write_text("print('old')\n")
    (r / "launcher.pyw").write_text("# old\n")
    (r / "core" / "__init__.py").write_text("")
    (r / "core" / "x.py").write_text("x = 1\n")
    (r / "core" / "legacy.py").write_text("legacy\n")
    (r / "data" / "kohakuyasha.db").write_text("DB")
    (r / "data" / "secrets.json").write_text('{"api_key": "k"}')
    (r / ".kohakuyasha-id").write_text("id-123")
    return r


def test_version_compare_and_settings_validation():
    assert updater.is_newer("0.9.0", "0.8.12") and updater.is_newer("v1.0.0", "0.99.99")
    assert not updater.is_newer("0.8.0", "0.8.0") and not updater.is_newer("garbage", "0.8.0") and not updater.is_newer("0.9.0", "garbage")
    s = updater.validate_settings({"repo": "evil repo; rm -rf", "branch": "../../x", "auto_check": "yes"})
    assert (s.repo, s.branch, s.auto_check) == ("Aspksa/Kohakuyasha", "main", True)
    s = updater.validate_settings({"repo": "me/my-repo.git", "branch": "release/1.x", "auto_check": False})
    assert (s.repo, s.branch, s.auto_check) == ("me/my-repo.git", "release/1.x", False)


def test_release_notes_only_newer_entries():
    log = "\n".join(json.dumps(x) for x in [
        {"version": "0.7.0", "summary": "old"}, {"version": "0.8.0", "summary": "current"},
        {"version": "0.9.0", "summary": "new one", "date": "2026-10-08"}, {"version": "0.10.0", "summary": "newest"}]) + "\nnot json\n"
    notes = updater.release_notes(log, "0.8.0")
    assert [n["version"] for n in notes] == ["0.10.0", "0.9.0"]


def test_check_uses_remote_version_and_notes(monkeypatch):
    def fake_text(repo, branch, path, token, limit=0):
        assert (repo, branch) == ("a/b", "main")
        return "0.9.0\n" if path == "VERSION" else json.dumps({"version": "0.9.0", "summary": "feature"}) + "\n"

    monkeypatch.setattr(updater, "fetch_text", fake_text)
    monkeypatch.setattr(updater, "fetch_commit", lambda *a: {"sha": "abc1234", "date": "d"})
    info = updater.check("a/b", "main", "", "0.8.0")
    assert info["newer"] is True and info["remote"] == "0.9.0" and info["sha"] == "abc1234" and info["notes"][0]["summary"] == "feature"
    monkeypatch.setattr(updater, "fetch_text", lambda *a, **k: "not a version")
    with pytest.raises(updater.UpdateError):
        updater.check("a/b", "main", "", "0.8.0")


def test_read_zip_filters_and_validates():
    files = updater.read_zip(make_zip({**BASE, "data/evil.db": "x", ".github/ci.yml": "x", "tests/t.py": "x", ".kohakuyasha-id": "x", "logs/a.log": "x"}))
    assert set(files) == set(BASE)  # protected and skipped paths never reach the installer
    for bad in ({"VERSION": "0.9.0"}, {**BASE, "VERSION": "oops"}):
        with pytest.raises(updater.UpdateError):
            updater.read_zip(make_zip(bad))
    with pytest.raises(updater.UpdateError):
        updater.read_zip(b"not a zip")


def test_read_zip_rejects_path_traversal():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in BASE.items():
            z.writestr(f"top/{name}", content)
        z.writestr("top/../../evil.py", "boom")
    with pytest.raises(updater.UpdateError):
        updater.read_zip(buf.getvalue())


def test_apply_preserves_user_data_backs_up_and_rolls_back(root: Path):
    files = updater.read_zip(make_zip(BASE))
    result = updater.apply(root, files, "0.8.0")
    assert result["version"] == "0.9.0" and result["changed"] >= 3 and result["added"] == 1  # README.md is new
    assert (root / "VERSION").read_text() == "0.9.0\n" and (root / "core" / "x.py").read_text() == "x = 2\n"
    assert (root / "data" / "kohakuyasha.db").read_text() == "DB" and (root / "data" / "secrets.json").exists()
    assert (root / ".kohakuyasha-id").read_text() == "id-123"
    assert (root / "core" / "legacy.py").exists()  # first update has no manifest, so nothing is deleted
    assert not list(root.rglob("*.kohaku-new"))
    backups = updater.list_backups(root)
    assert backups and backups[0]["from"] == "0.8.0" and backups[0]["to"] == "0.9.0"

    # second update: files dropped by the new release are removed (and backed up), files kept stay
    files2 = updater.read_zip(make_zip({**BASE, "VERSION": "1.0.0\n"}))
    del files2["core/x.py"]
    result2 = updater.apply(root, files2, "0.9.0")
    assert result2["removed"] == 1 and not (root / "core" / "x.py").exists() and (root / "core" / "legacy.py").exists()

    rb = updater.rollback(root)
    assert rb["version"] == "0.9.0" and (root / "core" / "x.py").read_text() == "x = 2\n" and (root / "VERSION").read_text() == "0.9.0\n"
    rb = updater.rollback(root)
    assert rb["version"] == "0.8.0" and (root / "VERSION").read_text() == "0.8.0\n" and (root / "core" / "x.py").read_text() == "x = 1\n"
    assert not (root / "README.md").exists()  # a file added by the update disappears on rollback
    assert (root / "data" / "kohakuyasha.db").read_text() == "DB"
    with pytest.raises(updater.UpdateError):
        updater.rollback(root)


def test_failed_apply_is_undone(root: Path, monkeypatch):
    files = updater.read_zip(make_zip(BASE))
    real_replace, calls = updater.os.replace, {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(updater.os, "replace", flaky)
    with pytest.raises(OSError):
        updater.apply(root, files, "0.8.0")
    monkeypatch.undo()
    assert (root / "VERSION").read_text() == "0.8.0\n" and (root / "main.py").read_text() == "print('old')\n" and (root / "core" / "x.py").read_text() == "x = 1\n"
    assert not (root / "README.md").exists()


def test_backups_are_pruned(root: Path):
    for i in range(updater.KEEP_BACKUPS + 2):
        files = updater.read_zip(make_zip({**BASE, "VERSION": f"0.9.{i}\n", "main.py": f"print({i})\n"}))
        updater.apply(root, files, f"0.8.{i}")
    assert len(updater.list_backups(root)) == updater.KEEP_BACKUPS


def test_relaunch_is_windows_only_noop_elsewhere(root: Path):
    import os
    if os.name != "nt":
        assert updater.relaunch(root) is False
