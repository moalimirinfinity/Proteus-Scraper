from scraper.detector import detect_blocked_response, detect_empty_parse
from scraper.parsing import SelectorSpec


def test_detect_blocked_response_status() -> None:
    reason = detect_blocked_response(403, {}, "https://example.com", "<html></html>")
    assert reason == "http_403"


def test_detect_blocked_response_title() -> None:
    html = "<html><head><title>Access Denied</title></head><body></body></html>"
    reason = detect_blocked_response(200, {}, "https://example.com", html)
    assert reason == "blocked_title"


def test_detect_blocked_response_script_marker() -> None:
    html = "<html><body><script>var x='cf-chl';</script></body></html>"
    reason = detect_blocked_response(200, {}, "https://example.com", html)
    assert reason == "challenge_script"


def test_detect_empty_parse_requires_required_fields() -> None:
    selectors = [
        SelectorSpec(field="title", selector="h1", data_type="string", required=True),
    ]
    reason = detect_empty_parse(200, {}, selectors)
    assert reason == "empty_parse"


def test_detect_empty_parse_ignores_optional_only() -> None:
    selectors = [
        SelectorSpec(field="subtitle", selector="h2", data_type="string", required=False),
    ]
    reason = detect_empty_parse(200, {}, selectors)
    assert reason is None
