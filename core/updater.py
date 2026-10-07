"""Project self-update from GitHub (zipball of a branch), with backups and rollback.

Trust model: code is downloaded over HTTPS from the repository/branch configured in Settings (default Aspksa/Kohakuyasha@main),
validated structurally, and only files outside the protected user-data paths are replaced. Every replaced or removed file is
copied to .runtime/backups first, so an update can be rolled back from the UI.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

GITHUB_API = os.environ.get("KOHAKUYASHA_GITHUB_API", "https://api.github.com").rstrip("/")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,60}/[A-Za-z0-9_.-]{1,100}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9_./-]{1,80}$")
TIMEOUT = 30
MAX_ZIP_BYTES = 80_000_000
MAX_FILES = 3000
MAX_UNPACKED = 300_000_000
KEEP_BACKUPS = 3
# Never overwritten or deleted by an update: user data, runtime, identity, VCS.
PROTECTED = ("data/", "logs/", ".runtime/", ".git/", ".kohakuyasha-id")
# Not needed at runtime.
SKIPPED = (".github/", "tests/")
REQUIRED = ("VERSION", "main.py", "launcher.pyw", "core/__init__.py")
_lock = threading.Lock()


class UpdateError(Exception):
    """Human-readable (Russian) update problem, safe to show in the UI."""


@dataclass(slots=True)
class UpdateSettings:
    repo: str = "Aspksa/Kohakuyasha"
    branch: str = "main"
    auto_check: bool = True


def validate_settings(raw: dict[str, Any] | None) -> UpdateSettings:
    raw = raw if isinstance(raw, dict) else {}
    d = UpdateSettings()
    repo, branch = raw.get("repo"), raw.get("branch")
    return UpdateSettings(
        repo=repo.strip() if isinstance(repo, str) and REPO_RE.match(repo.strip()) else d.repo,
        branch=branch.strip() if isinstance(branch, str) and BRANCH_RE.match(branch.strip()) and ".." not in branch else d.branch,
        auto_check=raw.get("auto_check") if isinstance(raw.get("auto_check"), bool) else d.auto_check,
    )


# ---------- versions ----------
def parse_version(text: str) -> tuple[int, ...]:
    m = re.match(r"^\s*v?(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else ()


def is_newer(remote: str, local: str) -> bool:
    r, l = parse_version(remote), parse_version(local)
    return bool(r) and bool(l) and r > l


# ---------- network ----------
class _SameHostAuth(urllib.request.HTTPRedirectHandler):
    """Follow redirects (GitHub zipballs redirect to codeload) but never forward the token to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            new.headers.pop("Authorization", None)
            new.unredirected_hdrs.pop("Authorization", None)
        return new


_OPENER = urllib.request.build_opener(_SameHostAuth())


def _request(url: str, token: str, accept: str) -> urllib.request.Request:
    headers = {"Accept": accept, "User-Agent": "Kohakuyasha-updater", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def _open(url: str, token: str, accept: str, limit: int) -> bytes:
    try:
        with _OPENER.open(_request(url, token, accept), timeout=TIMEOUT) as response:
            data = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("Репозиторий или ветка не найдены. Для приватного репозитория укажите токен GitHub с доступом на чтение.") from None
        if exc.code in (401, 403):
            raise UpdateError("GitHub отказал в доступе: проверьте токен или подождите, если исчерпан лимит запросов.") from None
        raise UpdateError(f"GitHub вернул ошибку {exc.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Нет связи с GitHub: {getattr(exc, 'reason', exc)}") from None
    if len(data) > limit:
        raise UpdateError("Ответ GitHub слишком большой.")
    return data


def fetch_text(repo: str, branch: str, path: str, token: str, limit: int = 2_000_000) -> str:
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}?ref={branch}"
    return _open(url, token, "application/vnd.github.raw+json", limit).decode("utf-8", "replace")


def fetch_zip(repo: str, branch: str, token: str) -> bytes:
    return _open(f"{GITHUB_API}/repos/{repo}/zipball/{branch}", token, "application/vnd.github+json", MAX_ZIP_BYTES)


