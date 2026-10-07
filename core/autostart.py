from __future__ import annotations

import os
import uuid
from pathlib import Path


def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("Переменная APPDATA недоступна.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _vbs_file() -> Path:
    return _startup_dir() / "Kohakuyasha-Autostart.vbs"


def _ps_file() -> Path:
    return _startup_dir() / "Kohakuyasha-Autostart.ps1"


def ensure_instance_marker(project_root: Path) -> str:
    marker = project_root / ".kohakuyasha-id"
    try:
        value = marker.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    value = str(uuid.uuid4())
    marker.write_text(value + "\n", encoding="utf-8")
    return value


def is_enabled() -> bool:
    if os.name != "nt":
        return False
    return _vbs_file().exists() and _ps_file().exists()


def enable(project_root: Path) -> Path:
    if os.name != "nt":
        raise RuntimeError("Автозапуск поддерживается только в Windows.")

    root = project_root.resolve()
    instance_id = ensure_instance_marker(root).replace("'", "''")
    startup = _startup_dir()
    startup.mkdir(parents=True, exist_ok=True)

    ps_script = f"""$ErrorActionPreference = 'SilentlyContinue'
$instanceId = '{instance_id}'
foreach ($drive in Get-PSDrive -PSProvider FileSystem) {{
    $marker = Join-Path $drive.Root '.kohakuyasha-id'
    if (-not (Test-Path -LiteralPath $marker)) {{ continue }}
    $found = (Get-Content -LiteralPath $marker -Raw -ErrorAction SilentlyContinue).Trim()
    if ($found -ne $instanceId) {{ continue }}
    $root = Split-Path -Parent $marker
    $bat = Join-Path $root 'Kohakuyasha.bat'
    if (Test-Path -LiteralPath $bat) {{
        Start-Process -FilePath $bat -WorkingDirectory $root
        break
    }}
}}
"""
    # UTF-8 BOM is required for Windows PowerShell 5.1 to read non-ASCII paths reliably.
    _ps_file().write_text(ps_script, encoding="utf-8-sig")
    command = (
        'Set sh=CreateObject("WScript.Shell")\r\n'
        'base=CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)\r\n'
        'ps=base & "\\Kohakuyasha-Autostart.ps1"\r\n'
        'sh.Run "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File """ & ps & """", 0, False\r\n'
    )
    _vbs_file().write_text(command, encoding="ascii")
    return _vbs_file()


def disable() -> None:
    if os.name != "nt":
        return
    for path in (_vbs_file(), _ps_file(), _startup_dir() / "Kohakuyasha-Autostart.cmd"):
        path.unlink(missing_ok=True)
