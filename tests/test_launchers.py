from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_batch_files_are_ascii_crlf_and_do_not_pass_trailing_backslash():
    for path in [*ROOT.glob("*.bat"), *(ROOT / "scripts").glob("*.bat")]:
        raw = path.read_bytes()
        raw.decode("ascii")  # cmd.exe mis-parses UTF-8 multibyte text
        assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), path.name
        text = raw.decode("ascii")
        assert '%~dp0"' not in text, path.name  # trailing backslash escapes the closing quote


def test_root_launcher_strips_trailing_backslash():
    text = (ROOT / "Kohakuyasha.bat").read_text(encoding="ascii")
    assert 'set "KOH_ROOT=%~dp0."' in text
