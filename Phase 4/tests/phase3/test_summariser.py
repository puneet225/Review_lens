from review_pulse.analysis.summariser import parse_summary, _build_prompt
from review_pulse.store.models import Review
from datetime import datetime


def _r(body):
    return Review(source="appstore", product="groww", rating=4,
                  body=body, raw_body=body, date=datetime.utcnow(), review_id="r0")


def test_parse_summary_forces_fixed_name():
    data = {"name": "LLM Invented Name", "sentiment": "positive",
            "description": "users like it", "quotes": ["love this app"], "action": None}
    res = parse_summary(data, fixed_name="💚 What Users Love", cluster_id=0, tokens_used=42)
    assert res.name == "💚 What Users Love"
    assert res.sentiment == "POSITIVE"
    assert res.raw_quotes == ["love this app"]
    assert res.tokens_used == 42


def test_build_prompt_has_no_existing_names_and_names_category():
    prompt = _build_prompt("💸 Fees & Charges", [_r("brokerage is too high")])
    assert "existing_theme_names" not in prompt
    assert "💸 Fees & Charges" in prompt
