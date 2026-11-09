"""Checks against the supplier's own history: payment details that changed,
an amount far above what this supplier usually bills, a new currency, or a
supplier never seen before. History means this supplier's invoices that were
approved or passed every check, so one bad invoice cannot vouch for another."""
from statistics import median

from sqlalchemy import select

from app.core.config import validation_config
from app.db.models import Document, Invoice
from app.pipeline.extract.bank import mask
from app.pipeline.validate.rules import F

TRUSTED = ("approved", "auto_validated")


def history(db, inv: Invoice) -> list[Invoice]:
    if not inv.supplier_norm:
        return []
    q = (select(Invoice).join(Document).where(Invoice.supplier_norm == inv.supplier_norm, Invoice.id != inv.id,
                                              Invoice.status.in_(TRUSTED), Document.role.is_distinct_from("ledger"))
         .order_by(Invoice.created_at))
    return list(db.scalars(q))


def find(db, inv: Invoice) -> list[dict]:
    cfg = validation_config()["risk"]
    if not inv.supplier_norm:
        return []
    past = history(db, inv)
    if not past:
        return [F("NEW_SUPPLIER", "info", "supplier_name", "First invoice from this supplier; there is no history to compare with.")]
    out = []
    known = {p.bank_account for p in past if p.bank_account}
    if inv.bank_account and known and inv.bank_account not in known:
        last = next(p.bank_account for p in reversed(past) if p.bank_account)
        out.append(F("BANK_CHANGED", "error", "bank_account",
                     "Payment details differ from this supplier's earlier invoices. Confirm the change with the supplier "
                     "by phone before paying.", expected=mask(last), actual=mask(inv.bank_account)))
    same_ccy = [p.total for p in past if p.total is not None and p.currency == inv.currency]
    if inv.total is not None and len(same_ccy) >= cfg["min_history"]:
        mid = median(abs(t) for t in same_ccy)
        if mid and abs(inv.total) > mid * cfg["amount_factor"]:
            out.append(F("AMOUNT_OUTLIER", "warning", "total",
                         f"About {abs(inv.total) / mid:.1f} times this supplier's usual invoice ({len(same_ccy)} earlier invoices).",
                         expected=mid, actual=inv.total))
    ccys = {p.currency for p in past if p.currency}
    if inv.currency and len(ccys) == 1 and len(past) >= cfg["min_history"] - 1 and inv.currency not in ccys:
        out.append(F("CURRENCY_CHANGED", "warning", "currency", "This supplier has always billed in another currency.",
                     expected=next(iter(ccys)), actual=inv.currency))
    return out
