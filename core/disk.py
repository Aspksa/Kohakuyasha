"""Диск Kohakuyasha: a small local file storage (folders, upload/download, trash) rooted in one directory.

Every user-supplied path is a relative POSIX path that is validated segment by segment and then re-checked
to stay inside the root after resolving symlinks, so nothing outside the storage can be read or written.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator

MAX_NAME = 120
MAX_DEPTH = 12
MAX_PATH = 400
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
DEFAULT_MAX_FILE_MB = 1024
DEFAULT_TRASH_DAYS = 30

# Served inline (preview); everything else is always a download. SVG/HTML are never inline: they can run script.
INLINE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8", ".json": "text/plain; charset=utf-8", ".log": "text/plain; charset=utf-8",
    ".csv": "text/plain; charset=utf-8", ".py": "text/plain; charset=utf-8",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".m4a": "audio/mp4",
    ".mp4": "video/mp4", ".webm": "video/webm", ".pdf": "application/pdf",
}
KINDS = {
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"},
    "text": {".txt", ".md", ".json", ".log", ".csv", ".py", ".js", ".html", ".css", ".xml", ".yml", ".yaml", ".ini"},
    "audio": {".mp3", ".wav", ".ogg", ".m4a", ".flac"},
    "video": {".mp4", ".webm", ".mkv", ".mov", ".avi"},
    "pdf": {".pdf"},
    "archive": {".zip", ".7z", ".rar", ".tar", ".gz"},
    "doc": {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods"},
}


def validate_settings(raw: Any) -> dict[str, int]:
    raw = raw if isinstance(raw, dict) else {}

    def num(key: str, default: int, lo: int, hi: int) -> int:
        v = raw.get(key)
        return min(max(v, lo), hi) if isinstance(v, int) and not isinstance(v, bool) else default

    return {"max_file_mb": num("max_file_mb", DEFAULT_MAX_FILE_MB, 1, 8192), "trash_days": num("trash_days", DEFAULT_TRASH_DAYS, 1, 365)}


class DiskError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    for kind, exts in KINDS.items():
        if ext in exts:
            return kind
    return "file"


def clean_name(name: Any) -> str:
    if not isinstance(name, str):
        raise DiskError("Некорректное имя.")
    name = name.strip()
    if not name or name in {".", ".."} or len(name) > MAX_NAME or BAD_CHARS.search(name) or name.endswith("."):
        raise DiskError("Некорректное имя: без символов < > : \" / \\ | ? *, не длиннее 120 знаков.")
    if name.split(".")[0].upper() in RESERVED:
        raise DiskError("Это имя зарезервировано системой Windows.")
    return name


def clean_rel(path: Any) -> list[str]:
    """'a/b/c' -> ['a','b','c']; '' or '/' -> []. Rejects traversal, absolute paths, drive letters and odd names."""
    if path is None:
        return []
    if not isinstance(path, str) or len(path) > MAX_PATH:
        raise DiskError("Некорректный путь.")
    parts = [p for p in path.replace("\\", "/").split("/") if p != ""]
    if len(parts) > MAX_DEPTH:
        raise DiskError("Слишком глубокая вложенность.")
    return [clean_name(p) for p in parts]


class DiskStore:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.files = base / "files"
        self.trash = base / "trash"

    def ensure(self) -> None:
        self.files.mkdir(parents=True, exist_ok=True)
        self.trash.mkdir(parents=True, exist_ok=True)

    # ---------- path safety ----------
    def resolve(self, rel: Any, *, must_exist: bool = True) -> Path:
        self.ensure()
        parts = clean_rel(rel)
        target = self.files.joinpath(*parts) if parts else self.files
        root = self.files.resolve()
        real = target.resolve()
        if real != root and root not in real.parents:
            raise DiskError("Путь вне диска.", 403)
        if must_exist and not target.exists():
            raise DiskError("Не найдено.", 404)
        return target

    @staticmethod
    def rel_of(parts: list[str]) -> str:
        return "/".join(parts)

    def _entry(self, p: Path, parent: list[str]) -> dict[str, Any]:
        st = p.stat()
        is_dir = p.is_dir()
        return {
            "name": p.name, "path": self.rel_of([*parent, p.name]), "dir": is_dir,
            "size": 0 if is_dir else st.st_size, "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
            "kind": "folder" if is_dir else kind_of(p.name), "inline": (not is_dir) and p.suffix.lower() in INLINE_TYPES,
        }

    # ---------- browsing ----------
    def list(self, rel: Any = "") -> dict[str, Any]:
        d = self.resolve(rel)
        if not d.is_dir():
            raise DiskError("Это не папка.")
        parts = clean_rel(rel)
        items = []
        for p in d.iterdir():
            if p.is_symlink() or p.name.startswith(".upload-"):
                continue
            try:
                items.append(self._entry(p, parts))
            except OSError:
                continue
        items.sort(key=lambda e: (not e["dir"], e["name"].lower()))
        return {"path": self.rel_of(parts), "crumbs": [{"name": n, "path": self.rel_of(parts[: i + 1])} for i, n in enumerate(parts)], "items": items}

    def search(self, query: str, limit: int = 100) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return []
        self.ensure()
        found: list[dict[str, Any]] = []
        for dirpath, dirnames, filenames in os.walk(self.files):
            dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
            for name in [*dirnames, *filenames]:
                if q in name.lower():
                    p = Path(dirpath) / name
                    if p.is_symlink():
                        continue
                    parent = list(p.relative_to(self.files).parts[:-1])
                    try:
                        found.append(self._entry(p, parent))
                    except OSError:
                        continue
                    if len(found) >= limit:
                        return found
        return found

    def usage(self) -> dict[str, int]:
        self.ensure()
        files = total = 0
        for dirpath, _, filenames in os.walk(self.files):
            for f in filenames:
                try:
                    total += (Path(dirpath) / f).stat().st_size
                    files += 1
                except OSError:
                    pass
        trash_bytes = 0
        for item in self.trash.glob("*/payload*"):
            for dirpath, _, filenames in os.walk(item) if item.is_dir() else [(str(item.parent), [], [item.name])]:
                for f in filenames:
                    try:
                        trash_bytes += (Path(dirpath) / f).stat().st_size
                    except OSError:
                        pass
        free = shutil.disk_usage(self.base if self.base.exists() else self.base.parent).free
        return {"files": files, "bytes": total, "trash_bytes": trash_bytes, "free": free}

    # ---------- changes ----------
    def mkdir(self, rel: Any) -> dict[str, Any]:
        parts = clean_rel(rel)
        if not parts:
            raise DiskError("Укажите имя папки.")
        parent = self.resolve(self.rel_of(parts[:-1]))
        target = parent / parts[-1]
        if target.exists():
            raise DiskError("Такое имя уже существует.", 409)
        target.mkdir()
        return self._entry(target, parts[:-1])

    def move(self, src: Any, dst: Any) -> dict[str, Any]:
        s_parts, d_parts = clean_rel(src), clean_rel(dst)
        if not s_parts or not d_parts:
            raise DiskError("Нельзя переместить корень.")
        s = self.resolve(self.rel_of(s_parts))
        if d_parts[: len(s_parts)] == s_parts:
            raise DiskError("Нельзя переместить папку внутрь самой себя.")
        parent = self.resolve(self.rel_of(d_parts[:-1]))
        if not parent.is_dir():
            raise DiskError("Целевая папка не найдена.", 404)
        target = parent / d_parts[-1]
        if target.exists() and target.resolve() != s.resolve():  # same file = case-only rename on Windows
            raise DiskError("Такое имя уже существует.", 409)
        s.rename(target)
        return self._entry(target, d_parts[:-1])

    def unique_name(self, folder: Path, name: str) -> str:
        if not (folder / name).exists():
            return name
        stem, ext = os.path.splitext(name)
        for i in range(2, 10000):
            cand = f"{stem} ({i}){ext}"
            if not (folder / cand).exists():
                return cand
        raise DiskError("Не удалось подобрать имя.", 409)

    def begin_upload(self, folder: Any, name: str, limit: int) -> "Upload":
        d = self.resolve(folder)
        if not d.is_dir():
            raise DiskError("Целевая папка не найдена.", 404)
        final = self.unique_name(d, clean_name(name))
        return Upload(self, d, clean_rel(folder), final, limit)

    def save_upload(self, folder: Any, name: str, chunks: Iterator[bytes], limit: int) -> dict[str, Any]:
        up = self.begin_upload(folder, name, limit)
        try:
            for chunk in chunks:
                up.write(chunk)
            return up.commit()
        except BaseException:
            up.abort()
            raise

    # ---------- trash ----------
    def delete(self, rel: Any) -> dict[str, Any]:
        parts = clean_rel(rel)
        if not parts:
            raise DiskError("Нельзя удалить корень диска.")
        src = self.resolve(self.rel_of(parts))
        tid = uuid.uuid4().hex[:16]
        slot = self.trash / tid
        slot.mkdir(parents=True)
        is_dir = src.is_dir()
        size = 0 if is_dir else src.stat().st_size
        shutil.move(str(src), str(slot / "payload"))
        meta = {"id": tid, "name": parts[-1], "path": self.rel_of(parts), "dir": is_dir, "size": size, "deleted_at": datetime.now(timezone.utc).isoformat()}
        (slot / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return meta

    def trash_list(self, purge_days: int = DEFAULT_TRASH_DAYS) -> list[dict[str, Any]]:
        self.ensure()
        out = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=purge_days)
        for slot in self.trash.iterdir():
            try:
                meta = json.loads((slot / "meta.json").read_text(encoding="utf-8"))
                when = datetime.fromisoformat(meta["deleted_at"])
            except (OSError, ValueError, KeyError):
                continue
            if when < cutoff:
                shutil.rmtree(slot, ignore_errors=True)
                continue
            out.append(meta)
        out.sort(key=lambda m: m["deleted_at"], reverse=True)
        return out

    def _slot(self, tid: Any) -> Path:
        if not isinstance(tid, str) or not re.fullmatch(r"[0-9a-f]{16}", tid):
            raise DiskError("Некорректный идентификатор.")
        slot = self.trash / tid
        if not (slot / "meta.json").exists():
            raise DiskError("Не найдено в корзине.", 404)
        return slot

    def restore(self, tid: Any) -> dict[str, Any]:
        slot = self._slot(tid)
        meta = json.loads((slot / "meta.json").read_text(encoding="utf-8"))
        parts = clean_rel(meta["path"])
        parent = self.files.joinpath(*parts[:-1]) if parts[:-1] else self.files
        parent.mkdir(parents=True, exist_ok=True)
        self.resolve(self.rel_of(parts[:-1]))  # re-check containment after the mkdir
        name = self.unique_name(parent, parts[-1])
        shutil.move(str(slot / "payload"), str(parent / name))
        shutil.rmtree(slot, ignore_errors=True)
        return self._entry(parent / name, parts[:-1])

    def purge(self, tid: Any) -> None:
        shutil.rmtree(self._slot(tid), ignore_errors=True)

    def empty_trash(self) -> int:
        n = 0
        for meta in self.trash_list():
            shutil.rmtree(self.trash / meta["id"], ignore_errors=True)
            n += 1
        return n

    # ---------- reading ----------
    def file_for_read(self, rel: Any) -> Path:
        p = self.resolve(rel)
        if not p.is_file():
            raise DiskError("Это не файл.", 404)
        return p


class Upload:
    """A file being written next to its destination; it only appears under its real name when commit() succeeds."""

    def __init__(self, store: DiskStore, folder: Path, parts: list[str], final: str, limit: int) -> None:
        self.store, self.folder, self.parts, self.final, self.limit = store, folder, parts, final, limit
        self.tmp = folder / f".upload-{uuid.uuid4().hex}.part"
        self.written = 0
        self._fh = open(self.tmp, "wb")

    def write(self, chunk: bytes) -> None:
        self.written += len(chunk)
        if self.written > self.limit:
            raise DiskError(f"Файл больше лимита {self.limit // (1024 * 1024)} МБ.", 413)
        self._fh.write(chunk)

    def commit(self) -> dict[str, Any]:
        self._fh.close()
        final = self.store.unique_name(self.folder, self.final)
        self.tmp.replace(self.folder / final)
        return self.store._entry(self.folder / final, self.parts)

    def abort(self) -> None:
        try:
            self._fh.close()
        finally:
            self.tmp.unlink(missing_ok=True)


def read_chunks(stream: BinaryIO, size: int = 1 << 20) -> Iterator[bytes]:
    while True:
        chunk = stream.read(size)
        if not chunk:
            return
        yield chunk
