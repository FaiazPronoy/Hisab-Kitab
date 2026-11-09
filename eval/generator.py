"""Synthetic invoices with ground truth written before rendering.

python -m eval.generator --n 200 --out eval/generated
Each invoice is a dict of true values; render() draws it with one of the
layouts; labels.jsonl holds the truth plus any planted problem."""
import argparse
import json
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from faker import Faker
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

LAYOUTS = ["classic", "wholesale", "eu_vat", "receipt", "multipage", "credit_note"]
CURRENCIES = {"classic": ["USD", "GBP", "BDT"], "wholesale": ["USD", "AUD"], "eu_vat": ["EUR"], "receipt": ["USD", "GBP"],
              "multipage": ["USD", "GBP"], "credit_note": ["GBP", "USD"]}
SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€", "AUD": "A$", "BDT": "BDT "}
PRODUCTS = ["Hex bolts M6", "Steel washers", "Copper wire 2.5mm", "Packing tape", "Pallet wrap", "LED panel 60x60",
            "Cable ties", "Safety gloves", "Printer paper A4", "Toner cartridge", "Office chair", "Desk lamp",
            "Laptop stand", "USB-C cable", "Network switch 8 port", "Extension lead", "Cleaning service", "Consulting hours",
            "Freight handling", "Warehouse storage"]
Q = Decimal("0.01")


def money(x) -> Decimal:
    return Decimal(x).quantize(Q, rounding=ROUND_HALF_UP)


def make(fake: Faker, rng: random.Random, i: int, layout: str) -> dict:
    ccy = rng.choice(CURRENCIES[layout])
    n_items = rng.randint(14, 34) if layout == "multipage" else rng.randint(1, 7)
    items = []
    for _ in range(n_items):
        qty = Decimal(rng.choice([1, 1, 2, 3, 5, 10, 12, 25]))
        price = money(rng.uniform(1.5, 480))
        items.append({"description": rng.choice(PRODUCTS), "quantity": str(qty), "unit_price": str(price),
                      "amount": str(money(qty * price))})
    sub = sum((Decimal(it["amount"]) for it in items), Decimal(0))
    rate = {"EUR": Decimal("0.19"), "GBP": Decimal("0.20"), "BDT": Decimal("0.15")}.get(ccy, rng.choice([Decimal("0.0825"), Decimal("0.10"), Decimal("0.07")]))
    discount = money(sub * Decimal("0.05")) if rng.random() < 0.2 else None
    shipping = money(rng.uniform(5, 60)) if rng.random() < 0.25 else None
    tax = money((sub - (discount or 0)) * rate)
    total = sub - (discount or 0) + (shipping or 0) + tax
    sign = -1 if layout == "credit_note" else 1
    d = date(2026, 1, 1) + timedelta(days=rng.randint(0, 290))
    prefix = rng.choice(["INV-", "INV", "", "SI-", "TX/"]) if layout != "credit_note" else "CN-"
    truth = {
        "id": f"inv{i:04d}", "layout": layout, "doc_type": "credit_note" if layout == "credit_note" else ("receipt" if layout == "receipt" else "invoice"),
        "invoice_number": f"{prefix}{rng.randint(1000, 99999)}", "invoice_date": d.isoformat(),
        "due_date": (d + timedelta(days=30)).isoformat() if layout not in ("receipt",) else None,
        "supplier_name": fake.company(), "customer_name": fake.company() if layout != "receipt" else None,
        "currency": ccy, "subtotal": str(money(sign * sub)), "tax": str(money(sign * tax)),
        "discount": str(discount) if discount else None, "shipping": str(money(sign * shipping)) if shipping else None,
        "total": str(money(sign * total)), "tax_rate": str(rate), "line_items": items, "planted": None,
    }
    if layout == "receipt":
        truth["subtotal"] = None if rng.random() < 0.5 else truth["subtotal"]
    return truth


