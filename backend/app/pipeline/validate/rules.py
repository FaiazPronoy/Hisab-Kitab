"""Every check is deterministic Python on Decimal values. Each finding is
{rule_code, severity, field, message, expected, actual}."""
from datetime import date, timedelta
from decimal import Decimal

from app.core.config import validation_config

ZERO = Decimal("0")


def F(code, severity, field, message, expected=None, actual=None):
    return {"rule_code": code, "severity": severity, "field": field, "message": message,
            "expected": None if expected is None else str(expected), "actual": None if actual is None else str(actual)}


def tol(value: Decimal, abs_: float, pct: float) -> Decimal:
    return max(Decimal(str(abs_)), abs(value) * Decimal(str(pct)))


def check(inv: dict, meta: dict, items: list[dict], tax_lines: list[dict], flags: list[str], today: date | None = None) -> list[dict]:
    """inv: typed values. meta: per-field {confidence, null_reason, verified, source}."""
    cfg = validation_config()
    t = cfg["tolerance"]
    today = today or date.today()
    out = []
    credit = inv.get("doc_type") == "credit_note"

    for f in cfg["key_fields"]:
        if inv.get(f) in (None, ""):
            reason = (meta.get(f) or {}).get("null_reason")
            if reason == "unverified":
                continue  # reported once as GROUNDING_FAILED below
            out.append(F("REQ_MISSING", "error", f, f"{f.replace('_', ' ')} is missing ({reason or 'not found'})."))
    for f in cfg["optional_fields"]:
        if inv.get(f) in (None, ""):
            out.append(F("OPT_MISSING", "warning", f, f"{f.replace('_', ' ')} is not on the document."))

    for f, m in meta.items():
        if (m or {}).get("null_reason") == "unverified":
            out.append(F("GROUNDING_FAILED", "critical", f, "The extracted value could not be found in the document text, so it was removed.",
                         actual=m.get("rejected_value")))

    for i, it in enumerate(items):
        q, p, a = (_d(it.get(k)) for k in ("quantity", "unit_price", "amount"))
        if q is None or p is None or a is None:
            continue
        exp = (q * p).quantize(Decimal("0.01"))
        diff = abs(exp - a)
        if diff > tol(a, t["line_math_abs"], t["line_math_pct"]):
            sev = "error" if a and diff / abs(a) > Decimal(str(t["line_math_error_pct"])) else "warning"
            out.append(F("LINE_MATH", sev, f"line_items[{i}].amount", f"Line {i + 1}: quantity x unit price does not match the amount.", exp, a))

    sub, tax, total = inv.get("subtotal"), inv.get("tax"), inv.get("total")
    disc, ship = inv.get("discount") or ZERO, inv.get("shipping") or ZERO
    amounts = [_d(it.get("amount")) for it in items]
    if sub is not None and amounts and all(a is not None for a in amounts):
        s = sum(amounts, ZERO)
        if abs(s - sub) > max(Decimal(str(t["subtotal_abs"])), Decimal(str(t["subtotal_per_line"])) * len(amounts)):
            out.append(F("SUBTOTAL_SUM", "error", "subtotal", "Line items do not add up to the subtotal.", s, sub))

    tax_sum = sum((_d(x.get("amount")) or ZERO for x in tax_lines), ZERO) if tax_lines else None
    if tax is not None and tax_sum is not None and abs(tax_sum - tax) > tol(tax, t["tax_lines_abs"], t["tax_lines_pct"]):
        out.append(F("TAX_LINES", "warning", "tax", "Tax lines do not add up to the tax total.", tax_sum, tax))

    if total is not None and sub is not None:
        tax_used = tax if tax is not None else (tax_sum or ZERO)
        exp = sub - disc + ship + tax_used
        allowed = tol(total, t["total_abs"], t["total_pct"])
        if abs(exp - total) > allowed:
            if abs((sub - disc + ship) - total) <= allowed and tax_used:
                out.append(F("TAX_INCLUSIVE", "info", "total", "Totals only reconcile if the prices already include tax."))
            else:
                out.append(F("TOTAL_MATH", "error", "total", "Subtotal, discount, shipping and tax do not add up to the total.", exp, total))
        if tax is not None and sub > 0:
            rate = tax / sub
            if rate < 0 or rate > Decimal(str(cfg["tax_rate"]["max_plausible"])):
                out.append(F("TAX_RATE", "warning", "tax", f"Effective tax rate {rate:.1%} looks wrong.", actual=f"{rate:.4f}"))

    if total is not None:
        if (total <= 0 and not credit) or abs(total) > cfg["amount"]["absurd_total"]:
            out.append(F("AMOUNT_SANITY", "warning", "total", "The total is zero, negative or implausibly large.", actual=total))

    d = inv.get("invoice_date")
    if d is not None:
        if d.year < cfg["date"]["min_year"]:
            out.append(F("DATE_SANITY", "error", "invoice_date", "The invoice date is implausibly old.", actual=d))
        elif d > today + timedelta(days=cfg["date"]["future_days"]):
            out.append(F("DATE_SANITY", "warning", "invoice_date", "The invoice date is in the future.", actual=d))
        due = inv.get("due_date")
        if due is not None and due < d:
            out.append(F("DATE_SANITY", "warning", "due_date", "The due date is before the invoice date.", d, due))
    for f in ("invoice_date", "due_date"):
        if (meta.get(f) or {}).get("ambiguous_date"):
            out.append(F("DATE_SANITY", "warning", f, "Day and month could be swapped; please confirm the date."))

    if "ambiguous_currency" in flags:
        out.append(F("CURRENCY", "warning", "currency", "Only a $ sign is printed; the currency was assumed to be USD."))

    kmin = cfg["confidence"]["key_field_min"]
    for f in cfg["key_fields"]:
        c = (meta.get(f) or {}).get("confidence")
        if inv.get(f) not in (None, "") and c is not None and c < kmin and (meta.get(f) or {}).get("source") != "user":
            out.append(F("LOW_CONFIDENCE", "warning", f, f"Low confidence in {f.replace('_', ' ')} ({c:.2f}).", actual=c))
    if (meta.get("total") or {}).get("source") == "vision":
        out.append(F("LOW_CONFIDENCE", "warning", "total", "Read from the page image; no text evidence to highlight."))

    if "suspicious_content" in flags:
        out.append(F("SUSPICIOUS_CONTENT", "warning", None, "The document contains instruction-like text. Check it by hand."))
    if "extraction_failed" in flags:
        out.append(F("EXTRACTION_FAILED", "error", None, "The extraction model returned no usable answer."))
    if "long_segment" in flags:
        out.append(F("LONG_SEGMENT", "info", None, "Invoice spans many pages; header fields were read from the first and last pages."))
    return out


def _d(v):
    if v is None or v == "":
        return None
    return v if isinstance(v, Decimal) else Decimal(str(v))
