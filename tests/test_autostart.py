from pathlib import Path

from core.autostart import ensure_instance_marker


def test_instance_marker_is_stable(tmp_path: Path):
    first = ensure_instance_marker(tmp_path)
    assert first
    assert ensure_instance_marker(tmp_path) == first
    assert (tmp_path / ".kohakuyasha-id").read_text(encoding="utf-8").strip() == first
