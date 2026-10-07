from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

MAX_MESSAGES = 5000
MAX_CHARS = 20_000
NOTE_CHUNK = 1500
ROLE_MAP = {
    "user": "user", "human": "user", "me": "user", "you": "user", "u": "user", "я": "user", "пользователь": "user",
    "assistant": "assistant", "ai": "assistant", "bot": "assistant", "model": "assistant", "gpt": "assistant",
    "chatgpt": "assistant", "claude": "assistant", "a": "assistant", "ассистент": "assistant", "бот": "assistant", "ии": "assistant",
}
LINE_RE = re.compile(r"^\s*([A-Za-zА-Яа-яЁё]{1,12})\s*[:：]\s*(.*)$")


class ImportError_(ValueError):
    """Unparseable import; the message is safe to show in the UI."""


def _norm_role(value: Any) -> str | None:
    return ROLE_MAP.get(str(value).strip().lower()) if value is not None else None


def _content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(filter(None, (_content(v) for v in value))).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "parts"):
            if key in value:
                return _content(value[key])
    return ""


def _messages(items: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        author = item.get("author")
        role = _norm_role(author.get("role") if isinstance(author, dict) else (item.get("role") or item.get("sender") or author))
        text = _content(item.get("content", item.get("text", item.get("message"))))
        if role and text:
            out.append({"role": role, "content": text[:MAX_CHARS]})
    return out


def _chatgpt(conv: dict[str, Any]) -> list[dict[str, str]]:
    mapping = conv.get("mapping")
    if not isinstance(mapping, dict):
        return []
    node_id, chain, seen = conv.get("current_node"), [], set()
    if node_id in mapping:
        while node_id and node_id in mapping and node_id not in seen:
            seen.add(node_id)
            chain.append(mapping[node_id])
            node_id = mapping[node_id].get("parent")
        chain.reverse()
    else:
        chain = sorted((n for n in mapping.values() if isinstance(n, dict)), key=lambda n: (n.get("message") or {}).get("create_time") or 0)
    out: list[dict[str, str]] = []
    for node in chain:
        msg = node.get("message") if isinstance(node, dict) else None
        if not isinstance(msg, dict):
            continue
        author = msg.get("author") if isinstance(msg.get("author"), dict) else {}
        role = _norm_role(author.get("role"))
        text = _content((msg.get("content") or {}).get("parts") if isinstance(msg.get("content"), dict) else msg.get("content"))
        if role and text:
            out.append({"role": role, "content": text[:MAX_CHARS]})
    return out


def _from_object(obj: Any, default_title: str) -> list[dict[str, Any]]:
    convs: list[dict[str, Any]] = []
    if isinstance(obj, list):
        if obj and all(isinstance(i, dict) and ("role" in i or "sender" in i) and ("content" in i or "text" in i) for i in obj):
            msgs = _messages(obj)
            return [{"title": default_title, "messages": msgs}] if msgs else []
        for index, item in enumerate(obj, 1):
            convs.extend(_from_object(item, f"{default_title} #{index}"))
        return convs
    if isinstance(obj, dict):
        title = str(obj.get("title") or obj.get("name") or default_title)[:120]
        if "mapping" in obj:
            msgs = _chatgpt(obj)
        elif isinstance(obj.get("chat_messages"), list):
            msgs = _messages(obj["chat_messages"])
        elif isinstance(obj.get("messages"), list):
            msgs = _messages(obj["messages"])
        elif isinstance(obj.get("conversations"), list):
            return _from_object(obj["conversations"], default_title)
        else:
            return []
        return [{"title": title, "messages": msgs}] if msgs else []
    return convs


def _from_text(text: str, title: str) -> list[dict[str, Any]]:
    msgs: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        m = LINE_RE.match(line)
        role = _norm_role(m.group(1)) if m else None
        if m and role:
            if current:
                msgs.append(current)
            current = {"role": role, "content": m.group(2)}
        elif current is not None:
            current["content"] += "\n" + line
    if current:
        msgs.append(current)
    msgs = [{"role": x["role"], "content": x["content"].strip()[:MAX_CHARS]} for x in msgs if x["content"].strip()]
    if msgs:
        return [{"title": title, "messages": msgs}]
    # Not a transcript: keep it as knowledge notes (paragraph chunks).
    notes, buf = [], ""
    for para in re.split(r"\n{2,}", text.strip()):
        para = para.strip()
        if not para:
            continue
        if buf and len(buf) + len(para) > NOTE_CHUNK:
            notes.append({"role": "note", "content": buf})
            buf = ""
        buf = f"{buf}\n\n{para}".strip()
    if buf:
        notes.append({"role": "note", "content": buf[:MAX_CHARS]})
    return [{"title": title, "messages": notes}] if notes else []


def parse_import(filename: str, text: str) -> list[dict[str, Any]]:
    """Return [{title, messages:[{role: user|assistant|note, content}]}] from JSON, JSONL, chat exports or plain text."""
    if not isinstance(text, str) or not text.strip():
        raise ImportError_("Нечего импортировать: текст пустой.")
    stem = (filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0].strip()
    title = (stem or f"Диалог от {datetime.now():%d.%m.%Y %H:%M}")[:120]
    body = text.strip().lstrip("﻿")
    convs: list[dict[str, Any]] = []
    parsed = False
    if body[:1] in "[{":
        try:
            convs, parsed = _from_object(json.loads(body), title), True
        except ValueError:
            parsed = False
        if not parsed:
            try:
                objs = [json.loads(line) for line in body.splitlines() if line.strip()]
                convs, parsed = _from_object(objs, title), True
            except ValueError:
                parsed = False
    if not convs:
        if parsed:
            raise ImportError_("В JSON не найдено сообщений. Нужны поля role/content, экспорт ChatGPT или Claude.")
        convs = _from_text(body, title)
    total = 0
    for conv in convs:
        conv["messages"] = conv["messages"][: max(0, MAX_MESSAGES - total)]
        total += len(conv["messages"])
    convs = [c for c in convs if c["messages"]]
    if not convs:
        raise ImportError_("Не удалось распознать сообщения.")
    return convs
