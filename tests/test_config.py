from pathlib import Path
from core.config import ConfigStore, Paths, Settings


def test_config_roundtrip(tmp_path: Path):
    paths = Paths(tmp_path)
    store = ConfigStore(paths)
    settings = store.load()
    assert settings.host == "127.0.0.1"
    settings.port = 9123
    store.save(settings)
    assert store.load().port == 9123
