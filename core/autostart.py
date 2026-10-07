from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Kohakuyasha"


def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("Переменная APPDATA недоступна.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _cmd_file() -> Path:
    return _startup_dir() / "Kohakuyasha-Autostart.cmd"


def _ps_file() -> Path:
    return _startup_dir() / "Kohakuyasha-Autostart.ps1"


def is_enabled() -> bool:
    if os.name != "nt":
        return False
    return _cmd_file().exists() and _ps_file().exists()


def enable(project_root: Path) -> Path:
    if os.name != "nt":
        raise RuntimeError("Автозапуск поддерживается только в Windows.")

    root = project_root.resolve()
    drive = Path(root.anchor)
    relative = root.relative_to(drive)
    marker_rel = str(relative / ".kohakuyasha-id").replace("'", "''")
    bat_rel = str(relative / "Kohakuyasha.bat").replace("'", "''")

    startup = _startup_dir()
    startup.mkdir(parents=True, exist_ok=True)

    ps_script = f"""$ErrorActionPreference = 'SilentlyContinue'
$markerRel = '{marker_rel}'
$batRel = '{bat_rel}'
foreach ($drive in Get-PSDrive -PSProvider FileSystem) {{
    $marker = Join-Path $drive.Root $markerRel
    if (Test-Path -LiteralPath $marker) {{
        $bat = Join-Path $drive.Root $batRel
        if (Test-Path -LiteralPath $bat) {{
            Start-Process -FilePath $bat -WorkingDirectory (Split-Path -Parent $bat)
            break
        }}
    }}
}}
"""
    _ps_file().write_text(ps_script, encoding="utf-8")
    _cmd_file().write_text(
        '@echo off\r\n'
        'powershell.exe -NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass '
        '-File "%~dp0Kohakuyasha-Autostart.ps1"\r\n',
        encoding="ascii",
    )
    return _cmd_file()


def disable() -> None:
    if os.name != "nt":
        return
    for path in (_cmd_file(), _ps_file()):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
