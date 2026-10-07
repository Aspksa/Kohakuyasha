from core.security import is_allowed_host_header, is_allowed_origin, session_matches


def test_host_header_rules():
    assert is_allowed_host_header("127.0.0.1:8710", 8710)
    assert is_allowed_host_header("localhost", 8710)
    assert is_allowed_host_header("[::1]:8710", 8710)
    assert not is_allowed_host_header("127.0.0.1:9999", 8710)
    assert not is_allowed_host_header("evil.example", 8710)
    assert not is_allowed_host_header("127.0.0.1.evil.example:8710", 8710)
    assert not is_allowed_host_header(None, 8710)
    assert not is_allowed_host_header("", 8710)


def test_origin_rules():
    assert is_allowed_origin("http://127.0.0.1:8710", 8710)
    assert not is_allowed_origin("https://127.0.0.1:8710", 8710)
    assert not is_allowed_origin("http://127.0.0.1:1", 8710)
    assert not is_allowed_origin("http://evil.example:8710", 8710)
    assert not is_allowed_origin(None, 8710)
    assert not is_allowed_origin("null", 8710)


def test_session_matches():
    assert session_matches("abc", "abc")
    assert not session_matches("abc", "abd")
    assert not session_matches(None, "abc")
    assert not session_matches("", "")
