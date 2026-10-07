import json
import urllib.error
from pathlib import Path

import pytest

from core import ai, assistant, prefs


def test_validate_ai_clamps_and_rejects_bad_values():
    s = ai.validate_ai({"provider": "evil", "temperature": 7, "max_tokens": 10**9, "base_url": "file:///etc/passwd", "use_character": "yes"})
    assert s.provider == "none" and s.temperature == 1.0 and s.max_tokens == 8192
    assert s.base_url == "" and s.use_character is True
    assert ai.validate_ai({"temperature": True}).temperature is None
    assert ai.validate_ai({"base_url": "http://127.0.0.1:11434/v1/"}).base_url == "http://127.0.0.1:11434/v1"
    assert ai.validate_ai(None).provider == "none"


def test_validate_avatar():
    a = prefs.validate_avatar({"crop": "x", "shape": "circle", "size": 9999, "ring": 1, "ring_color": "red", "left_action": "x"})
    assert (a.crop, a.shape, a.size, a.ring, a.ring_color, a.left_action) == ("face", "circle", 240, False, "#e8be56", "chat")
    assert prefs.validate_avatar({}).shape == "soft"  # circle is no longer the default
    assert prefs.validate_avatar({"active_face": "../x"}).active_face == "default"
    assert prefs.validate_avatar({"glow_color": "#AABBCC", "active_face": "0a1b2c3d"}).glow_color == "#aabbcc"


def test_secret_store_never_exposes_key(tmp_path: Path):
    store = ai.SecretStore(tmp_path / "data" / "secrets.json")
    assert not store.has_key() and store.hint() == ""
    store.set_key("sk-test-1234567890")
    assert store.get_key() == "sk-test-1234567890" and store.hint() == "…7890"
    public = ai.public_ai(ai.AISettings(), store)
    assert "sk-test" not in json.dumps(public) and public["has_key"] is True
    with pytest.raises(ValueError):
        store.set_key("has space")
    store.delete_key()
    assert not store.has_key()


def test_normalize_history_alternates_and_starts_with_user():
    msgs = ai.normalize_history([
        {"role": "assistant", "content": "hi"}, {"role": "user", "content": "a"},
        {"role": "user", "content": "b"}, {"role": "assistant", "content": "c"}, {"role": "x", "content": "z"},
    ])
    assert msgs == [{"role": "user", "content": "a\n\nb"}, {"role": "assistant", "content": "c"}]


def test_anthropic_request_shape(monkeypatch):
    seen = {}

    def fake(url, headers, body):
        seen.update(url=url, headers=headers, body=body)
        return {"content": [{"type": "text", "text": "Привет"}]}

    monkeypatch.setattr(ai, "_http_post_json", fake)
    s = ai.AISettings(provider="anthropic", system_prompt="be brief")
    out = ai.complete(s, "key123456", ai.build_system_prompt(s, {"name": "K"}), [{"role": "user", "content": "x"}])
    assert out == "Привет"
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "key123456"
    assert "temperature" not in seen["body"] and "be brief" in seen["body"]["system"] and '"name": "K"' in seen["body"]["system"]
    assert seen["body"]["model"] == ai.DEFAULT_MODELS["anthropic"]


def test_openai_compatible_local_needs_no_key(monkeypatch):
    seen = {}

    def fake(url, headers, body):
        seen.update(url=url, headers=headers, body=body)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(ai, "_http_post_json", fake)
    s = ai.AISettings(provider="openai", base_url="http://127.0.0.1:11434/v1", temperature=0.3, model="llama3")
    assert ai.complete(s, "", "sys", [{"role": "user", "content": "x"}]) == "ok"
    assert seen["url"] == "http://127.0.0.1:11434/v1/chat/completions" and "Authorization" not in seen["headers"]
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"} and seen["body"]["temperature"] == 0.3


def test_missing_key_and_provider_errors(monkeypatch):
    with pytest.raises(ai.AIError):
        ai.complete(ai.AISettings(provider="none"), "", "", [{"role": "user", "content": "x"}])
    with pytest.raises(ai.AIError, match="ключ"):
        ai.complete(ai.AISettings(provider="anthropic"), "", "", [{"role": "user", "content": "x"}])


def test_http_error_is_sanitized(monkeypatch):
    import io

    def boom(url, headers, body):
        raise urllib.error.HTTPError(url, 401, "no", {}, io.BytesIO(b'{"error":"bad key sk-secret-999"}'))

    monkeypatch.setattr(ai, "_http_post_json", boom)
    with pytest.raises(ai.AIError) as exc:
        ai.complete(ai.AISettings(provider="anthropic"), "sk-secret-999", "", [{"role": "user", "content": "x"}])
    assert "401" in str(exc.value) and "sk-secret-999" not in str(exc.value)


def test_assistant_not_connected_message():
    out = assistant.reply(ai.AISettings(), "", {}, [{"role": "user", "content": "hi"}])
    assert out == assistant.NOT_CONNECTED
