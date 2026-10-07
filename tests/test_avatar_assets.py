import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def test_avatar_widget_is_wired_into_index():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for needle in ('id="avatar"', 'id="chat-panel"', 'id="cabinet-panel"', "/static/avatar.js", "/static/avatar.css"):
        assert needle in html
    for asset in ("avatar.js", "avatar.css", "avatar.png", "avatar-small.png"):
        assert (WEB / "static" / asset).stat().st_size > 0


def test_ui_respects_strict_csp():
    # CSP is style-src/script-src 'self': no inline handlers or style attributes.
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"\son\w+\s*=", html)
    assert "style=" not in html
    js = (WEB / "static" / "avatar.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js  # chat text is untrusted: textContent only
