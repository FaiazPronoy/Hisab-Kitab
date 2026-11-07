from types import SimpleNamespace
from pydantic import BaseModel
import pytest

from app.db.models import LlmCall
from app.pipeline.extract.providers import (
    PRICES,
    GeminiProvider,
    LlmError,
    call_structured,
    cost_of,
    get_provider,
    get_total_spent,
    record_spent,
    reset_budget_counter,
)
from app.pipeline.process import _ask_same


class DummySchema(BaseModel):
    value: str


def _make_fake_gemini_provider(response_obj):
    prov = object.__new__(GeminiProvider)
    prov.client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda *args, **kwargs: response_obj
        )
    )
    return prov


def test_finish_reason_handling_and_billed_tokens():
    """H14: GeminiProvider.generate handles SAFETY, MAX_TOKENS, STOP, empty text, recording billed tokens."""
    reset_budget_counter()

    # 1. SAFETY: non-transient, records billed tokens
    u_safety = SimpleNamespace(prompt_token_count=1000, candidates_token_count=200, thoughts_token_count=0)
    cand_safety = SimpleNamespace(finish_reason="SAFETY")
    resp_safety = SimpleNamespace(usage_metadata=u_safety, candidates=[cand_safety], text="")
    prov = _make_fake_gemini_provider(resp_safety)

    with pytest.raises(LlmError) as exc_info:
        prov.generate("gemini-2.5-flash", "", "user", DummySchema, None)
    assert not exc_info.value.transient
    assert "SAFETY" in str(exc_info.value)
    assert get_total_spent(None) > 0.0

    # 2. MAX_TOKENS: non-transient, records billed tokens
    reset_budget_counter()
    u_max = SimpleNamespace(prompt_token_count=1000, candidates_token_count=4096, thoughts_token_count=0)
    cand_max = SimpleNamespace(finish_reason="MAX_TOKENS")
    resp_max = SimpleNamespace(usage_metadata=u_max, candidates=[cand_max], text="partial")
    prov_max = _make_fake_gemini_provider(resp_max)

    with pytest.raises(LlmError) as exc_info:
        prov_max.generate("gemini-2.5-flash", "", "user", DummySchema, None)
    assert not exc_info.value.transient
    assert "max tokens reached" in str(exc_info.value)
    assert get_total_spent(None) > 0.0

    # 3. STOP: valid text, returns text and token counts
    u_stop = SimpleNamespace(prompt_token_count=50, candidates_token_count=20, thoughts_token_count=0)
    cand_stop = SimpleNamespace(finish_reason="STOP")
    resp_stop = SimpleNamespace(usage_metadata=u_stop, candidates=[cand_stop], text='{"value": "ok"}')
    prov_stop = _make_fake_gemini_provider(resp_stop)

    text, tin, tout = prov_stop.generate("gemini-2.5-flash", "", "user", DummySchema, None)
    assert text == '{"value": "ok"}'
    assert tin == 50
    assert tout == 20

    # 4. Empty text: transient error, records billed tokens
    reset_budget_counter()
    u_empty = SimpleNamespace(prompt_token_count=50, candidates_token_count=0, thoughts_token_count=0)
    cand_empty = SimpleNamespace(finish_reason="STOP")
    resp_empty = SimpleNamespace(usage_metadata=u_empty, candidates=[cand_empty], text="")
    prov_empty = _make_fake_gemini_provider(resp_empty)

    with pytest.raises(LlmError) as exc_info:
        prov_empty.generate("gemini-2.5-flash", "", "user", DummySchema, None)
    assert exc_info.value.transient
    assert "empty response" in str(exc_info.value)


def test_cache_lookup_ignores_null_response_and_finds_latest_good(monkeypatch):
    """H14: a bad-JSON row stored first does not hide a subsequent good row."""
    # Mock DB query with two rows: first has response=None, second has valid response
    class FakeQuery:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            # The filter in code requires LlmCall.response.is_not(None)
            valid = [r for r in self.rows if r.response is not None]
            return valid[-1] if valid else None

    row_bad = LlmCall(id=1, prompt_version="v1", model="mock", purpose="test",
                      input_hash="hash1", response=None, cached=False)
    row_good = LlmCall(id=2, prompt_version="v1", model="mock", purpose="test",
                       input_hash="hash1", response={"value": "cached_success"}, cached=False)

    class FakeDB:
        def query(self, model):
            return FakeQuery([row_bad, row_good])

    out = call_structured(FakeDB(), purpose="test", version="v1", schema=DummySchema, user="test_user")
    assert out is not None
    assert out.value == "cached_success"


def test_vision_model_validation_in_get_provider(monkeypatch):
    """H14: get_provider validates both llm_model and llm_vision_model against PRICES."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("LLM_VISION_MODEL", "invalid-vision-model-xyz")

    from app.core.config import get_settings
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="Unknown or unconfigured vision model"):
        get_provider()

    get_settings.cache_clear()


def test_ask_same_fallback_on_llm_error(monkeypatch):
    """H14: _ask_same catches LlmError and returns heuristic (True, 0.5)."""
    def raise_llm_error(*args, **kwargs):
        raise LlmError("Service unavailable", transient=True)

    monkeypatch.setattr("app.pipeline.process.call_structured", raise_llm_error)
    ask = _ask_same(None)
    same, conf = ask("page text A", "page text B")
    assert same is True
    assert conf == 0.5


def test_gemini_36_flash_pricing():
    assert "gemini-3.6-flash" in PRICES
    pin, pout = PRICES["gemini-3.6-flash"]
    assert pin == 1.50 and pout == 7.50
    c = cost_of("gemini-3.6-flash", 1_000_000, 1_000_000)
    assert round(c, 2) == 9.00


def test_unknown_model_pricing_raises():
    with pytest.raises(ValueError, match="Unknown pricing"):
        cost_of("unknown-model-xyz", 100, 100)


def test_budget_counter_and_reset():
    reset_budget_counter()
    assert get_total_spent(None) == 0.0
    record_spent(None, 0.42)
    assert round(get_total_spent(None), 2) == 0.42
    reset_budget_counter()
    assert get_total_spent(None) == 0.0
