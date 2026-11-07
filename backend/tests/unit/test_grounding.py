import pytest

from app.pipeline.extract.grounding import number_on_page, value_in_quote
from app.pipeline.extract.run import normalize
from app.pipeline.extract.schema import InvoiceOut, LineItemOut


@pytest.mark.parametrize("val,quote,expected", [
    ("1,250.00", "Total 1,250.50 USD", False),
    ("10.00", "Balance 31.50", False),
    ("300.00", "Amount 3,075.00", False),
    ("1,250.00", "Total 1,250.00 USD", True),
    ("1250", "Total 1,250.00 USD", True),
    ("12.5", "Price 12.50 EUR", True),
])
def test_value_in_quote_decimal_precision(val, quote, expected):
    assert value_in_quote("amount", val, quote, "amount") is expected


@pytest.mark.parametrize("val,page,expected", [
    ("1,250.00", "Subtotal: 1,000.00\nTotal: 1,250.50", False),
    ("10.00", "Item A qty 2 price 31.50", False),
    ("300.00", "Summary: 3,075.00", False),
    ("1,250.00", "Total: 1,250.00", True),
    ("1250", "Total: 1,250.00", True),
    ("12.5", "Unit Price: 12.50", True),
])
def test_number_on_page_decimal_precision(val, page, expected):
    assert number_on_page(val, page) is expected


def test_line_item_grounding_rejects_hallucinated_qty_or_unit_price():
    fields = {
        "invoice_number": {"value_raw": "INV-1", "value_norm": "INV-1", "confidence": 0.9},
        "invoice_date": {"value_raw": "2026-01-01", "value_norm": "2026-01-01", "confidence": 0.9},
        "supplier_name": {"value_raw": "Acme", "value_norm": "Acme", "confidence": 0.9},
        "total": {"value_raw": "100.00", "value_norm": "100.00", "confidence": 0.9},
        "currency": {"value_raw": "USD", "value_norm": "USD", "confidence": 0.9},
        "subtotal": {"value_raw": None, "value_norm": None, "confidence": 0.0},
        "tax_amount": {"value_raw": None, "value_norm": None, "confidence": 0.0},
        "due_date": {"value_raw": None, "value_norm": None, "confidence": 0.0},
        "customer_name": {"value_raw": None, "value_norm": None, "confidence": 0.0},
    }
    # Printed quote has amount 100.00, but qty is 2 and unit price is 50.00
    # Model hallucinated qty 5 and unit price 20.00
    out = InvoiceOut(
        line_items=[
            LineItemOut(description="Widget", quantity="5", unit_price="20.00", amount="100.00",
                        quote="Widget 2 x 50.00 = 100.00")
        ]
    )
    res = normalize(fields, out, "Widget 2 x 50.00 = 100.00", [], [], "llm", 0.8)
    # The hallucinated item must NOT be verified because qty 5 and unit_price 20.00 are not in quote
    item = res["line_items"][0]
    assert not item["evidence"]["verified"]
    assert item["confidence"] == 0.4


def test_line_item_deduplication_by_line_id():
    items = [
        LineItemOut(description="Widget", quantity="2", unit_price="50.00", amount="100.00", line_id="P1:L10"),
        LineItemOut(description="Widget", quantity="2", unit_price="50.00", amount="100.00", line_id="P1:L10"),
        LineItemOut(description="Widget", quantity="2", unit_price="50.00", amount="100.00", line_id="P1:L11"),
    ]
    seen = set()
    deduped = []
    for it in items:
        key = it.line_id.strip() if it.line_id and it.line_id.strip() else (
            (it.description or "").strip().lower(), (it.amount or "").strip(), (it.quantity or "").strip()
        )
        if key not in seen:
            seen.add(key)
            deduped.append(it)
    assert len(deduped) == 2
    assert deduped[0].line_id == "P1:L10"
    assert deduped[1].line_id == "P1:L11"
