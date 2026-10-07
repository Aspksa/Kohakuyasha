import json
from datetime import datetime
from pathlib import Path

import pytest

from core import ai, brain, prefs
from core.database import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "b.db")
    d.initialize()
    return d


def script_provider(monkeypatch, facts=None, summary="Кратко: обсуждали кошку.", extract_raw=None):
    """Fake Cloud.ru: routes by the system prompt so extraction, summary and chat get different answers."""
    calls = {"extract": 0, "summary": 0, "chat": 0, "systems": []}

    def fake(url, headers, body):
        system = body["messages"][0]["content"] if body["messages"][0]["role"] == "system" else ""
        calls["systems"].append(system)
        if system == brain.EXTRACT_SYSTEM:
            calls["extract"] += 1
            content = extract_raw if extract_raw is not None else json.dumps({"facts": facts or []}, ensure_ascii=False)
        elif system == brain.SUMMARY_SYSTEM:
            calls["summary"] += 1
            content = summary
        else:
            calls["chat"] += 1
            content = "Ответ"
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(ai, "_http_post_json", fake)
    return calls


def test_text_helpers():
    assert brain.similarity("Любит чай с лимоном", "любит чай лимон") >= 0.6
    assert brain.similarity("Живёт в Казани", "Работает программистом") < 0.3
    assert brain.similarity("Живёт в Казани", "Живёт в Казани уже 5 лет") >= 0.6  # an expanded version is the same fact
    assert brain.similarity("Живёт в Казани", "Работает в Казани") < 0.6 and brain.similarity("Мурка", "Мурка любит рыбу") < 0.6
    assert brain.explicit_remember("Запомни: я живу в Казани") == "я живу в Казани"
    assert brain.explicit_remember("запиши мою кошку зовут Мурка") == "мою кошку зовут Мурка"
    assert brain.explicit_remember("не запомни это") is None and brain.explicit_remember("запомни") is None


def test_cognition_router_and_contextual_followups():
    assert brain.reasoning_mode("привет") == "fast"
    assert brain.reasoning_mode("Проанализируй архитектуру кода, сравни варианты и объясни почему? Что проверить?") == "deep"
    history = [{"role": "user", "content": "У меня есть кошка Мурка"}, {"role": "assistant", "content": "Запомнила"}, {"role": "user", "content": "Она любит рыбу"}]
    expanded = brain.contextual_query("а как её зовут?", history)
    assert "как её зовут" in expanded and "кошка Мурка" in expanded
    assert "глубокий" in brain.cognition_block("Проанализируй код\n\nсравни два решения? Что проверить?")


def test_working_memory_and_conflict_detection():
    history = [
        {"role": "user", "content": "Нужно отвечать коротко и без лишних вопросов"},
        {"role": "assistant", "content": "Хорошо"},
        {"role": "user", "content": "Сделай план архитектуры"},
    ]
    block = brain.working_memory_block("Сделай план архитектуры", history)
    assert "Текущая цель" in block and "без лишних вопросов" in block
    facts = [
        {"text": "Любит кофе", "category": "preference"},
        {"text": "Не любит кофе", "category": "preference"},
        {"text": "Живёт в Казани", "category": "personal"},
    ]
    pairs = brain.memory_conflicts(facts)
    assert len(pairs) == 1 and "кофе" in brain.format_conflicts(pairs).lower()


def test_parse_facts_json_is_tolerant():
    good = '{"facts":[{"text":"Любит чай","category":"preference","importance":4},{"text":"x"},{"text":"Живёт в Казани","category":"zzz","importance":99}]}'
    out = brain.parse_facts_json(good)
    assert out == [{"text": "Любит чай", "category": "preference", "importance": 4}, {"text": "Живёт в Казани", "category": "other", "importance": 3}]
    assert brain.parse_facts_json("```json\n" + good + "\n```") == out
    assert brain.parse_facts_json("Вот результат: " + good + " готово")[0]["text"] == "Любит чай"
    assert brain.parse_facts_json('["Кошку зовут Мурка"]')[0]["text"] == "Кошку зовут Мурка"
    assert brain.parse_facts_json("не json") == [] and brain.parse_facts_json("") == [] and brain.parse_facts_json('{"facts": 5}') == []


def test_select_facts_prefers_pinned_then_relevance():
    now = datetime.now().astimezone()
    base = {"updated_at": now.isoformat(), "pinned": False}
    facts = [
        {**base, "id": 1, "text": "Любит зелёный чай", "importance": 2},
        {**base, "id": 2, "text": "Работает программистом", "importance": 5},
        {**base, "id": 3, "text": "Кошку зовут Мурка", "importance": 2},
        {**base, "id": 4, "text": "Закреплённое правило", "importance": 1, "pinned": True},
    ]
    top = brain.select_facts(facts, "как зовут мою кошку?", limit=2, now=now)
    assert [f["id"] for f in top] == [4, 3]  # pinned first, then the relevant one beats the important-but-unrelated
    assert brain.select_facts(facts, "", limit=10, now=now)[0]["id"] == 4


def test_store_facts_deduplicates(db: Database):
    added, updated = brain.store_facts(db, [{"text": "Любит чай с лимоном", "category": "preference", "importance": 3}])
    assert (added, updated) == (1, 0)
    added, updated = brain.store_facts(db, [{"text": "Любит чай с лимоном и мёдом", "category": "preference", "importance": 5}, {"text": "Живёт в Казани", "category": "personal", "importance": 4}])
    assert (added, updated) == (1, 1)
    facts = {f["text"]: f for f in db.list_facts()}
    assert "Любит чай с лимоном и мёдом" in facts and facts["Любит чай с лимоном и мёдом"]["importance"] == 5
    assert db.fact_count() == 2


