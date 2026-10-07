import os
from pathlib import Path

import pytest

from core import disk
from core.disk import DiskError, DiskStore


@pytest.fixture()
def store(tmp_path: Path) -> DiskStore:
    s = DiskStore(tmp_path / "disk"); s.ensure()
    return s


@pytest.mark.parametrize("bad", ["../x", "a/../../x", "C:/Windows", "a/b:c", "a\\..\\x", "CON", "nul.txt", "x" * 200, "a/" * 20, "name.", "q?"])
def test_bad_paths_are_rejected(store, bad):
    with pytest.raises(DiskError):
        store.resolve(bad, must_exist=False)


def test_leading_slash_means_inside_the_disk(store):
    assert store.resolve("/etc/passwd", must_exist=False) == store.files / "etc" / "passwd"


def test_symlink_escape_is_blocked(store, tmp_path):
    outside = tmp_path / "secret.txt"; outside.write_text("s")
    try:
        os.symlink(outside, store.files / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(DiskError) as e:
        store.file_for_read("link.txt")
    assert e.value.status == 403
    assert all(i["name"] != "link.txt" for i in store.list("")["items"])


def test_folders_upload_move_search_and_listing(store):
    store.mkdir("Документы"); store.mkdir("Документы/Фото")
    with pytest.raises(DiskError) as e:
        store.mkdir("Документы")
    assert e.value.status == 409
    entry = store.save_upload("Документы", "отчёт.txt", iter([b"abc", b"def"]), 100)
    assert entry["name"] == "отчёт.txt" and entry["size"] == 6 and entry["kind"] == "text" and entry["inline"]
    assert store.save_upload("Документы", "отчёт.txt", iter([b"x"]), 100)["name"] == "отчёт (2).txt"  # never overwrites
    listing = store.list("Документы")
    assert [i["name"] for i in listing["items"]] == ["Фото", "отчёт (2).txt", "отчёт.txt"] and listing["crumbs"][0]["name"] == "Документы"
    store.move("Документы/отчёт.txt", "Документы/Фото/итог.txt")
    assert [i["path"] for i in store.search("итог")] == ["Документы/Фото/итог.txt"]
    with pytest.raises(DiskError):
        store.move("Документы", "Документы/Фото/Документы")  # into itself
    with pytest.raises(DiskError):
        store.move("Документы/Фото/итог.txt", "Документы/отчёт (2).txt")  # name taken
    store.move("Документы/Фото/итог.txt", "Документы/Фото/Итог.txt")  # case-only rename is fine


def test_upload_limit_cleans_partial_file(store):
    with pytest.raises(DiskError) as e:
        store.save_upload("", "big.bin", iter([b"x" * 60, b"x" * 60]), 100)
    assert e.value.status == 413 and list(store.files.iterdir()) == []


def test_trash_restore_purge_and_expiry(store):
    store.mkdir("a"); store.save_upload("a", "f.txt", iter([b"hi"]), 10)
    meta = store.delete("a/f.txt")
    assert not (store.files / "a" / "f.txt").exists() and store.trash_list()[0]["name"] == "f.txt"
    store.save_upload("a", "f.txt", iter([b"new"]), 10)  # name reused meanwhile
    restored = store.restore(meta["id"])
    assert restored["name"] == "f (2).txt" and (store.files / "a" / "f (2).txt").read_bytes() == b"hi"
    folder = store.delete("a")
    assert store.restore(folder["id"])["name"] == "a"
    third = store.delete("a/f.txt")
    store.purge(third["id"]); assert store.trash_list() == []
    with pytest.raises(DiskError):
        store.purge("../../etc")
    old = store.delete("a/f (2).txt")
    import json
    mp = store.trash / old["id"] / "meta.json"
    m = json.loads(mp.read_text()); m["deleted_at"] = "2020-01-01T00:00:00+00:00"; mp.write_text(json.dumps(m))
    assert store.trash_list(30) == [] and not (store.trash / old["id"]).exists()
    with pytest.raises(DiskError):
        store.delete("")


def test_usage_and_settings_validation(store):
    store.save_upload("", "a.bin", iter([b"12345"]), 10)
    assert store.usage()["bytes"] == 5 and store.usage()["files"] == 1
    assert disk.validate_settings({"max_file_mb": 99999, "trash_days": "x"}) == {"max_file_mb": 8192, "trash_days": 30}