def plant(rng, invs: list[dict], share: float = 0.13):
    """Make some invoices wrong on purpose so validation recall can be measured."""
    kinds = ["wrong_total", "missing_subtotal_wrong_total", "missing_tax", "missing_number", "duplicate", "near_duplicate", "conflict"]
    for inv in rng.sample(invs, int(len(invs) * share)):
        k = rng.choice(kinds)
        if k == "wrong_total":
            inv["printed_total"] = str(money(Decimal(inv["total"]) + Decimal(rng.choice([10, 9, 100, 1]))))
        elif k == "missing_subtotal_wrong_total":
            inv["subtotal"] = None
            inv["hide"] = list(set((inv.get("hide") or []) + ["subtotal"]))
            inv["printed_total"] = str(money(Decimal(inv["total"]) + Decimal(rng.choice([10, 9, 100, 1]))))
        elif k == "missing_tax":
            inv["hide"] = ["tax"]
        elif k == "missing_number":
            inv["hide"] = ["invoice_number"]
        elif k in ("duplicate", "near_duplicate", "conflict"):
            src = rng.choice([x for x in invs if x is not inv and not x.get("planted")])
            for f in ("supplier_name", "invoice_number", "currency", "total", "subtotal", "tax", "line_items", "invoice_date", "customer_name"):
                inv[f] = src[f]
            if k == "near_duplicate":
                inv["invoice_number"] = src["invoice_number"].replace("0", "O", 1) if "0" in src["invoice_number"] else src["invoice_number"] + "A"
            if k == "conflict":
                inv["total"] = str(money(Decimal(src["total"]) + 25))
                inv["printed_total"] = inv["total"]
            inv["duplicate_of"] = src["id"]
        inv["planted"] = k


def fmt_amount(v: str, ccy: str, eu: bool) -> str:
    d = Decimal(v)
    s = f"{abs(d):,.2f}"
    if eu:
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        s = f"{s} €"
    else:
        s = f"{SYMBOL.get(ccy, '')}{s}"
    return f"-{s}" if d < 0 else s


def fmt_date(iso: str, layout: str, ccy: str) -> str:
    d = date.fromisoformat(iso)
    if layout == "eu_vat":
        return d.strftime("%d.%m.%Y")
    if layout == "receipt":
        return d.strftime("%d %b %Y")
    return d.strftime("%m/%d/%Y") if ccy == "USD" else d.strftime("%d/%m/%Y")


def draw(c: canvas.Canvas, inv: dict, continued_from: int | None = None):
    lay, ccy = inv["layout"], inv["currency"]
    eu = lay == "eu_vat"
    W, H = A4
    hide = set(inv.get("hide") or [])
    a = lambda v: fmt_amount(v, ccy, eu)  # noqa: E731
    y = H - 60
    title = {"credit_note": "CREDIT NOTE", "receipt": "RECEIPT", "eu_vat": "RECHNUNG / INVOICE"}.get(lay, "INVOICE")
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, inv["supplier_name"])
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(W - 50, y, title)
    c.setFont("Helvetica", 10)
    y -= 34
    label = inv.get("number_label") or (
        "Credit Note No" if lay == "credit_note" else ("Receipt No" if lay == "receipt" else "Invoice No"))
    if "invoice_number" not in hide:
        c.drawString(50, y, f"{label}: {inv['invoice_number']}")
    c.drawRightString(W - 50, y, f"Date: {fmt_date(inv['invoice_date'], lay, ccy)}")
    y -= 16
    if inv.get("due_date"):
        c.drawRightString(W - 50, y, f"Due Date: {fmt_date(inv['due_date'], lay, ccy)}")
    if inv.get("customer_name"):
        c.drawString(50, y, "Bill To:")
        y -= 14
        c.drawString(50, y, inv["customer_name"])
    if lay == "eu_vat":
        y -= 14
        c.drawString(50, y, "Currency: EUR")
    elif lay in ("classic", "wholesale") and ccy != "USD":
        y -= 14
        c.drawString(50, y, f"Currency: {ccy}")
    y -= 30
    cols = [50, 320, 390, 480] if lay != "wholesale" else [50, 300, 370, 470]
    heads = ["Description", "Qty", "Unit Price", "Amount"]

    def header(yy):
        c.setFont("Helvetica-Bold", 10)
        for x, h in zip(cols, heads):
            c.drawString(x, yy, h)
        c.setFont("Helvetica", 10)
        return yy - 18

    y = header(y)
    page = 1
    for it in inv["line_items"]:
        if y < 150:
            c.drawRightString(W - 50, 40, f"Page {page} of 2" if lay == "multipage" else "continued")
            c.showPage()
            page += 1
            c.setFont("Helvetica", 10)
            yy = H - 60
            c.drawString(50, yy, inv["supplier_name"])
            c.drawRightString(W - 50, yy, f"{label}: {inv['invoice_number']}" if "invoice_number" not in hide else "")
            y = header(yy - 30)
        c.drawString(cols[0], y, it["description"])
        c.drawString(cols[1], y, it["quantity"])
        c.drawString(cols[2], y, a(it["unit_price"]))
        c.drawString(cols[3], y, a(it["amount"]))
        y -= 16
    y -= 14
    rows = []
    if inv.get("subtotal") and "subtotal" not in hide:
        rows.append(("Subtotal", inv["subtotal"]))
    if inv.get("discount"):
        rows.append(("Discount", str(-Decimal(inv["discount"]))))
    if inv.get("shipping"):
        rows.append(("Shipping", inv["shipping"]))
    if "tax" not in hide:
        pct = f"{Decimal(inv['tax_rate']) * 100:.2f}".rstrip("0").rstrip(".")
        rows.append((f"{'MwSt' if eu else ('VAT' if ccy in ('GBP', 'BDT') else 'Tax')} {pct}%", inv["tax"]))
    rows.append(("Total", inv.get("printed_total") or inv["total"]))
    for k, v in rows:
        c.setFont("Helvetica-Bold" if k == "Total" else "Helvetica", 10)
        c.drawString(cols[2], y, k)
        c.drawString(cols[3], y, a(v))
        y -= 16
    if lay == "multipage":
        c.setFont("Helvetica", 10)
        c.drawRightString(W - 50, 40, f"Page {page} of {page}")
    c.setFont("Helvetica", 8)
    if inv.get("iban"):
        c.drawString(50, 74, f"Pay to IBAN: {inv['iban']}")
    c.drawString(50, 60, "Thank you for your business. Payment within 30 days.")
    c.showPage()


