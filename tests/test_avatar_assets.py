import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def test_avatar_widget_is_wired_into_index():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for needle in ('id="avatar"', 'id="chat-panel"', 'id="cabinet-panel"', "/static/avatar.css", "/static/theme.js"):
        assert needle in html
    scripts = re.findall(r'src="/static/([\w.-]+\.js)"', html)
    assert {"core.js", "avatar.js", "panels.js", "chat.js", "cabinet.js", "cab-avatar.js", "cab-ai.js", "cab-memory.js", "overview.js", "settings.js", "update.js"} <= set(scripts)
    for script in scripts:
        assert (WEB / "static" / script).stat().st_size > 0, script
    for asset in ("avatar.png", "avatar-small.png", "avatar-full.png", "avatar.css", "app.css", "pattern.svg"):
        assert (WEB / "static" / asset).stat().st_size > 0


def test_removed_pages_are_gone_from_the_menu():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for gone in ('data-page="observe"', 'data-page="tests"', 'data-page="journal"', "Журнал событий", "mini-events"):
        assert gone not in html
    assert 'data-page="overview"' in html and 'data-page="settings"' in html
    assert 'data-page="update"' in html and 'id="page-update"' in html
    for gone in ('id="clock-time"', 'id="cal-grid"', "calendar-card", "clock-card"):
        assert gone not in html


def test_ui_respects_strict_csp():
    # CSP is style-src/script-src 'self': no inline handlers or style attributes.
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"\son\w+\s*=", html)
    assert "style=" not in html
    for path in sorted((WEB / "static").glob("*.js")):
        js = path.read_text(encoding="utf-8")
        assert "innerHTML" not in js and "insertAdjacentHTML" not in js  # chat text is untrusted: DOM nodes only
        assert "eval(" not in js
