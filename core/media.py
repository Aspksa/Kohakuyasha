from __future__ import annotations

import base64
import binascii
import hashlib
import io
from pathlib import Path

from PIL import Image, ImageOps

from .prefs import MEDIA_NAME_RE

MAX_UPLOAD_BYTES = 6_000_000
MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}


class MediaError(ValueError):
    """Human-readable (Russian) upload problem, safe to show in the UI."""


def decode_upload(data: object) -> bytes:
    if not isinstance(data, str) or not data:
        raise MediaError("Файл не получен.")
    if data.startswith("data:"):
        data = data.partition(",")[2]
    if len(data) > MAX_UPLOAD_BYTES * 4 // 3 + 8:
        raise MediaError("Файл слишком большой (максимум 6 МБ).")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise MediaError("Файл повреждён.") from None
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise MediaError("Файл слишком большой (максимум 6 МБ).")
    return raw


def open_image(raw: bytes) -> Image.Image:
    """Decode and re-encode later: this strips metadata and rejects non-images."""
    try:
        probe = Image.open(io.BytesIO(raw))
        if probe.format not in ALLOWED_FORMATS:
            raise MediaError("Поддерживаются PNG, JPEG, WebP и GIF.")
        probe.verify()
        img = Image.open(io.BytesIO(raw))
        img.seek(0)
        img = ImageOps.exif_transpose(img)
        img.load()
    except MediaError:
        raise
    except Exception:
        raise MediaError("Не удалось прочитать изображение.") from None
    return img


def encode(img: Image.Image, max_side: int, *, force_jpeg: bool = False, quality: int = 90) -> tuple[bytes, str]:
    img = img.copy()
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    out = io.BytesIO()
    if has_alpha and not force_jpeg:
        img.convert("RGBA").save(out, "PNG", optimize=True)
        return out.getvalue(), "png"
    img.convert("RGB").save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue(), "jpg"


def render_face(img: Image.Image, zoom: float, x: float, y: float, size: int = 512) -> bytes:
    """Square crop: zoom >= 1 shrinks the crop window, x/y in [-1, 1] slide it across the image."""
    zoom = min(max(float(zoom), 1.0), 4.0)
    x = min(max(float(x), -1.0), 1.0)
    y = min(max(float(y), -1.0), 1.0)
    w, h = img.size
    side = min(w, h) / zoom
    left = (w - side) / 2 + x * (w - side) / 2
    top = (h - side) / 2 + y * (h - side) / 2
    crop = img.convert("RGBA").crop((round(left), round(top), round(left + side), round(top + side)))
    crop = crop.resize((size, size), Image.LANCZOS)
    out = io.BytesIO()
    crop.save(out, "PNG", optimize=True)
    return out.getvalue()


def short_hash(raw: bytes, length: int = 12) -> str:
    return hashlib.sha256(raw).hexdigest()[:length]


class MediaStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def save(self, name: str, raw: bytes) -> str:
        if not MEDIA_NAME_RE.match(name):
            raise MediaError("Недопустимое имя файла.")
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / name
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(raw)
        tmp.replace(target)
        return name

    def path(self, name: str) -> Path | None:
        if not MEDIA_NAME_RE.match(name):
            return None
        target = self.root / name
        return target if target.is_file() else None

    def read(self, name: str) -> bytes | None:
        path = self.path(name)
        return path.read_bytes() if path else None

    def delete(self, name: str) -> None:
        if name and MEDIA_NAME_RE.match(name):
            (self.root / name).unlink(missing_ok=True)
