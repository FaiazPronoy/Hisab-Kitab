"""Cross-verification. Ledger rows (a register-mode spreadsheet) against
extracted invoices, and one invoice against another copy of itself.
Matching never guesses: several equal candidates come back as ambiguous."""
from datetime import date
from decimal import Decimal

import numpy as np
from rapidfuzz import fuzz
from scipy.optimize import linear_sum_assignment

from app.core.config import validation_config

FIELDS = ["invoice_number", "invoice_date", "supplier_name", "customer_name", "currency", "subtotal", "tax", "total"]


def _close(a: Decimal | None, b: Decimal | None, cfg) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(Decimal(str(cfg["amount_abs"])), abs(b) * Decimal(str(cfg["amount_pct"])))


def _days(a: date | None, b: date | None):
    return abs((a - b).days) if a and b else None


def _str(v):
    return None if v is None else str(v)


def item(category, severity, left=None, right=None, field=None, delta=None):
    return {"category": category, "severity": severity, "field": field,
            "left_value": None if left is None else _str(left.get(field)),
            "right_value": None if right is None else _str(right.get(field)),
            "delta": None if delta is None else str(delta),
            "left_ref": None if left is None else left["ref"], "right_ref": None if right is None else right["ref"]}


def match_ledger(invoices: list[dict], ledger: list[dict]) -> list[dict]:
    """invoices / ledger: dicts with invoice_number_norm, supplier_norm, invoice_date,
    total, currency and ref. Returns reconciliation items."""
    cfg = validation_config()["reconcile"]
    out, used_inv = [], set()
    seen = {}
    for row in ledger:
        k = (row.get("supplier_norm"), row.get("invoice_number_norm"))
        if row.get("invoice_number_norm") and k in seen:
            out.append(item("duplicate_in_ledger", "warning", None, row, "invoice_number"))
        seen[k] = True

    by_num: dict[str, list[int]] = {}
    for i, inv in enumerate(invoices):
        if inv.get("invoice_number_norm"):
            by_num.setdefault(inv["invoice_number_norm"], []).append(i)

    leftovers = []
    for row in ledger:
        cands = [i for i in by_num.get(row.get("invoice_number_norm") or "", []) if i not in used_inv]
        if len(cands) == 1:
            used_inv.add(cands[0])
            out += compare_pair(invoices[cands[0]], row, cfg)
        elif len(cands) > 1:
            out.append(item("ambiguous", "warning", None, row, "invoice_number"))
        else:
            leftovers.append(row)

    for row in leftovers:
        cands = []
        for i, inv in enumerate(invoices):
            if i in used_inv or not inv.get("supplier_norm") or not row.get("supplier_norm"):
                continue
            if fuzz.ratio(inv["supplier_norm"], row["supplier_norm"]) < cfg["supplier_fuzzy_min"]:
                continue
            d = _days(inv.get("invoice_date"), row.get("invoice_date"))
            if _close(inv.get("total"), row.get("total"), cfg) and (d is None or d <= cfg["date_window_days"]):
                cands.append(i)
        if len(cands) == 1:
            used_inv.add(cands[0])
            r = compare_pair(invoices[cands[0]], row, cfg)
            r.append(item("matched_without_number", "warning", invoices[cands[0]], row, "invoice_number"))
            out += r
        elif len(cands) > 1:
            out.append(item("ambiguous", "warning", None, row, "total"))
        else:
            out.append(item("missing_in_invoices", "error", None, row, "invoice_number"))

    for i, inv in enumerate(invoices):
        if i not in used_inv:
            out.append(item("missing_in_ledger", "error", inv, None, "invoice_number"))
    return out


def compare_pair(inv: dict, row: dict, cfg: dict) -> list[dict]:
    out = []
    if not _close(inv.get("total"), row.get("total"), cfg):
        d = (inv["total"] - row["total"]) if inv.get("total") is not None and row.get("total") is not None else None
        out.append(item("amount_mismatch", "error", inv, row, "total", d))
    d = _days(inv.get("invoice_date"), row.get("invoice_date"))
    if d:
        out.append(item("date_mismatch", "warning" if d <= cfg["date_window_days"] else "error", inv, row, "invoice_date", d))
    if inv.get("supplier_norm") and row.get("supplier_norm") and fuzz.ratio(inv["supplier_norm"], row["supplier_norm"]) < cfg["supplier_fuzzy_min"]:
        out.append(item("supplier_mismatch", "warning", inv, row, "supplier_name"))
    if inv.get("currency") and row.get("currency") and inv["currency"] != row["currency"]:
        out.append(item("amount_mismatch", "error", inv, row, "currency"))
    if not out:
        out.append(item("matched", "info", inv, row, "invoice_number"))
    return out


def compare_copies(a: dict, b: dict, items_a: list[dict], items_b: list[dict]) -> list[dict]:
    """Two documents that should be the same invoice: field diff plus line items
    paired with the Hungarian algorithm on description similarity and amount."""
    cfg = validation_config()["reconcile"]
    out = []
    for f in FIELDS:
        va, vb = a.get(f), b.get(f)
        if isinstance(va, Decimal) or isinstance(vb, Decimal):
            same = _close(va, vb, cfg) or (va is None and vb is None)
        elif isinstance(va, str) and isinstance(vb, str):
            same = fuzz.ratio(va.lower(), vb.lower()) >= 95
        else:
            same = va == vb
        if not same:
            out.append(item("field_diff", "error" if f in ("total", "invoice_number") else "warning", a, b, f,
                            (va - vb) if isinstance(va, Decimal) and isinstance(vb, Decimal) else None))
    if items_a or items_b:
        n, m = len(items_a), len(items_b)
        cost = np.ones((max(n, 1), max(m, 1)))
        for i, x in enumerate(items_a):
            for j, y in enumerate(items_b):
                sim = fuzz.token_sort_ratio(x.get("description") or "", y.get("description") or "") / 100
                amt = 1.0 if _close(x.get("amount"), y.get("amount"), cfg) else 0.0
                cost[i, j] = 1 - (0.7 * sim + 0.3 * amt)
        rows, cols = linear_sum_assignment(cost)
        paired_a, paired_b = set(), set()
        for i, j in zip(rows, cols):
            if i < n and j < m and cost[i, j] < 0.5:
                paired_a.add(i)
                paired_b.add(j)
                if not _close(items_a[i].get("amount"), items_b[j].get("amount"), cfg):
                    out.append({"category": "line_amount_mismatch", "severity": "error", "field": f"line_items[{i}]",
                                "left_value": str(items_a[i].get("amount")), "right_value": str(items_b[j].get("amount")),
                                "delta": None, "left_ref": a["ref"], "right_ref": b["ref"]})
        for i in set(range(n)) - paired_a:
            out.append({"category": "line_missing_right", "severity": "warning", "field": f"line_items[{i}]",
                        "left_value": items_a[i].get("description"), "right_value": None, "delta": None,
                        "left_ref": a["ref"], "right_ref": b["ref"]})
        for j in set(range(m)) - paired_b:
            out.append({"category": "line_missing_left", "severity": "warning", "field": f"line_items[{j}]",
                        "left_value": None, "right_value": items_b[j].get("description"), "delta": None,
                        "left_ref": a["ref"], "right_ref": b["ref"]})
    if not out:
        out.append(item("matched", "info", a, b, "invoice_number"))
    return out
