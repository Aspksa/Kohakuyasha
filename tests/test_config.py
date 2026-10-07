from pathlib import Path

from core.config import ConfigStore, Paths


def test_config_roundtrip_and_validation(tmp_path: Path):
    store = ConfigStore(Paths(tmp_path))
    settings = store.load()
    settings.port = "not-a-port"  # type: ignore[assignment]
    settings.host = "0.0.0.0"
    store.save(settings)
    loaded = store.load()
    assert loaded.port == 8710
    assert loaded.host == "127.0.0.1"


def test_corrupt_config_is_backed_up_and_rewritten(tmp_path: Path):
    paths = Paths(tmp_path)
    paths.ensure()
    paths.settings.write_text("{broken", encoding="utf-8")
    store = ConfigStore(paths)
    loaded = store.load()
    assert loaded.port == 8710
    assert list(paths.data.glob("settings.corrupt-*.json"))
    assert '"port": 8710' in paths.settings.read_text(encoding="utf-8")
    assert store.warnings
