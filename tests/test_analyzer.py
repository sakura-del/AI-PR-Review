import json
from ai_pr_review.analyzer import parse_ai_response
from ai_pr_review.models import Severity


def test_parse_ai_response_valid_json():
    raw = json.dumps({
        "summary": {
            "intent": "Add auth",
            "scope": "Auth module",
            "key_changes": ["New auth.py"],
        },
        "findings": [
            {
                "type": "risk",
                "severity": "high",
                "confidence": 4,
                "expert": "security",
                "file": "auth.py",
                "line": 10,
                "title": "Hardcoded secret",
                "description": "Secret is hardcoded",
                "suggestion": "Use env var",
                "code_snippet": "secret = 'xxx'",
            }
        ],
        "suggestions": [],
    })
    result = parse_ai_response(raw)
    assert result.summary.intent == "Add auth"
    assert len(result.findings) == 1
    assert result.findings[0].severity == Severity.HIGH


def test_parse_ai_response_with_markdown_wrapper():
    raw = '```json\n{"summary": {"intent": "Fix bug", "scope": "Core", "key_changes": []}, "findings": [], "suggestions": []}\n```'
    result = parse_ai_response(raw)
    assert result.summary.intent == "Fix bug"


def test_parse_ai_response_invalid_json_returns_empty():
    result = parse_ai_response("not valid json at all")
    assert result.summary.intent == ""
    assert len(result.findings) == 0
