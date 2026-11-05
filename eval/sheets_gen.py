"""A payments ledger that should match the invoice set, with planted
discrepancies so reconciliation recall can be measured."""
import random
from decimal import Decimal
from pathlib import Path

import openpyxl


def ledger(invoices: list[dict], out: Path, rng: random.Random) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rows, planted = [], {"amount_mismatch": [], "missing_in_ledger": [], "missing_in_invoices": []}
    pool = [x for x in invoices if not x.get("planted") and x["layout"] != "credit_note"]
    rng.shuffle(pool)
    drop = set(x["id"] for x in pool[:3])
    bump = set(x["id"] for x in pool[3:7])
    for inv in invoices:
        if inv.get("planted") in ("duplicate", "near_duplicate", "conflict") or inv["layout"] == "credit_note":
            continue
        if inv["id"] in drop:
            planted["missing_in_ledger"].append(inv["invoice_number"])
            continue
        total = Decimal(inv.get("printed_total") or inv["total"])
        if inv["id"] in bump:
            total += Decimal("37.50")
            planted["amount_mismatch"].append(inv["invoice_number"])
        rows.append([inv["invoice_number"], inv["invoice_date"], inv["supplier_name"], float(total), inv["currency"]])
    for k in range(2):
        num = f"GHOST-{9000 + k}"
        rows.append([num, "2026-05-01", "Phantom Supplies Ltd", 199.0 + k, "USD"])
        planted["missing_in_invoices"].append(num)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Payments"
    ws.append(["Invoice No", "Invoice Date", "Supplier", "Total", "Currency"])
    for r in rows:
        ws.append(r)
    p = out / "ledger.xlsx"
    wb.save(p)
    return {"file": p.name, "planted": planted, "rows": len(rows)}