def fetch_commit(repo: str, branch: str, token: str) -> dict[str, str]:
    try:
        data = json.loads(_open(f"{GITHUB_API}/repos/{repo}/commits/{branch}", token, "application/vnd.github+json", 1_000_000))
        return {"sha": str(data.get("sha", ""))[:7], "date": str((data.get("commit", {}).get("committer") or {}).get("date", ""))}
    except (UpdateError, ValueError):
        return {"sha": "", "date": ""}


def release_notes(changelog: str, local: str, limit: int = 5) -> list[dict[str, str]]:
    """Newest changelog entries (JSONL) with a version above the installed one."""
    notes = []
    for line in changelog.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        version = str(item.get("version", ""))
        if is_newer(version, local) and item.get("summary"):
            notes.append({"version": version, "date": str(item.get("date", "")), "summary": str(item["summary"])[:400]})
    return notes[::-1][:limit]


def check(repo: str, branch: str, token: str, local: str) -> dict[str, Any]:
    remote = fetch_text(repo, branch, "VERSION", token, 100).strip()
    if not parse_version(remote):
        raise UpdateError("В репозитории не найден корректный файл VERSION.")
    newer = is_newer(remote, local)
    notes: list[dict[str, str]] = []
    if newer:
        try:
            notes = release_notes(fetch_text(repo, branch, "CHANGELOG.jsonl", token), local)
        except UpdateError:
            notes = []
    return {"local": local, "remote": remote, "newer": newer, "notes": notes, **fetch_commit(repo, branch, token),
            "checked_at": datetime.now().isoformat(timespec="seconds"), "repo": repo, "branch": branch}


# ---------- validating and applying ----------
def _safe_member(name: str) -> str | None:
    """Path inside the repo (top-level folder stripped) or None for entries to skip. Raises on traversal."""
    parts = PurePosixPath(name).parts
    if len(parts) < 2:
        return None
    rel = PurePosixPath(*parts[1:])
    if rel.is_absolute() or ".." in rel.parts or "\\" in str(rel) or ":" in rel.parts[0]:
        raise UpdateError("Архив содержит небезопасные пути.")
    return str(rel)


def _is_protected(rel: str) -> bool:
    return any(rel == p.rstrip("/") or rel.startswith(p) for p in PROTECTED)


def _is_skipped(rel: str) -> bool:
    return any(rel.startswith(p) for p in SKIPPED) or rel.endswith("/")


