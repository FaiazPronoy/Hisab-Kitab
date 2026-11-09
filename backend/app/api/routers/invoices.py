import csv
import io
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.api.serialize import inv_detail, inv_summary
from app.db.models import Correction, ExtractedField, Invoice, ValidationResult
from app.db.session import get_db
from app.pipeline import index as index_mod
from app.pipeline.extract.normalize import norm_invoice_number, norm_supplier
from app.pipeline.process import revalidate

router = APIRouter(tags=["invoices"])
MONEY = {"subtotal", "tax", "discount", "shipping", "total"}
DATES = {"invoice_date", "due_date"}
TEXT = {"invoice_number", "supplier_name", "customer_name", "po_number", "currency"}
ITEM = re.compile(r"^line_items\[(\d+)\]\.(description|quantity|unit_price|amount)$")


def _inv(db, invoice_id) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found.")
    return inv


@router.get("/invoices")
def list_invoices(status: str | None = None, supplier: str | None = None, currency: str | None = None,
                  date_from: date | None = None, date_to: date | None = None, min_total: Decimal | None = None,
                  max_total: Decimal | None = None, document_id: uuid.UUID | None = None, limit: int = 100, offset: int = 0,
                  db: Session = Depends(get_db)):
    q = select(Invoice).order_by(Invoice.created_at.desc())
    if status:
        q = q.where(Invoice.status == status)
    if supplier:
        q = q.where(Invoice.supplier_norm.ilike(f"%{norm_supplier(supplier) or supplier}%"))
    if currency:
        q = q.where(Invoice.currency == currency.upper())
    if date_from:
        q = q.where(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.where(Invoice.invoice_date <= date_to)
    if min_total is not None:
        q = q.where(Invoice.total >= min_total)
    if max_total is not None:
        q = q.where(Invoice.total <= max_total)
    if document_id:
        q = q.where(Invoice.document_id == document_id)
    return [inv_summary(i) for i in db.scalars(q.offset(offset).limit(min(limit, 500))).all()]


@router.get("/invoices/export")
def export(status: str | None = None, db: Session = Depends(get_db)):
    q = select(Invoice).order_by(Invoice.created_at)
    if status:
        q = q.where(Invoice.status == status)
    cols = ["invoice_number", "invoice_date", "supplier_name", "customer_name", "currency", "subtotal", "tax", "total", "status"]
    num_cols = {"subtotal", "tax", "total"}

    def safe(col: str, v):
        if v is None:
            return ""
        s = str(v)
        if col in num_cols:
            return s
        # stop spreadsheet apps from running a cell as a formula
        return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

    def rows():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id"] + cols)
        yield buf.getvalue()
        for inv in db.scalars(q).yield_per(200):
            buf.seek(0)
            buf.truncate()
            w.writerow([inv.id] + [safe(c, getattr(inv, c)) for c in cols])
            yield buf.getvalue()

    return StreamingResponse(rows(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=invoices.csv"})


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    inv = _inv(db, invoice_id)
    corr = db.scalars(select(Correction).where(Correction.invoice_id == inv.id).order_by(Correction.id)).all()
    return inv_detail(inv, corr)


class CorrectionIn(BaseModel):
    field: str
    value: str | None
    reason: str | None = None


class PatchIn(BaseModel):
    corrections: list[CorrectionIn]
    version: int
    corrected_by: str = "reviewer"


FIELD_CAPS = {
    "invoice_number": 100,
    "supplier_name": 255,
    "customer_name": 255,
    "currency": 3,
    "po_number": 100,
    "payment_terms": 100,
    "description": 1000,
}


def _parse(field: str, value: str | None):
    if value is None or value == "":
        return None
    if field in MONEY or field in ("quantity", "unit_price", "amount"):
        val_str = str(value).strip()
        # Reject EU-looking input like '1.234,56' or '1234,56'
        if re.search(r"\d+\.\d{3},\d{2}", val_str) or ("," in val_str and "." in val_str and val_str.find(".") < val_str.find(",")) or re.search(r",\d{1,2}$", val_str):
            raise HTTPException(422, f"European number format '{value}' is not accepted. Use plain decimals like '1234.56'.")
        clean = val_str.replace(",", "")
        if not re.fullmatch(r"^-?\d+(?:\.\d+)?$", clean):
            raise HTTPException(422, f"'{value}' is not a valid number.")
        try:
            d = Decimal(clean)
        except InvalidOperation:
            raise HTTPException(422, f"'{value}' is not a valid number.")
        if not d.is_finite():
            raise HTTPException(422, "Number must be finite.")
        if abs(d) >= Decimal("1e14"):
            raise HTTPException(422, "Number exceeds maximum allowed value.")
        return d.quantize(Decimal("0.0001"))
    if field in DATES:
        try:
            return date.fromisoformat(str(value).strip())
        except ValueError:
            raise HTTPException(422, f"'{value}' is not a date (YYYY-MM-DD).")
    if field == "currency":
        clean_c = str(value).strip()
        if not re.fullmatch(r"[A-Za-z]{3}", clean_c):
            raise HTTPException(422, "Currency must be a 3-letter ISO code.")
        return clean_c.upper()
    val_str = str(value).strip()
    max_len = FIELD_CAPS.get(field, 255)
    if len(val_str) > max_len:
        raise HTTPException(422, f"Field '{field}' exceeds maximum length of {max_len} characters.")
    return val_str


@router.patch("/invoices/{invoice_id}")
def correct(invoice_id: uuid.UUID, body: PatchIn, db: Session = Depends(get_db)):
    inv = _inv(db, invoice_id)
    if body.version != inv.version:
        raise HTTPException(409, "This invoice was changed by someone else. Reload and try again.")
    by_name = {f.name: f for f in inv.fields}
    for c in body.corrections:
        m = ITEM.match(c.field)
        if m:
            idx, col = int(m.group(1)), m.group(2)
            item = next((li for li in inv.line_items if li.idx == idx), None)
            if not item:
                raise HTTPException(422, f"No line item {idx}.")
            new = c.value if col == "description" else _parse(col, c.value)
            old = getattr(item, col)
            setattr(item, col, new)
            item.confidence = 1.0
        elif c.field in MONEY | DATES | TEXT:
            new = _parse(c.field, c.value)
            old = getattr(inv, c.field)
            setattr(inv, c.field, new)
            if c.field == "invoice_number":
                inv.invoice_number_norm = norm_invoice_number(new)
            if c.field == "supplier_name":
                inv.supplier_norm = norm_supplier(new)
            f = by_name.get(c.field) or ExtractedField(invoice_id=inv.id, name=c.field)
            f.value_norm = None if new is None else str(new)
            f.source, f.confidence, f.verified, f.null_reason = "user", 1.0, new is not None, None if new is not None else "not_on_document"
            db.add(f)
        else:
            raise HTTPException(422, f"Unknown field '{c.field}'.")
        db.add(Correction(invoice_id=inv.id, field=c.field, old_value=None if old is None else str(old),
                          new_value=None if new is None else str(new), reason=c.reason, corrected_by=body.corrected_by))
    if inv.status == "approved":
        inv.status = "needs_review"
    inv.updated_at = func.now()
    try:
        db.flush()
        db.refresh(inv)
        findings = revalidate(db, inv, pages_failed=inv.document.pages_failed)
        index_mod.index_invoice(db, inv)
        db.commit()
    except StaleDataError:
        db.rollback()
        raise HTTPException(409, "This invoice was changed concurrently. Reload and try again.")
    _sync_doc_status(db, inv.document)
    return {"status": inv.status, "version": inv.version, "findings": findings}


class ApproveIn(BaseModel):
    version: int | None = None


def _sync_doc_status(db, doc):
    # a document waits for review while any of its invoices does
    if doc.status not in ("done", "needs_review"):
        return
    waiting = any(i.status == "needs_review" for i in doc.invoices)
    new = "needs_review" if waiting else "done"
    if doc.status != new:
        doc.status = new
        db.commit()


@router.post("/invoices/{invoice_id}/approve")
def approve(invoice_id: uuid.UUID, body: ApproveIn | None = None, db: Session = Depends(get_db)):
    inv = _inv(db, invoice_id)
    if body and body.version is not None and body.version != inv.version:
        raise HTTPException(409, "This invoice was changed by someone else. Reload and try again.")
    inv.status = "approved"
    db.add(Correction(invoice_id=inv.id, field="status", old_value=None, new_value="approved", reason="approved"))
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise HTTPException(409, "This invoice was changed concurrently. Reload and try again.")
    _sync_doc_status(db, inv.document)
    nxt = _next_review(db, exclude=inv.id)
    return {"status": "approved", "next_invoice_id": str(nxt) if nxt else None}


def _review_query():
    sev = func.max(case((ValidationResult.severity == "critical", 4), (ValidationResult.severity == "error", 3),
                        (ValidationResult.severity == "warning", 2), else_=1))
    return (select(Invoice, sev.label("rank")).outerjoin(ValidationResult, ValidationResult.invoice_id == Invoice.id)
            .where(Invoice.status == "needs_review").group_by(Invoice.id).order_by(sev.desc().nullslast(), Invoice.created_at))


def _next_review(db, exclude=None):
    q = _review_query()
    if exclude:
        q = q.where(Invoice.id != exclude)
    row = db.execute(q.limit(1)).first()
    return row[0].id if row else None


@router.get("/review-queue")
def review_queue(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.execute(_review_query().limit(min(limit, 500))).all()
    return [{**inv_summary(i), "rank": r, "filename": i.document.filename} for i, r in rows]

