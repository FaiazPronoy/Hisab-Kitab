import pytest

from app.pipeline.extract.grounding import number_on_page, quote_score, value_in_quote
from app.pipeline.extract.run import dedupe_line_items, normalize
from app.pipeline.extract.schema import InvoiceOut, LineItemOut
from app.pipeline.validate.routing import route
from app.pipeline.validate.rules import check


@pytest.mark.parametrize("field,val,quote,kind,expected", [
    ("total", "10.00", "Total 1,000", "amount", False),
    ("total", "1.25", "Total 1,250", "amount", False),
    ("total", "125", "Total 1.25", "amount", False),
])
def test_h1_cross_style_repro(field, val, quote, kind, expected):
    assert value_in_quote(field, val, quote, kind) is expected


@pytest.mark.parametrize("field,val,quote,kind,style,expected", [
    ("total", "1,250.00", "Total 1,250.00", "amount", "us", True),
    ("total", "1250", "Total 1,250.00", "amount", "us", True),
    ("total", "12.5", "Price 12.50", "amount", "us", True),
    ("total", "1250.00", "Total 1.250,00", "amount", "eu", True),
    ("total", "1250", "Total 1.250,00", "amount", "eu", True),
    ("total", "12.5", "Price 12,50", "amount", "eu", True),
    ("total", "-1250.00", "Total (1,250.00)", "amount", "us", True),
    ("total", "-1250.00", "Total -1,250.00", "amount", "us", True),
    ("total", "1250.00", "Total $1,250.00", "amount", "us", True),
    ("total", "1250.00", "Total €1.250,00", "amount", "eu", True),
    ("total", "10.00", "Total 1,000", "amount", "us", False),
    ("total", "1.25", "Total 1,250", "amount", "us", False),
    ("total", "125", "Total 1.25", "amount", "us", False),
    ("total", "1.25", "Total 1.250", "amount", "eu", False),
    ("total", "1250.00", "Total 1.250", "amount", "eu", True),
])
def test_h1_table_driven_decimal_matching(field, val, quote, kind, style, expected):
    assert value_in_quote(field, val, quote, kind, style=style) is expected


@pytest.mark.parametrize("val,quote,expected", [
    ("INV-1050", "Invoice No: INV-1060", False),
    ("INV-10234", "INV-10284", False),
    ("INV-2024-0001", "INV-2024-0007", False),
])
def test_h2_identifiers_repro(val, quote, expected):
    assert value_in_quote("invoice_number", val, quote, "text") is expected


@pytest.mark.parametrize("field,val,quote,kind,expected", [
    ("invoice_number", "INV-1050", "Invoice No: INV-1060", "text", False),
    ("invoice_number", "INV-10234", "INV-10284", "text", False),
    ("invoice_number", "INV-2024-0001", "INV-2024-0007", "text", False),
    ("invoice_number", "INV-1050", "Invoice: INV-1050", "text", True),
    ("po_number", "PO-9942", "P.O. Number: PO-9942", "text", True),
    ("po_number", "PO-9942", "P.O. Number: PO-9943", "text", False),
    ("supplier_name", "Acme Corporation", "From: Acme Corporation Ltd.", "text", True),
    ("supplier_name", "Acme Corp 1", "From: Acme Corp 2", "text", False),
    ("customer_name", "Global Logistics", "Bill To: Global Logistics Inc", "text", True),
    ("currency", "USD", "Total: $1,250.00", "currency", True),
    ("currency", "USD", "Total: USD 1250.00", "currency", True),
    ("currency", "EUR", "Total: €1.250,00", "currency", True),
    ("currency", "EUR", "Total: $1,250.00", "currency", False),
    ("currency", "GBP", "Total: £99.00", "currency", True),
    ("invoice_date", "2026-04-03", "Date: 03/04/2026", "date", True),
    ("invoice_date", "2026-12-25", "Date: 03/04/2026", "date", False),
    ("invoice_date", "2026-01-15", "Date: 15 Jan 2026", "date", True),
    ("due_date", "2026-05-20", "Due: 2026-05-20", "date", True),
    ("due_date", "2026-05-20", "Due: 2026-05-21", "date", False),
])
def test_h2_identifiers_names_dates_currency(field, val, quote, kind, expected):
    assert value_in_quote(field, val, quote, kind) is expected


def test_h2_ocr_noise_quote_vs_page():
    page_text = "Invoice No: INV-105O Date: 2026-01-01"
    quote = "Invoice No: INV-105O"
    val = "INV-105O"
    assert quote_score(quote, page_text) >= 0.9
    assert value_in_quote("invoice_number", val, quote, "text") is True


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


