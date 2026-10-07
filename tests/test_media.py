import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from core import media


def png_b64(size=(400, 600), color=(200, 50, 50), mode="RGB") -> str:
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, "PNG")
    return base64.b64encode(out.getvalue()).decode()


def test_decode_and_open_rejects_garbage():
    with pytest.raises(media.MediaError):
        media.decode_upload("")
    with pytest.raises(media.MediaError):
        media.decode_upload("!!!not base64!!!")
    with pytest.raises(media.MediaError):
        media.open_image(b"<script>alert(1)</script>")
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    with pytest.raises(media.MediaError):
        media.open_image(svg)
    img = media.open_image(media.decode_upload("data:image/png;base64," + png_b64()))
    assert img.size == (400, 600)


def test_encode_reencodes_and_limits_size():
    img = media.open_image(media.decode_upload(png_b64((3000, 1500))))
    data, ext = media.encode(img, 1280)
    assert ext == "jpg" and Image.open(io.BytesIO(data)).size[0] == 1280
    data, ext = media.encode(media.open_image(media.decode_upload(png_b64((50, 50), (1, 2, 3, 128), "RGBA"))), 1280)
    assert ext == "png"


def test_render_face_is_square_and_clamps():
    img = media.open_image(media.decode_upload(png_b64((400, 800))))
    for args in [(1, 0, 0), (9, 5, -5), (2.5, -1, 1)]:
        out = Image.open(io.BytesIO(media.render_face(img, *args, size=128)))
        assert out.size == (128, 128)


def test_store_only_serves_safe_names(tmp_path: Path):
    store = media.MediaStore(tmp_path / "media")
    store.save("face-abc12345-0a.png", b"x")
    assert store.read("face-abc12345-0a.png") == b"x"
    for bad in ("../secrets.json", "a/b.png", "x.exe", "..png", "secrets.json"):
        assert store.path(bad) is None
        with pytest.raises(media.MediaError):
            store.save(bad, b"x")
