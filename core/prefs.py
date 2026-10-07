from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MEDIA_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{3,90}\.(png|jpg|webp)$")
FACE_ID_RE = re.compile(r"^(default|[a-f0-9]{8})$")
ACTIONS = ("chat", "cabinet", "none")


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _int(value: Any, default: int, low: int, high: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, low), high)


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _color(value: Any, default: str) -> str:
    return value.lower() if isinstance(value, str) and HEX_RE.match(value) else default


@dataclass(slots=True)
class AvatarSettings:
    active_face: str = "default"
    crop: str = "face"          # face | full
    shape: str = "soft"         # soft | rounded | circle
    size: int = 96
    opacity: int = 100
    ring: bool = False
    ring_color: str = "#e8be56"
    glow: bool = True
    glow_color: str = "#e8be56"
    status_dot: bool = True
    animation: str = "none"     # none | float | pulse | breathe
    snap_edges: bool = False
    idle_dim: bool = False
    hide_on_open: bool = False
    greeting: bool = True
    left_action: str = "chat"
    right_action: str = "cabinet"
    replace_logo: bool = True


def validate_avatar(raw: dict[str, Any] | None) -> AvatarSettings:
    raw = raw if isinstance(raw, dict) else {}
    d = AvatarSettings()
    face = raw.get("active_face")
    return AvatarSettings(
        active_face=face if isinstance(face, str) and FACE_ID_RE.match(face) else d.active_face,
        crop=_choice(raw.get("crop"), ("face", "full"), d.crop),
        shape=_choice(raw.get("shape"), ("soft", "rounded", "circle"), d.shape),
        size=_int(raw.get("size"), d.size, 48, 240),
        opacity=_int(raw.get("opacity"), d.opacity, 30, 100),
        ring=_bool(raw.get("ring"), d.ring),
        ring_color=_color(raw.get("ring_color"), d.ring_color),
        glow=_bool(raw.get("glow"), d.glow),
        glow_color=_color(raw.get("glow_color"), d.glow_color),
        status_dot=_bool(raw.get("status_dot"), d.status_dot),
        animation=_choice(raw.get("animation"), ("none", "float", "pulse", "breathe"), d.animation),
        snap_edges=_bool(raw.get("snap_edges"), d.snap_edges),
        idle_dim=_bool(raw.get("idle_dim"), d.idle_dim),
        hide_on_open=_bool(raw.get("hide_on_open"), d.hide_on_open),
        greeting=_bool(raw.get("greeting"), d.greeting),
        left_action=_choice(raw.get("left_action"), ACTIONS, d.left_action),
        right_action=_choice(raw.get("right_action"), ACTIONS, d.right_action),
        replace_logo=_bool(raw.get("replace_logo"), d.replace_logo),
    )


@dataclass(slots=True)
class AppSettings:
    theme: str = "dark"         # dark | black | light | auto
    accent: str = "gold"        # gold | rose | violet | blue | green | red
    background: str = "glow"    # glow | plain | image
    bg_image: str = ""
    bg_dim: int = 45
    ui_zoom: int = 100
    animations: bool = True
    clock_24h: bool = True
    clock_seconds: bool = True
    week_start: int = 1         # 1 = Monday, 0 = Sunday


ACCENTS = ("gold", "rose", "violet", "blue", "green", "red")


def validate_app(raw: dict[str, Any] | None) -> AppSettings:
    raw = raw if isinstance(raw, dict) else {}
    d = AppSettings()
    image = raw.get("bg_image")
    image = image if isinstance(image, str) and MEDIA_NAME_RE.match(image) else ""
    background = _choice(raw.get("background"), ("glow", "plain", "image"), d.background)
    if background == "image" and not image:
        background = "glow"
    return AppSettings(
        theme=_choice(raw.get("theme"), ("dark", "black", "light", "auto"), d.theme),
        accent=_choice(raw.get("accent"), ACCENTS, d.accent),
        background=background,
        bg_image=image,
        bg_dim=_int(raw.get("bg_dim"), d.bg_dim, 0, 85),
        ui_zoom=_int(raw.get("ui_zoom"), d.ui_zoom, 85, 130),
        animations=_bool(raw.get("animations"), d.animations),
        clock_24h=_bool(raw.get("clock_24h"), d.clock_24h),
        clock_seconds=_bool(raw.get("clock_seconds"), d.clock_seconds),
        week_start=0 if raw.get("week_start") in (0, "0") else 1,
    )


@dataclass(slots=True)
class MemorySettings:
    enabled: bool = True
    learn_chat: bool = True
    max_snippets: int = 6


def validate_memory(raw: dict[str, Any] | None) -> MemorySettings:
    raw = raw if isinstance(raw, dict) else {}
    d = MemorySettings()
    return MemorySettings(
        enabled=_bool(raw.get("enabled"), d.enabled),
        learn_chat=_bool(raw.get("learn_chat"), d.learn_chat),
        max_snippets=_int(raw.get("max_snippets"), d.max_snippets, 1, 12),
    )