def test_line_item_grounding_nulls_hallucinations_and_routes_to_needs_review():
    fields = {
        "invoice_number": {"value_raw": "INV-1", "value_norm": "INV-1", "confidence": 0.9, "null_reason": None},
        "invoice_date": {"value_raw": "2026-01-01", "value_norm": "2026-01-01", "confidence": 0.9, "null_reason": None},
        "supplier_name": {"value_raw": "Acme", "value_norm": "Acme", "confidence": 0.9, "null_reason": None},
        "total": {"value_raw": "100.00", "value_norm": "100.00", "confidence": 0.9, "null_reason": None},
        "currency": {"value_raw": "USD", "value_norm": "USD", "confidence": 0.9, "null_reason": None},
        "subtotal": {"value_raw": "100.00", "value_norm": "100.00", "confidence": 0.9, "null_reason": None},
        "tax_amount": {"value_raw": None, "value_norm": None, "confidence": 0.0, "null_reason": "not_on_document"},
        "due_date": {"value_raw": None, "value_norm": None, "confidence": 0.0, "null_reason": "not_on_document"},
        "customer_name": {"value_raw": None, "value_norm": None, "confidence": 0.0, "null_reason": "not_on_document"},
    }
    line = {"id": "P1:L5", "text": "Widget 2 x 50.00 = 100.00", "bbox": [0.1, 0.2, 0.8, 0.25], "conf": 0.95}
    full_text = "Acme\nInvoice INV-1\nDate: 2026-01-01\nWidget 2 x 50.00 = 100.00\nTotal: 100.00"

    # Hallucinated quantity 5 and unit_price 20.00 against real line "Widget 2 x 50.00 = 100.00"
    out = InvoiceOut(
        line_items=[
            LineItemOut(description="Widget", quantity="5", unit_price="20.00", amount="100.00",
                        quote="Widget 2 x 50.00 = 100.00", line_id="P1:L5")
        ]
    )
    res = normalize(fields, out, full_text, [line], [], "llm", 0.8)
    item = res["line_items"][0]

    # Hallucinated qty and unit_price must be nulled
    assert item["quantity"] is None
    assert item["unit_price"] is None
    assert item["amount"] == "100.00"
    assert not item["evidence"]["verified"]
    assert "quantity" in item["evidence"]["rejected"]
    assert "unit_price" in item["evidence"]["rejected"]
    assert item["evidence"]["bbox"] == [0.1, 0.2, 0.8, 0.25]
    assert item["evidence"]["page"] == 1

    from datetime import date as d_cls
    from decimal import Decimal
    inv_typed = {
        "invoice_number": "INV-1", "invoice_date": d_cls(2026, 1, 1), "supplier_name": "Acme",
        "total": Decimal("100.00"), "subtotal": Decimal("100.00"), "currency": "USD",
    }
    findings = check(inv_typed, res["fields"], res["line_items"], res["tax_lines"], res["flags"])
    # Finding must exist for line_items[0].quantity
    grounding_failures = [f for f in findings if f["rule_code"] == "GROUNDING_FAILED"]
    assert any(f["field"] == "line_items[0].quantity" and f["severity"] == "critical" for f in grounding_failures)
    assert any(f["field"] == "line_items[0].unit_price" and f["severity"] == "critical" for f in grounding_failures)

    # Must route to needs_review due to critical GROUNDING_FAILED finding
    status = route(findings, res["fields"])
    assert status == "needs_review"


def test_line_item_grounding_correct_item_stays_verified():
    fields = {
        "invoice_number": {"value_raw": "INV-1", "value_norm": "INV-1", "confidence": 0.9, "null_reason": None},
        "invoice_date": {"value_raw": "2026-01-01", "value_norm": "2026-01-01", "confidence": 0.9, "null_reason": None},
        "supplier_name": {"value_raw": "Acme", "value_norm": "Acme", "confidence": 0.9, "null_reason": None},
        "total": {"value_raw": "100.00", "value_norm": "100.00", "confidence": 0.9, "null_reason": None},
        "currency": {"value_raw": "USD", "value_norm": "USD", "confidence": 0.9, "null_reason": None},
        "subtotal": {"value_raw": "100.00", "value_norm": "100.00", "confidence": 0.9, "null_reason": None},
        "tax_amount": {"value_raw": None, "value_norm": None, "confidence": 0.0, "null_reason": "not_on_document"},
        "due_date": {"value_raw": None, "value_norm": None, "confidence": 0.0, "null_reason": "not_on_document"},
        "customer_name": {"value_raw": None, "value_norm": None, "confidence": 0.0, "null_reason": "not_on_document"},
    }
    line = {"id": "P1:L5", "text": "Widget 2 x 50.00 = 100.00", "bbox": [0.1, 0.2, 0.8, 0.25], "conf": 0.95}
    full_text = "Acme\nInvoice INV-1\nDate: 2026-01-01\nWidget 2 x 50.00 = 100.00\nTotal: 100.00"

    out = InvoiceOut(
        line_items=[
            LineItemOut(description="Widget", quantity="2", unit_price="50.00", amount="100.00",
                        quote="Widget 2 x 50.00 = 100.00", line_id="P1:L5")
        ]
    )
    res = normalize(fields, out, full_text, [line], [], "llm", 0.8)
    item = res["line_items"][0]

    assert item["quantity"] == "2"
    assert item["unit_price"] == "50.00"
    assert item["amount"] == "100.00"
    assert item["evidence"]["verified"] is True
    assert item["evidence"]["rejected"] == []
    assert item["evidence"]["bbox"] == [0.1, 0.2, 0.8, 0.25]
    assert item["evidence"]["page"] == 1


def test_line_item_deduplication_via_run_dedupe():
    items = [
        LineItemOut(description="Widget", quantity="2", unit_price="50.00", amount="100.00", line_id="P1:L10"),
        LineItemOut(description="Widget", quantity="2", unit_price="50.00", amount="100.00", line_id="P1:L10"),
        LineItemOut(description="Widget", quantity="2", unit_price="50.00", amount="100.00", line_id="P1:L11"),
    ]
    deduped = dedupe_line_items(items)
    assert len(deduped) == 2
    assert deduped[0].line_id == "P1:L10"
    assert deduped[1].line_id == "P1:L11"
