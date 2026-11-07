from datetime import date
from decimal import Decimal
import pytest

from app.db.models import Document, ExtractedField, Invoice, LineItem
from app.db.session import SessionLocal
from app.pipeline.process import revalidate
from app.pipeline.validate import duplicates, rules

pytestmark = pytest.mark.usefixtures("db_ready")


def _add_key_fields(db, inv: Invoice):
    fields = [
        ("invoice_number", inv.invoice_number),
        ("invoice_date", str(inv.invoice_date)),
        ("supplier_name", inv.supplier_name),
        ("customer_name", inv.customer_name or "Test Customer"),
        ("subtotal", str(inv.subtotal or inv.total)),
        ("tax", str(inv.tax or Decimal("0.00"))),
        ("total", str(inv.total)),
        ("currency", inv.currency),
    ]
    for name, val in fields:
        f = ExtractedField(
            invoice_id=inv.id,
            name=name,
            value_norm=val,
            value_raw=val,
            confidence=0.99,
            verified=True,
            source="model",
        )
        db.add(f)
    # Add matching line item so SUBTOTAL_SUM passes
    li = LineItem(
        invoice_id=inv.id,
        idx=0,
        description="Services",
        quantity=Decimal("1"),
        unit_price=inv.subtotal or inv.total,
        amount=inv.subtotal or inv.total,
        confidence=0.99,
    )
    db.add(li)
    db.flush()


def _create_test_doc(db, tag="default"):
    doc = Document(
        sha256=f"sha256_{tag}",
        filename=f"doc_{tag}.pdf",
        mime="application/pdf",
        size_bytes=2048,
        storage_key=f"storage_{tag}.pdf",
        kind="pdf",
        status="done",
        page_count=1,
    )
    db.add(doc)
    db.flush()
    return doc


def test_h12_missing_subtotal_derived_total_math():
    """H12: missing subtotal derived from line items and verified against total."""
    # 1. Matching total: items amount = 100, tax = 10, total = 110 -> valid (no TOTAL_MATH error)
    inv = {
        "subtotal": None,
        "tax": Decimal("10.00"),
        "total": Decimal("110.00"),
        "discount": None,
        "shipping": None,
        "invoice_date": date(2025, 1, 1),
    }
    items = [
        {"amount": Decimal("40.00")},
        {"amount": Decimal("60.00")},
    ]
    findings = rules.check(inv, {}, items, [], [])
    math_findings = [f for f in findings if f["rule_code"] == "TOTAL_MATH"]
    assert len(math_findings) == 0

    # 2. Wrong total: items amount = 100, tax = 10, total = 150 -> TOTAL_MATH error
    inv_wrong = {
        "subtotal": None,
        "tax": Decimal("10.00"),
        "total": Decimal("150.00"),
        "discount": None,
        "shipping": None,
        "invoice_date": date(2025, 1, 1),
    }
    findings_wrong = rules.check(inv_wrong, {}, items, [], [])
    math_findings_wrong = [f for f in findings_wrong if f["rule_code"] == "TOTAL_MATH"]
    assert len(math_findings_wrong) == 1
    assert "Derived subtotal" in math_findings_wrong[0]["message"]
    assert str(math_findings_wrong[0]["expected"]) == "110.00"
    assert str(math_findings_wrong[0]["actual"]) == "150.00"


def test_h12_derived_subtotal_tolerances():
    """H12: test at and around tolerance bounds for derived subtotal."""
    # total_abs tolerance is 0.05, total_per_line is 0.01 per line
    # For 2 lines, allowed is max(0.05, 0.02) = 0.05
    items = [{"amount": Decimal("50.00")}, {"amount": Decimal("50.00")}]  # sum = 100.00
    tax = Decimal("10.00")

    # Within tolerance (diff = 0.04) -> no error
    inv_within = {"subtotal": None, "tax": tax, "total": Decimal("110.04"), "invoice_date": date(2025, 1, 1)}
    f_within = [f for f in rules.check(inv_within, {}, items, [], []) if f["rule_code"] == "TOTAL_MATH"]
    assert len(f_within) == 0

    # Exactly at tolerance (diff = 0.05) -> no error
    inv_at = {"subtotal": None, "tax": tax, "total": Decimal("110.05"), "invoice_date": date(2025, 1, 1)}
    f_at = [f for f in rules.check(inv_at, {}, items, [], []) if f["rule_code"] == "TOTAL_MATH"]
    assert len(f_at) == 0

    # Beyond tolerance (diff = 0.06) -> TOTAL_MATH error
    inv_beyond = {"subtotal": None, "tax": tax, "total": Decimal("110.06"), "invoice_date": date(2025, 1, 1)}
    f_beyond = [f for f in rules.check(inv_beyond, {}, items, [], []) if f["rule_code"] == "TOTAL_MATH"]
    assert len(f_beyond) == 1