def read_zip(blob: bytes) -> dict[str, bytes]:
    """Validated {relative path: content} for every file that should be installed."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise UpdateError("Скачанный архив повреждён.") from None
    infos = archive.infolist()
    if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNPACKED:
        raise UpdateError("Архив слишком большой.")
    files: dict[str, bytes] = {}
    for info in infos:
        if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
            continue
        rel = _safe_member(info.filename)
        if rel is None or _is_skipped(rel) or _is_protected(rel):
            continue
        files[rel] = archive.read(info)
    missing = [r for r in REQUIRED if r not in files]
    if missing:
        raise UpdateError("В архиве нет обязательных файлов: " + ", ".join(missing))
    if not parse_version(files["VERSION"].decode("utf-8", "replace")):
        raise UpdateError("В архиве некорректный файл VERSION.")
    return files


def _manifest_path(root: Path) -> Path:
    return root / ".runtime" / "installed-files.json"


def _backup_root(root: Path) -> Path:
    return root / ".runtime" / "backups"


def apply(root: Path, files: dict[str, bytes], old_version: str) -> dict[str, Any]:
    if not _lock.acquire(blocking=False):
        raise UpdateError("Обновление уже выполняется.")
    try:
        root = Path(root).resolve()
        new_version = files["VERSION"].decode("utf-8", "replace").strip()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = _backup_root(root) / f"{old_version}-{stamp}"
        previous: list[str] = []
        try:
            previous = json.loads(_manifest_path(root).read_text(encoding="utf-8")).get("files", [])
        except (OSError, ValueError):
            previous = []
        changed, removed, new_files = 0, 0, 0
        written: list[tuple[Path, Path | None]] = []
        try:
            for rel, content in files.items():
                target = (root / rel).resolve()
                if root not in target.parents:
                    raise UpdateError("Архив содержит небезопасные пути.")
                if target.exists() and target.is_file() and target.read_bytes() == content:
                    continue
                saved = None
                if target.exists():
                    saved = backup / rel
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, saved)
                else:
                    new_files += 1
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(target.name + ".kohaku-new")
                tmp.write_bytes(content)
                os.replace(tmp, target)
                written.append((target, saved))
                changed += 1
            for rel in previous:  # files the previous release installed but the new one no longer has
                if rel not in files and not _is_protected(rel):
                    target = (root / rel).resolve()
                    if root in target.parents and target.is_file():
                        saved = backup / rel
                        saved.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, saved)
                        target.unlink()
                        removed += 1
        except Exception:
            for target, saved in reversed(written):  # undo a half-applied update
                if saved is not None and saved.exists():
                    shutil.copy2(saved, target)
                else:
                    target.unlink(missing_ok=True)
            raise
        (backup).mkdir(parents=True, exist_ok=True)
        (backup / "meta.json").write_text(json.dumps({"from": old_version, "to": new_version, "created": stamp, "added": [str(t.relative_to(root)) for t, s in written if s is None]}), encoding="utf-8")
        _manifest_path(root).parent.mkdir(parents=True, exist_ok=True)
        _manifest_path(root).write_text(json.dumps({"version": new_version, "files": sorted(files)}), encoding="utf-8")
        _prune_backups(root)
        return {"changed": changed, "removed": removed, "added": new_files, "version": new_version, "backup": backup.name}
    finally:
        _lock.release()


def _prune_backups(root: Path) -> None:
    dirs = sorted((d for d in _backup_root(root).glob("*") if d.is_dir()), key=lambda d: d.name, reverse=True)
    for old in dirs[KEEP_BACKUPS:]:
        shutil.rmtree(old, ignore_errors=True)


def list_backups(root: Path) -> list[dict[str, str]]:
    out = []
    for d in sorted((d for d in _backup_root(Path(root)).glob("*") if d.is_dir()), key=lambda d: d.name, reverse=True):
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"name": d.name, "from": str(meta.get("from", "")), "to": str(meta.get("to", "")), "created": str(meta.get("created", ""))})
    return out


def rollback(root: Path) -> dict[str, Any]:
    """Restore the most recent backup (files replaced/removed by the last update) and delete files the update added."""
    if not _lock.acquire(blocking=False):
        raise UpdateError("Обновление уже выполняется.")
    try:
        root = Path(root).resolve()
        backups = list_backups(root)
        if not backups:
            raise UpdateError("Резервных копий нет.")
        latest = _backup_root(root) / backups[0]["name"]
        meta = json.loads((latest / "meta.json").read_text(encoding="utf-8"))
        restored = 0
        for src in latest.rglob("*"):
            if src.is_file() and src.name != "meta.json":
                rel = src.relative_to(latest)
                target = (root / rel).resolve()
                if root in target.parents and not _is_protected(str(rel).replace("\\", "/")):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, target)
                    restored += 1
        for rel in meta.get("added", []):
            target = (root / rel).resolve()
            if root in target.parents and not _is_protected(rel):
                target.unlink(missing_ok=True)
        shutil.rmtree(latest, ignore_errors=True)
        try:
            _manifest_path(root).unlink(missing_ok=True)
        except OSError:
            pass
        return {"restored": restored, "version": str(meta.get("from", ""))}
    finally:
        _lock.release()


# ---------- relaunch ----------
def relaunch(root: Path) -> bool:
    """Start Kohakuyasha.bat again after a short delay (so this instance can release its lock). Windows only."""
    if os.name != "nt":
        return False
    bat = Path(root).resolve() / "Kohakuyasha.bat"
    if not bat.is_file():
        return False
    command = f"Start-Sleep -Seconds 3; Start-Process -FilePath '{str(bat).replace(chr(39), chr(39) * 2)}' -WorkingDirectory '{str(bat.parent).replace(chr(39), chr(39) * 2)}'"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(["powershell.exe", "-NoLogo", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command], creationflags=flags, close_fds=True)
    return True
