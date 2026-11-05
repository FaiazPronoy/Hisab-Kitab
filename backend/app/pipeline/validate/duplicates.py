from rapidfuzz import fuzz
from sqlalchemy import or_, select

from app.core.config import validation_config
from app.db.models import Invoice
from app.pipeline.extract.normalize import ocr_variant
from app.pipeline.validate.rules import F


def tier(a: dict, b: dict, cfg: dict) -> str | None:
    """a, b: typed invoice dicts. Returns DUP_INVOICE, DUP_CONFLICT, DUP_SUSPECTED or None."""
    same_supplier = a.get("supplier_norm") and a.get("supplier_norm") == b.get("supplier_norm")
    na, nb = a.get("invoice_number_norm"), b.get("invoice_number_norm")
    if same_supplier and na and na == nb:
        if a.get("total") == b.get("total") and a.get("currency") == b.get("currency"):
            return "DUP_INVOICE"
        return "DUP_CONFLICT"
    if not (a.get("supplier_norm") and b.get("supplier_norm")):
        return None
    sim = fuzz.ratio(a["supplier_norm"], b["supplier_norm"]) / 100
    if sim < cfg["duplicates"]["supplier_trigram_min"] or a.get("total") is None or a.get("total") != b.get("total"):
        return None
    da, db_ = a.get("invoice_date"), b.get("invoice_date")
    if da and db_ and abs((da - db_).days) > cfg["duplicates"]["date_window_days"]:
        return None
    if na != nb or ocr_variant(na, nb):
        return "DUP_SUSPECTED"
    return None


def find(db, inv: Invoice) -> list[dict]:
    cfg = validation_config()
    if not inv.supplier_norm and not inv.invoice_number_norm:
        return []
    # ledger rows are payment records, compared to invoices by reconciliation, not here
    is_row = inv.row_index is not None
    q = select(Invoice).where(Invoice.id != inv.id,
                              Invoice.row_index.is_not(None) if is_row else Invoice.row_index.is_(None))
    conds = []
    if inv.invoice_number_norm:
        conds.append(Invoice.invoice_number_norm == inv.invoice_number_norm)
    if inv.total is not None:
        conds.append(Invoice.total == inv.total)
    rows = db.scalars(q.where(or_(*conds)).limit(50)).all() if conds else []
    me = _typed(inv)
    out = []
    for other in rows:
        t = tier(me, _typed(other), cfg)
        if not t:
            continue
        sev = "warning" if t == "DUP_SUSPECTED" else "error"
        msg = {"DUP_INVOICE": "Same supplier, number and total as another invoice.",
               "DUP_CONFLICT": "Same supplier and number as another invoice but a different total.",
               "DUP_SUSPECTED": "Looks like a near-duplicate of another invoice."}[t]
        f = F(t, sev, "invoice_number", msg, expected=other.invoice_number, actual=inv.invoice_number)
        f["related_invoice_id"] = other.id
        out.append(f)
    return out


def _typed(i: Invoice) -> dict:
    return {"supplier_norm": i.supplier_norm, "invoice_number_norm": i.invoice_number_norm, "total": i.total,
            "currency": i.currency, "invoice_date": i.invoice_date}

