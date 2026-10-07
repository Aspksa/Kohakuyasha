import json
from pathlib import Path

import pytest

from core import ai, memory
from core.database import Database


def test_parse_openai_style_messages_and_text_transcript():
    convs = memory.parse_import("a.json", json.dumps([{"role": "user", "content": "привет"}, {"role": "assistant", "content": "здравствуйте"}, {"role": "system", "content": "x"}]))
    assert convs[0]["messages"] == [{"role": "user", "content": "привет"}, {"role": "assistant", "content": "здравствуйте"}]
    text = "Пользователь: люблю чай\nс лимоном\nАссистент: запомню\n"
    convs = memory.parse_import("talk.txt", text)
    assert convs[0]["title"] == "talk"
    assert [m["content"] for m in convs[0]["messages"]] == ["люблю чай\nс лимоном", "запомню"]


def test_parse_chatgpt_export_follows_current_node():
    export = [{"title": "T", "current_node": "c", "mapping": {
        "a": {"parent": None, "message": {"author": {"role": "user"}, "content": {"parts": ["вопрос"]}}},
        "b": {"parent": "a", "message": {"author": {"role": "assistant"}, "content": {"parts": ["ответ"]}}},
        "x": {"parent": "a", "message": {"author": {"role": "assistant"}, "content": {"parts": ["другая ветка"]}}},
        "c": {"parent": "b", "message": {"author": {"role": "user"}, "content": {"parts": ["ещё"]}}},
    }}]
    convs = memory.parse_import("conversations.json", json.dumps(export))
    assert convs[0]["title"] == "T"
    assert [m["content"] for m in convs[0]["messages"]] == ["вопрос", "ответ", "ещё"]


def test_parse_claude_export_and_jsonl_and_notes():
    claude = [{"name": "C", "chat_messages": [{"sender": "human", "text": "hi"}, {"sender": "assistant", "text": "yo"}]}]
    assert memory.parse_import("c.json", json.dumps(claude))[0]["messages"][1] == {"role": "assistant", "content": "yo"}
    jsonl = "\n".join(json.dumps(x) for x in [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])
    assert len(memory.parse_import("d.jsonl", jsonl)[0]["messages"]) == 2
    notes = memory.parse_import("facts.md", "Я живу в Казани.\n\nМою кошку зовут Мурка.")
    assert notes[0]["messages"][0]["role"] == "note" and "Мурка" in notes[0]["messages"][0]["content"]


def test_parse_rejects_garbage():
    with pytest.raises(memory.ImportError_):
        memory.parse_import("x", "   ")
    with pytest.raises(memory.ImportError_):
        memory.parse_import("x.json", '{"foo": 1}')


def test_memory_store_search_and_skip_recent_learned(tmp_path: Path):
    db = Database(tmp_path / "m.db")
    db.initialize()
    did = db.add_dialog("Про кошек", "dialog", [{"role": "user", "content": "Мою кошку зовут Мурка"}, {"role": "assistant", "content": "Мурка — красивое имя"}])
    assert db.memory_stats() == {"dialogs": 1, "imported": 2, "learned": 0}
    hits = db.search_memory("Как зовут мою кошку?", 5)
    assert hits and hits[0]["title"] == "Про кошек" and "Мурка" in hits[0]["content"]
    assert db.search_memory("абракадабра", 5) == [] and db.search_memory("a", 5) == []
    db.add_learned("user", "кошка любит рыбу")
    assert all(h["title"] == "Про кошек" for h in db.search_memory("кошка", 5))  # fresh learned items are hidden (already in chat history)
    assert any(h["title"] == "чат" for h in db.search_memory("кошка", 5, skip_recent_learned=0))
    assert db.clear_learned() == 1
    assert db.delete_dialog(did) and not db.delete_dialog(did)
    assert db.memory_stats()["imported"] == 0 and db.search_memory("кошку", 5, 0) == []


def test_memory_is_formatted_into_system_prompt():
    prompt = ai.build_system_prompt(ai.AISettings(provider="cloudru"), {}, [{"title": "Про кошек", "role": "user", "content": "кошка Мурка"}])
    assert "Мурка" in prompt and "Про кошек" in prompt
    assert ai.format_memory([]) == ""