def render(inv: dict, path: Path):
    c = canvas.Canvas(str(path), pagesize=A4)
    draw(c, inv)
    c.save()


def render_many(invs: list[dict], path: Path):
    c = canvas.Canvas(str(path), pagesize=A4)
    for inv in invs:
        draw(c, inv)
    c.save()


def build(n: int, out: Path, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    fake = Faker("en_GB")
    Faker.seed(seed)
    invs = [make(fake, rng, i, LAYOUTS[i % len(LAYOUTS)]) for i in range(n)]
    plant(rng, invs)
    rng.shuffle(invs)
    cut = int(n * 0.3)
    out.mkdir(parents=True, exist_ok=True)
    labels = []
    for k, inv in enumerate(invs):
        inv["split"] = "dev" if k < cut else "test"
        p = out / f"{inv['id']}.pdf"
        render(inv, p)
        labels.append({**inv, "file": p.name, "invoices": [inv["id"]]})
    # multi-invoice PDFs for the boundary detector
    singles = [x for x in invs if x["layout"] != "multipage" and not x.get("planted")]
    for j in range(min(12, len(singles) // 3)):
        group = singles[j * 3:(j * 3) + rng.randint(2, 3)]
        p = out / f"multi{j:02d}.pdf"
        render_many(group, p)
        labels.append({"id": f"multi{j:02d}", "file": p.name, "split": "test", "layout": "multi",
                       "invoices": [g["id"] for g in group], "multi": True})
    (out / "labels.jsonl").write_text("\n".join(json.dumps(x) for x in labels), encoding="utf-8")
    return labels


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=180)
    ap.add_argument("--out", default="eval/generated/pdf")
    a = ap.parse_args()
    print(len(build(a.n, Path(a.out))), "files")


def iban(rng: random.Random) -> str:
    """A UK IBAN with correct check digits, printed in groups of four."""
    bban = "NWBK" + "".join(str(rng.randint(0, 9)) for _ in range(14))
    digits = "".join(str(int(ch, 36)) for ch in bban + "GB00")
    raw = f"GB{98 - int(digits) % 97:02d}{bban}"
    return " ".join(raw[i:i + 4] for i in range(0, len(raw), 4))
