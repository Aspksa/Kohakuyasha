import json
import urllib.error
from pathlib import Path

import pytest

from core import ai, assistant, prefs


def test_validate_ai_clamps_and_rejects_bad_values():
    s = ai.validate_ai({"provider": "evil", "temperature": 7, "max_tokens": 10**9, "base_url": "file:///etc/passwd", "use_character": "yes"})
    assert s.provider == "cloudru" and s.temperature == 1.0 and s.max_tokens == 8192  # unknown/legacy providers fall back to Cloud.ru
    assert ai.validate_ai({"provider": "anthropic"}).provider == "cloudru" and ai.validate_ai({"provider": "none"}).provider == "none"
    assert s.base_url == "" and s.use_character is True
    assert ai.validate_ai({"temperature": True}).temperature is None
    assert ai.validate_ai({"base_url": "http://127.0.0.1:11434/v1/"}).base_url == "http://127.0.0.1:11434/v1"
    assert ai.validate_ai(None).provider == "cloudru"


def test_validate_avatar():
    a = prefs.validate_avatar({"crop": "x", "shape": "circle", "size": 9999, "ring": 1, "ring_color": "red", "left_action": "x"})
    assert (a.crop, a.shape, a.size, a.ring, a.ring_color, a.left_action) == ("face", "circle", 240, False, "#e8be56", "chat")
    assert prefs.validate_avatar({}).shape == "soft"  # circle is no longer the default
    assert prefs.validate_avatar({"active_face": "../x"}).active_face == "default"
    assert prefs.validate_avatar({"glow_color": "#AABBCC", "active_face": "0a1b2c3d"}).glow_color == "#aabbcc"


def test_secret_store_never_exposes_key(tmp_path: Path):
    store = ai.SecretStore(tmp_path / "data" / "secrets.json")
    assert not store.has_key() and store.hint("api_key") == ""
    store.set_key("sk-test-1234567890")
    assert store.get_key() == "sk-test-1234567890" and store.hint("api_key") == "…7890"
    public = ai.public_ai(ai.AISettings(), store)
    assert "sk-test" not in json.dumps(public) and public["has_key"] is True
    with pytest.raises(ValueError):
        store.set_key("has space")
    store.set("github_token", "ghp_abcdefgh1234")
    assert store.get("github_token") == "ghp_abcdefgh1234" and store.get_key() == "sk-test-1234567890"  # secrets do not clobber each other
    store.delete_key()
    assert not store.has_key() and store.hint("github_token") == "…1234"
    store.delete("github_token")
    assert not (tmp_path / "data" / "secrets.json").exists()  # an empty secrets file is removed


def test_normalize_history_alternates_and_starts_with_user():
    msgs = ai.normalize_history([
        {"role": "assistant", "content": "hi"}, {"role": "user", "content": "a"},
        {"role": "user", "content": "b"}, {"role": "assistant", "content": "c"}, {"role": "x", "content": "z"},
    ])
    assert msgs == [{"role": "user", "content": "a\n\nb"}, {"role": "assistant", "content": "c"}]


def test_cloudru_request_shape(monkeypatch):
    seen = {}

    def fake(url, headers, body):
        seen.update(url=url, headers=headers, body=body)
        return {"choices": [{"message": {"content": "Привет"}}]}

    monkeypatch.setattr(ai, "_http_post_json", fake)
    s = ai.AISettings(system_prompt="be brief")
    out = ai.complete(s, "key123456", ai.build_system_prompt(s, {"name": "K"}), [{"role": "user", "content": "x"}])
    assert out == "Привет"
    assert seen["url"] == "https://foundation-models.api.cloud.ru/v1/chat/completions"
    assert seen["headers"] == {"Authorization": "Bearer key123456"}
    assert seen["body"]["model"] == "deepseek-ai/DeepSeek-V4-Flash" and "temperature" not in seen["body"]
    assert seen["body"]["messages"][0]["role"] == "system" and '"name": "K"' in seen["body"]["messages"][0]["content"]
    pro = ai.AISettings(model="deepseek-ai/DeepSeek-V4-Pro", temperature=0.3, base_url="https://example.test/v1")
    ai.complete(pro, "key123456", "", [{"role": "user", "content": "x"}])
    assert seen["url"] == "https://example.test/v1/chat/completions" and seen["body"]["model"].endswith("V4-Pro") and seen["body"]["temperature"] == 0.3


def test_models_offered_are_deepseek_v4():
    ids = [m["id"] for m in ai.MODEL_SUGGESTIONS["cloudru"]]
    assert ids == ["deepseek-ai/DeepSeek-V4-Flash", "deepseek-ai/DeepSeek-V4-Pro"]
    assert ai.PROVIDERS == ("none", "cloudru")


def test_missing_key_and_disabled_errors():
    with pytest.raises(ai.AIError):
        ai.complete(ai.AISettings(provider="none"), "k", "", [{"role": "user", "content": "x"}])
    with pytest.raises(ai.AIError, match="ключ"):
        ai.complete(ai.AISettings(), "", "", [{"role": "user", "content": "x"}])


def test_http_error_is_sanitized(monkeypatch):
    import io

    def boom(url, headers, body):
        raise urllib.error.HTTPError(url, 401, "no", {}, io.BytesIO(b'{"error":"bad key sk-secret-999"}'))

    monkeypatch.setattr(ai, "_http_post_json", boom)
    with pytest.raises(ai.AIError) as exc:
        ai.complete(ai.AISettings(), "sk-secret-999", "", [{"role": "user", "content": "x"}])
    assert "401" in str(exc.value) and "sk-secret-999" not in str(exc.value)


def test_assistant_not_connected_message():
    msgs = [{"role": "user", "content": "hi"}]
    assert assistant.reply(ai.AISettings(), "", {}, msgs) == assistant.NOT_CONNECTED  # no key yet
    assert assistant.reply(ai.AISettings(provider="none"), "k", {}, msgs) == assistant.NOT_CONNECTED
    assert "Cloud.ru" in assistant.NOT_CONNECTED


def test_new_appearance_flags_are_validated():
    a = prefs.validate_app({"pattern": False, "petals": "no"})
    assert a.pattern is False and a.petals is True
    d = prefs.validate_app({})
    assert d.pattern is True and d.petals is True and d.theme == "dark"