def test_fact_crud_and_trim(db: Database):
    a = db.add_fact("Первый факт", "bad-category", 99, "manual", True)
    f = db.list_facts()[0]
    assert f["category"] == "other" and f["importance"] == 5 and f["pinned"] is True
    assert db.update_fact(a, text="Изменённый", importance=2, pinned=False, category="project")
    assert not db.update_fact(a) and not db.update_fact(9999, text="x")
    for i in range(6):
        db.add_fact(f"Автофакт номер {i}", "other", 1, "auto")
    db.trim_facts(3)
    assert db.fact_count() == 3
    assert db.clear_facts("auto") == 2 and db.fact_count() == 1  # the manual fact survives
    assert db.delete_fact(a) and not db.delete_fact(a)


def test_maintenance_extracts_after_n_user_messages_and_is_idempotent(db: Database, monkeypatch):
    calls = script_provider(monkeypatch, facts=[{"text": "Кошку зовут Мурка", "category": "relation", "importance": 4}])
    settings, mem = ai.AISettings(), prefs.MemorySettings(extract_every=3)
    for t in ("привет", "у меня есть кошка Мурка"):
        db.add_chat_message("user", t); db.add_chat_message("assistant", "ок")
    assert brain.run_maintenance(db, settings, "k", mem)["added"] == 0 and calls["extract"] == 0  # only 2 user messages so far
    db.add_chat_message("user", "её любимая еда — рыба"); db.add_chat_message("assistant", "ок")
    r = brain.run_maintenance(db, settings, "k", mem)
    assert r["added"] == 1 and r["texts"] == ["Кошку зовут Мурка"] and calls["extract"] == 1
    assert brain.run_maintenance(db, settings, "k", mem)["added"] == 0 and calls["extract"] == 1  # pointer advanced: nothing new
    assert db.get_setting("memory_state")["extracted_upto"] > 0


def test_explicit_remember_falls_back_to_user_words(db: Database, monkeypatch):
    script_provider(monkeypatch, extract_raw="это не json")
    db.add_chat_message("user", "Запомни: пароль от Wi-Fi хранится в сейфе"); db.add_chat_message("assistant", "ок")
    r = brain.run_maintenance(db, ai.AISettings(), "k", prefs.MemorySettings(), explicit="пароль от Wi-Fi хранится в сейфе")
    assert r["added"] == 1 and db.list_facts()[0]["importance"] == 5 and "сейфе" in db.list_facts()[0]["text"]


def test_provider_errors_are_reported_not_raised(db: Database, monkeypatch):
    def boom(url, headers, body):
        raise OSError("down")

    monkeypatch.setattr(ai, "_http_post_json", boom)
    notes = []
    for t in ("а", "б", "в"):
        db.add_chat_message("user", t)
    r = brain.run_maintenance(db, ai.AISettings(), "k", prefs.MemorySettings(), notify=lambda lvl, msg: notes.append((lvl, msg)))
    assert "Нет связи" in r["error"] and notes and notes[0][0] == "WARNING"
    assert db.get_setting("memory_state").get("extracted_upto", 0) == 0  # will retry next time


def test_summary_folds_old_messages_and_history_window_skips_them(db: Database, monkeypatch):
    calls = script_provider(monkeypatch, summary="Обсуждали проект «Лиса».")
    mem = prefs.MemorySettings(auto_facts=False)
    for i in range(brain.SUMMARY_TRIGGER + 5):
        db.add_chat_message("user" if i % 2 == 0 else "assistant", f"сообщение {i}")
    assert len(brain.history_window(db, mem)) == brain.HISTORY_WINDOW  # no summary yet: plain recent window
    r = brain.run_maintenance(db, ai.AISettings(), "k", mem)
    assert r["summarized"] is True and calls["summary"] == 1 and calls["extract"] == 0
    state = db.get_setting("memory_state")
    assert state["summary"] == "Обсуждали проект «Лиса»." and state["summary_upto"] > 0
    window = brain.history_window(db, mem)
    assert len(window) == brain.SUMMARY_KEEP
    assert all(m["id"] > state["summary_upto"] for m in window)
    assert not brain.run_maintenance(db, ai.AISettings(), "k", mem)["summarized"]  # nothing left to fold


def test_build_context_has_time_facts_and_summary(db: Database):
    now = datetime(2026, 10, 7, 9, 30)
    db.add_fact("Кошку зовут Мурка", "relation", 4, "auto")
    db.set_setting("memory_state", {"summary": "Обсуждали отпуск."})
    blocks, used = brain.build_context(db, prefs.MemorySettings(), "как зовут кошку", now)
    text = "\n".join(blocks)
    assert "среда, 7 октября 2026, 09:30" in text and "Мурка" in text and "Обсуждали отпуск" in text
    assert "календар" not in text.lower() and len(used) == 1 and brain.GUIDELINES in text
    off = prefs.MemorySettings(use_facts=False, use_summary=False)
    blocks, used = brain.build_context(db, off, "кошка", now)
    assert len(blocks) == 2 and used == []  # clock plus cognition mode


def test_memory_settings_are_clamped():
    m = prefs.validate_memory({"extract_every": 99, "auto_facts": "yes", "use_summary": False})
    assert m.extract_every == 10 and m.auto_facts is True and m.use_summary is False
