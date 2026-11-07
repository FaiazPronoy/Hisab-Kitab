from enum import Enum
import pytest

from app.pipeline.extract.providers import (
    PRICES, BudgetExceeded, LlmError, cost_of, get_total_spent, record_spent, reset_budget_counter,
)


class MockFinishReason(Enum):
    SAFETY = 1
    MAX_TOKENS = 2
    STOP = 3


def test_finish_reason_enum_handling():
    # Verify that enum .name attribute extraction matches correctly
    finish_safety = MockFinishReason.SAFETY
    finish_safety_str = getattr(finish_safety, "name", str(finish_safety)).upper()
    assert finish_safety_str in ("SAFETY", "BLOCKED", "PROHIBITED_CONTENT")

    finish_max = MockFinishReason.MAX_TOKENS
    finish_max_str = getattr(finish_max, "name", str(finish_max)).upper()
    assert finish_max_str == "MAX_TOKENS"


def test_gemini_36_flash_pricing():
    assert "gemini-3.6-flash" in PRICES
    pin, pout = PRICES["gemini-3.6-flash"]
    assert pin == 1.50 and pout == 7.50
    # Cost for 1M input tokens and 1M output tokens = $9.00
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
