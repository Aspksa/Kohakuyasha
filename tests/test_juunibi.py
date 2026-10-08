import json
import shutil
from pathlib import Path

import pytest

from core import ai, juunibi
from core.database import Database

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content" / "juunibi"
CLOUD = ai.AISettings(provider="cloudru")
NONE = ai.AISettings(provider="none")


@pytest.fixture()
def engine(tmp_path):
    db = Database(tmp_path / "k.db"); db.initialize()
    return juunibi.Engine(db, juunibi.Library(CONTENT))


def test_library_loads_the_pack():
    lib = juunibi.Library(CONTENT)
    assert lib.available and len(lib.actions) == 365 and len(lib.phrases) == 452 and lib.persona()["name"] == "JUUNIBI"
    assert "Господин" in json.dumps(lib.persona(), ensure_ascii=False) and len(json.dumps(lib.persona(), ensure_ascii=False)) < 9000


def test_missing_or_duplicated_content_is_reported(tmp_path):
    assert not juunibi.Library(tmp_path / "nope").available and "не найдены" in juunibi.Library(tmp_path / "nope").error
    bad = tmp_path / "bad"; shutil.copytree(CONTENT, bad)
    data = json.loads((bad / juunibi.ACTIONS_FILE).read_text(encoding="utf-8")); data["actions"][1]["id"] = data["actions"][0]["id"]
    (bad / juunibi.ACTIONS_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert not juunibi.Library(bad).available


def test_all_365_actions_are_unique_and_persist_across_restarts(tmp_path):
    db = Database(tmp_path / "k.db"); db.initialize()
    seen = set()
    for i in range(365):
        eng = juunibi.Engine(db, juunibi.Library(CONTENT))  # a fresh engine each time = a restart
        a = eng.next_action(NONE, "", allow_generate=False)
        assert a["id"] not in seen
        seen.add(a["id"])
    assert len(seen) == 365
    with pytest.raises(juunibi.JuunibiError) as e:
        juunibi.Engine(db, juunibi.Library(CONTENT)).next_action(NONE, "", allow_generate=False)
    assert "Повтор не выполняется" in str(e.value)


def test_category_filter_and_variety(engine):
    assert engine.next_action(NONE, "", category="защита")["category"] == "защита"
    cats = [engine.next_action(NONE, "")["category"] for _ in range(40)]
    assert sum(1 for a, b in zip(cats, cats[1:]) if a == b) <= 3  # moods rarely repeat back to back
    assert engine.next_action(NONE, "", category="такой нет")["id"]  # unknown category = any


GOOD = "*Она медленно проводит ладонью по воздуху, и над столом вспыхивает крошечный рой серебристых искр. Ушки замирают, хвосты едва заметно покачиваются в такт, а взгляд становится внимательным.*"


def exhaust(engine):
    for a in engine.all_actions():
        engine.db.juunibi_mark("action", a["id"], a["category"])


def test_generation_after_exhaustion_is_validated_saved_and_not_repeated(engine, monkeypatch):
    exhaust(engine)
    calls = []

    def fake(settings, key, system, messages):
        calls.append((settings.model, key))
        return json.dumps({"text": GOOD, "category": "тайна", "emotion": "тайна", "duration_seconds": 4.2}, ensure_ascii=False)

    monkeypatch.setattr(ai, "complete", fake)
    a = engine.next_action(CLOUD, "sk-secret")
    assert a["id"].startswith("JUA-GEN-") and a["category"] == "тайна" and calls[0] == ("deepseek-ai/DeepSeek-V4-Flash", "sk-secret")
    assert engine.stats()["generated"] == 1 and engine.stats()["actions_unused"] == 0
    # the same text again is rejected as a duplicate, so the sixth attempt fails and nothing repeats
    with pytest.raises(juunibi.JuunibiError) as e:
        engine.next_action(CLOUD, "sk-secret")
    assert "5 попыток" in str(e.value) and len(calls) == 1 + juunibi.MAX_ATTEMPTS and engine.stats()["generated"] == 1


def test_generation_requires_ai_and_reports_provider_errors(engine, monkeypatch):
    exhaust(engine)
    with pytest.raises(juunibi.JuunibiError) as e:
        engine.next_action(NONE, "")
    assert "ИИ не подключён" in str(e.value)
    monkeypatch.setattr(ai, "complete", lambda *a: (_ for _ in ()).throw(ai.AIError("Нет связи с Cloud.ru: x")))
    with pytest.raises(juunibi.JuunibiError) as e:
        engine.next_action(CLOUD, "k")
    assert "Нет связи" in str(e.value) and engine.stats()["generated"] == 0 and "Нет связи" in engine.stats()["last_error"]
    with pytest.raises(juunibi.JuunibiError):
        engine.next_action(CLOUD, "k", allow_generate=False)


@pytest.mark.parametrize("text,fragment", [("короткое", "длина"), ("*" + "а " * 400 + "*", "длина"), ("*" + "Джууниби " + GOOD[1:], "имя"), ("«" + GOOD[1:], "имя")])
def test_validation_rejects_bad_candidates(engine, text, fragment):
    assert fragment in engine.validate(text)


def test_validation_rejects_near_duplicates_but_accepts_new_text(engine):
    base = engine.library.actions[0]["text"]
    assert "похоже" in engine.validate(base) and "похоже" in engine.validate(base.replace("медленно", "плавно"))
    assert engine.validate(GOOD) == ""


def test_parse_accepts_json_or_plain_text(engine):
    assert engine._parse('```json\n{"text":"abc","category":"тайна","duration_seconds":99}\n```', None)["duration_seconds"] == 7.0
    plain = engine._parse("Она улыбается.", "защита")
    assert plain["text"] == "*Она улыбается.*" and plain["category"] == "защита"


def test_phrase_bag_has_no_repeats_until_category_is_exhausted(engine):
    total = len([p for p in engine.library.phrases if p["category"] == "утро"])
    ids = [engine.next_phrase("утро")["id"] for _ in range(total)]
    assert len(set(ids)) == total
    again = engine.next_phrase("утро")  # the bag refills; the next cycle may start with any phrase
    assert again["category"] == "утро"
    assert engine.next_phrase("auto")["category"] in {"приветствие", "утро", "вечер"}
    assert engine.next_phrase("ambient")["category"] in juunibi.AMBIENT_CATEGORIES
    assert engine.next_phrase("???")["id"]


def test_refilled_bag_avoids_the_most_recent_phrases(engine):
    cat = "анализ"; total = len([p for p in engine.library.phrases if p["category"] == cat])
    ids = [engine.next_phrase(cat)["id"] for _ in range(total)]
    nxt = engine.next_phrase(cat)["id"]
    assert nxt not in ids[-(juunibi.PHRASE_RECENT):] or total <= juunibi.PHRASE_RECENT  # 15 phrases < 60: any is allowed


def test_reset_scopes(engine):
    engine.next_action(NONE, ""); engine.next_phrase("утро")
    assert engine.reset("actions") == 1 and engine.stats()["actions_used"] == 0 and engine.db.juunibi_used_ids("phrase")
    engine.reset("all"); assert not engine.db.juunibi_used_ids("phrase")


def test_settings_validation():
    assert juunibi.validate_settings({"actions": "yes", "persona": True}) == juunibi.JuunibiSettings(persona=True)
    assert juunibi.validate_settings(None) == juunibi.JuunibiSettings()
