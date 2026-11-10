"""Two-way matching against uploaded purchase orders: the PO an invoice
cites must exist, belong to the same supplier, and not be billed beyond its
amount once every invoice citing it is added up. Goods receipts are not
modelled, so this is not a full three-way match."""
from decimal import Decimal

from rapidfuzz import fuzz
from sqlalchemy import func, select

from app.core.config import validation_config
from app.db.models import Document, Invoice
from app.pipeline.validate.rules import F


def norm_po(v) -> str:
    return "".join(ch for ch in str(v or "").upper() if ch.isalnum())


def _po_key():
    return func.upper(func.regexp_replace(Invoice.po_number, "[^A-Za-z0-9]", "", "g"))


def find(db, inv: Invoice) -> list[dict]:
    key = norm_po(inv.po_number)
    if not key:
        return []
    po_rows = select(Invoice).join(Document).where(Document.role == "purchase_orders")
    if db.scalar(select(func.count()).select_from(po_rows.subquery())) == 0:
        return []  # no purchase orders uploaded: nothing to match against
    po = db.scalars(po_rows.where(_po_key() == key).order_by(Invoice.created_at.desc())).first()
    if po is None:
        return [F("PO_UNKNOWN", "warning", "po_number", "The purchase order on this invoice is not in the uploaded purchase orders.",
                  actual=inv.po_number)]
    out = []
    cfg = validation_config()["po"]
    if po.supplier_norm and inv.supplier_norm and fuzz.ratio(po.supplier_norm, inv.supplier_norm) < cfg["supplier_min"]:
        out.append(F("PO_SUPPLIER", "warning", "supplier_name", "The purchase order was raised for another supplier.",
                     expected=po.supplier_name, actual=inv.supplier_name))
    if po.currency and inv.currency and po.currency != inv.currency:
        out.append(F("PO_CURRENCY", "warning", "currency", "The purchase order is in another currency.",
                     expected=po.currency, actual=inv.currency))
    elif po.total is not None and inv.total is not None:
        others = db.scalars(select(Invoice.total).join(Document).where(
            _po_key() == key, Invoice.id != inv.id, Invoice.total.is_not(None),
            Document.role.is_(None) | (Document.role == "invoices"))).all()
        billed = sum(others, Decimal("0")) + inv.total
        if billed > po.total + Decimal(str(cfg["over_abs"])):
            out.append(F("PO_OVER", "error", "total",
                         f"Invoices against this purchase order add up to more than it allows ({len(others) + 1} invoices).",
                         expected=po.total, actual=billed))
    return out
