from datetime import date
from decimal import Decimal as D

import pytest

from app.pipeline.reconcile.engine import compare_copies, match_ledger
from app.pipeline.segment import segment
from app.pipeline.validate.duplicates import tier
from app.pipeline.validate.routing import route
from app.pipeline.validate.rules import check

TODAY = date(2026, 11, 6)
OK_META = {f: {"confidence": 0.95, "value_norm": "x", "source": "llm"} for f in
           ("invoice_number", "invoice_date", "supplier_name", "total", "currency")}


def inv(**kw):
    base = dict(invoice_number="INV-1", invoice_date=date(2026, 10, 1), supplier_name="Acme", customer_name="Globex",
                currency="USD", subtotal=D("100.00"), tax=D("10.00"), discount=None, shipping=None, total=D("110.00"),
                doc_type="invoice", due_date=None)
    base.update(kw)
    return base


ITEMS = [{"quantity": D("2"), "unit_price": D("25.00"), "amount": D("50.00")},
         {"quantity": D("1"), "unit_price": D("50.00"), "amount": D("50.00")}]


def codes(findings):
    return sorted(f["rule_code"] for f in findings)


def test_clean_invoice_has_no_findings_and_auto_validates():
    f = check(inv(), OK_META, ITEMS, [], [], TODAY)
    assert f == []
    assert route(f, OK_META) == "auto_validated"


@pytest.mark.parametrize("total,expect", [
    (D("110.02"), []),            # inside max(0.05, 0.01 per line)
    (D("110.05"), []),
    (D("110.10"), ["TOTAL_MATH"]),
    (D("111.00"), ["TOTAL_MATH"]),
])
def test_total_math_tolerance(total, expect):
    assert codes(check(inv(total=total), OK_META, ITEMS, [], [], TODAY)) == expect


def test_tax_inclusive_is_info_not_error():
    f = check(inv(total=D("100.00")), OK_META, ITEMS, [], [], TODAY)
    assert codes(f) == ["TAX_INCLUSIVE"] and f[0]["severity"] == "info"


@pytest.mark.parametrize("amount,sev", [(D("50.40"), "warning"), (D("52.00"), "error"), (D("50.02"), None)])
def test_line_math(amount, sev):
    items = [{"quantity": D("2"), "unit_price": D("25.00"), "amount": amount}, ITEMS[1]]
    f = [x for x in check(inv(subtotal=amount + D("50.00"), total=amount + D("60.00")), OK_META, items, [], [], TODAY)
         if x["rule_code"] == "LINE_MATH"]
    assert (f[0]["severity"] if f else None) == sev


def test_subtotal_sum_and_tax_lines():
    f = check(inv(subtotal=D("120.00"), total=D("130.00")), OK_META, ITEMS, [{"amount": D("9.00")}], [], TODAY)
    assert "SUBTOTAL_SUM" in codes(f) and "TAX_LINES" in codes(f)


def test_missing_and_ungrounded_fields():
    meta = {**OK_META, "total": {"null_reason": "unverified", "rejected_value": "999"}}
    f = check(inv(total=None, customer_name=None), meta, [], [], [], TODAY)
    c = codes(f)
    assert "GROUNDING_FAILED" in c and "OPT_MISSING" in c
    assert not any(x["rule_code"] == "REQ_MISSING" and x["field"] == "total" for x in f)
    assert route(f, meta) == "needs_review"


def test_dates_amounts_and_flags():
    f = check(inv(invoice_date=date(2027, 1, 1), total=D("-5"), subtotal=None, tax=None), OK_META, [], [],
              ["ambiguous_currency", "suspicious_content"], TODAY)
    c = codes(f)
    assert {"DATE_SANITY", "AMOUNT_SANITY", "CURRENCY", "SUSPICIOUS_CONTENT"} <= set(c)


def test_missing_tax_shows_up_as_an_unexplained_total():
    f = [x for x in check(inv(tax=None, total=D("110")), OK_META, ITEMS, [], [], TODAY) if x["rule_code"] == "TOTAL_MATH"]
    assert f and "tax line may be missing" in f[0]["message"]
    assert "TOTAL_MATH" not in codes(check(inv(tax=None, total=D("100")), OK_META, ITEMS, [], [], TODAY))


def test_credit_note_negative_total_is_fine():
    f = check(inv(doc_type="credit_note", subtotal=D("-100"), tax=D("-10"), total=D("-110")), OK_META, [], [], [], TODAY)
    assert "AMOUNT_SANITY" not in codes(f)