def test_h11_duplicate_found_when_over_50_invoices_share_total():
    """H11: A duplicate is found even when more than 50 other invoices share the exact same total."""
    with SessionLocal() as db:
        doc = _create_test_doc(db, "over_50_total")

        shared_total = Decimal("99.99")

        # Create 60 distracting invoices with the same total but different suppliers
        for i in range(60):
            inv_distract = Invoice(
                document_id=doc.id,
                supplier_name=f"Distractor Corp {i}",
                supplier_norm=f"distractor corp {i}",
                invoice_number=f"DIST-{i}",
                invoice_number_norm=f"dist{i}",
                total=shared_total,
                currency="USD",
                invoice_date=date(2025, 1, 1),
                status="auto_validated",
            )
            db.add(inv_distract)
        db.commit()

        # Create Invoice A with specific supplier & number
        inv_a = Invoice(
            document_id=doc.id,
            supplier_name="Global Tech Solutions",
            supplier_norm="global tech solutions",
            invoice_number="INV-TARGET-101",
            invoice_number_norm="invtarget101",
            total=shared_total,
            currency="USD",
            invoice_date=date(2025, 1, 1),
            status="auto_validated",
        )
        db.add(inv_a)
        db.commit()

        # Create Invoice B identical to A
        inv_b = Invoice(
            document_id=doc.id,
            supplier_name="Global Tech Solutions",
            supplier_norm="global tech solutions",
            invoice_number="INV-TARGET-101",
            invoice_number_norm="invtarget101",
            total=shared_total,
            currency="USD",
            invoice_date=date(2025, 1, 1),
            status="auto_validated",
        )
        db.add(inv_b)
        db.commit()

        # Find duplicates for inv_b
        dups = duplicates.find(db, inv_b)
        assert any(d["rule_code"] == "DUP_INVOICE" and d["related_invoice_id"] == inv_a.id for d in dups)


def test_h11_correcting_invoice_a_clears_mirrored_duplicate_on_b(client, H):
    """H11: Correcting invoice A so it is no longer duplicate clears mirrored finding on B and recomputes status."""
    with SessionLocal() as db:
        doc = _create_test_doc(db, "correction_clears_dup")
        inv_a = Invoice(
            document_id=doc.id,
            supplier_name="Alpha Supplies",
            supplier_norm="alpha supplies",
            customer_name="Customer Alpha",
            invoice_number="DUP-100",
            invoice_number_norm="dup100",
            subtotal=Decimal("200.00"),
            tax=Decimal("0.00"),
            total=Decimal("200.00"),
            currency="USD",
            invoice_date=date(2025, 2, 1),
            status="auto_validated",
        )
        db.add(inv_a)
        db.flush()
        _add_key_fields(db, inv_a)

        inv_b = Invoice(
            document_id=doc.id,
            supplier_name="Alpha Supplies",
            supplier_norm="alpha supplies",
            customer_name="Customer Alpha",
            invoice_number="DUP-100",
            invoice_number_norm="dup100",
            subtotal=Decimal("200.00"),
            tax=Decimal("0.00"),
            total=Decimal("200.00"),
            currency="USD",
            invoice_date=date(2025, 2, 1),
            status="auto_validated",
        )
        db.add(inv_b)
        db.flush()
        _add_key_fields(db, inv_b)

        # Revalidate both so duplicate findings are created and mirrored
        revalidate(db, inv_a)
        revalidate(db, inv_b)
        db.commit()
        db.refresh(inv_a)
        db.refresh(inv_b)

        assert inv_a.status == "needs_review"
        assert inv_b.status == "needs_review"
        assert any(v.rule_code == "DUP_INVOICE" for v in inv_a.findings)
        assert any(v.rule_code == "DUP_INVOICE" for v in inv_b.findings)

        a_id = str(inv_a.id)
        a_ver = inv_a.version
        b_id = str(inv_b.id)

    # Correct invoice A's supplier name so it's not a duplicate or near-duplicate
    r = client.patch(
        f"/api/v1/invoices/{a_id}",
        json={"corrections": [{"field": "supplier_name", "value": "Gamma Enterprises Unique"}], "version": a_ver},
        headers=H,
    )
    assert r.status_code == 200

    # Verify invoice B now has no duplicate findings and returned to auto_validated
    with SessionLocal() as db:
        inv_b_after = db.get(Invoice, b_id)
        db.refresh(inv_b_after)
        b_findings = [v.rule_code for v in inv_b_after.findings if v.rule_code.startswith("DUP_")]
        assert len(b_findings) == 0
        assert inv_b_after.status == "auto_validated"


def test_h11_deleting_invoice_a_clears_mirrored_duplicate_on_b():
    """H11: Deleting invoice A clears mirrored duplicate on B and recomputes B's status."""
    with SessionLocal() as db:
        doc = _create_test_doc(db, "delete_clears_dup")
        inv_a = Invoice(
            document_id=doc.id,
            supplier_name="Beta Logistics",
            supplier_norm="beta logistics",
            customer_name="Customer Beta",
            invoice_number="LOG-200",
            invoice_number_norm="log200",
            subtotal=Decimal("350.00"),
            tax=Decimal("0.00"),
            total=Decimal("350.00"),
            currency="USD",
            invoice_date=date(2025, 3, 1),
            status="auto_validated",
        )
        db.add(inv_a)
        db.flush()
        _add_key_fields(db, inv_a)

        inv_b = Invoice(
            document_id=doc.id,
            supplier_name="Beta Logistics",
            supplier_norm="beta logistics",
            customer_name="Customer Beta",
            invoice_number="LOG-200",
            invoice_number_norm="log200",
            subtotal=Decimal("350.00"),
            tax=Decimal("0.00"),
            total=Decimal("350.00"),
            currency="USD",
            invoice_date=date(2025, 3, 1),
            status="auto_validated",
        )
        db.add(inv_b)
        db.flush()
        _add_key_fields(db, inv_b)

        revalidate(db, inv_a)
        revalidate(db, inv_b)
        db.commit()
        db.refresh(inv_a)
        db.refresh(inv_b)

        assert inv_b.status == "needs_review"
        assert any(v.rule_code == "DUP_INVOICE" for v in inv_b.findings)
        b_id = inv_b.id

        # Delete invoice A
        db.delete(inv_a)
        db.commit()

        # Check invoice B
        inv_b_after = db.get(Invoice, b_id)
        db.refresh(inv_b_after)
        b_dup_findings = [v for v in inv_b_after.findings if v.rule_code.startswith("DUP_")]
        assert len(b_dup_findings) == 0
        assert inv_b_after.status == "auto_validated"