def test_routing_rules():
    warn = {"rule_code": "OPT_MISSING", "severity": "warning", "field": "x"}
    assert route([warn], OK_META) == "auto_validated"
    assert route([warn, warn], OK_META) == "needs_review"
    assert route([], {**OK_META, "total": {"value_norm": None}}) == "needs_review"
    assert route([], {**OK_META, "total": {"value_norm": None, "source": "user"}}) == "auto_validated"
    assert route([], OK_META, pages_failed=1) == "needs_review"


@pytest.mark.parametrize("b,want", [
    (dict(invoice_number_norm="INV1", total=D("10"), currency="USD"), "DUP_INVOICE"),
    (dict(invoice_number_norm="INV1", total=D("12"), currency="USD"), "DUP_CONFLICT"),
    (dict(invoice_number_norm="INV1O8", supplier_norm="acme trading", total=D("10"), currency="USD",
          invoice_date=date(2026, 1, 3)), "DUP_SUSPECTED"),
    (dict(invoice_number_norm="INV9", total=D("99"), currency="USD"), None),
])
def test_duplicate_tiers(b, want):
    from app.core.config import validation_config
    a = dict(supplier_norm="acme trading", invoice_number_norm="INV1", total=D("10"), currency="USD", invoice_date=date(2026, 1, 1))
    other = {**dict(supplier_norm="acme trading", invoice_date=date(2026, 1, 1)), **b}
    if want == "DUP_SUSPECTED":
        a["invoice_number_norm"] = "INV108"
    assert tier(a, other, validation_config()) == want


def test_same_number_with_slightly_different_supplier_is_suspected():
    from app.core.config import validation_config
    a = dict(supplier_norm="acme trading", invoice_number_norm="INV1", total=D("10"), currency="USD", invoice_date=date(2026, 1, 1))
    b = {**a, "supplier_norm": "acme tradinq"}
    assert tier(a, b, validation_config()) == "DUP_SUSPECTED"


def test_segmenter_splits_on_new_invoice_numbers_and_blank_pages():
    pages = ["ACME\nINVOICE\nInvoice No: A-100\nItem 1\nTotal 10.00",
             "ACME\nInvoice No: A-100\nDescription Qty\nmore items\nTotal 20.00",
             "",
             "GLOBEX\nTAX INVOICE\nInvoice No: G-7\nTotal 5.00",
             "GLOBEX\nPage 2 of 2\nDescription\nTotal 5.00"]
    assert [(s["page_start"], s["page_end"]) for s in segment(pages)] == [(1, 2), (4, 5)]


def test_ledger_matching_finds_planted_discrepancies():
    ref = {"x": 1}
    invoices = [dict(invoice_number_norm="A1", supplier_norm="acme", invoice_date=date(2026, 1, 1), total=D("100"), currency="USD", ref=ref),
                dict(invoice_number_norm="A2", supplier_norm="acme", invoice_date=date(2026, 1, 2), total=D("50"), currency="USD", ref=ref),
                dict(invoice_number_norm="A3", supplier_norm="acme", invoice_date=date(2026, 1, 3), total=D("70"), currency="USD", ref=ref)]
    ledger = [dict(invoice_number_norm="A1", supplier_norm="acme", invoice_date=date(2026, 1, 1), total=D("100"), currency="USD", ref=ref),
              dict(invoice_number_norm="A2", supplier_norm="acme", invoice_date=date(2026, 1, 2), total=D("55"), currency="USD", ref=ref),
              dict(invoice_number_norm="Z9", supplier_norm="initech", invoice_date=date(2026, 1, 9), total=D("10"), currency="USD", ref=ref)]
    cats = sorted(i["category"] for i in match_ledger(invoices, ledger))
    assert cats == ["amount_mismatch", "matched", "missing_in_invoices", "missing_in_ledger"]


def test_copy_compare_pairs_line_items():
    ref = {}
    a = dict(invoice_number="1", total=D("30"), ref=ref)
    b = dict(invoice_number="1", total=D("31"), ref=ref)
    out = compare_copies(a, b, [{"description": "Bolts M6", "amount": D("10")}, {"description": "Nuts", "amount": D("20")}],
                         [{"description": "Nuts", "amount": D("21")}, {"description": "Bolts M6", "amount": D("10")}])
    assert sorted(i["category"] for i in out) == ["field_diff", "line_amount_mismatch"]
