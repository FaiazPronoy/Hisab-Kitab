"""Label-based parser behind MockProvider. It lets the whole system run and
be tested without an API key, and doubles as a rule-based baseline in the
evaluation. It reads the same line-numbered text the LLM receives."""
import json
import re

from app.pipeline.extract.schema import ColumnMapOut, Field_, InvoiceOut, SameInvoiceOut

LINE = re.compile(r"^\[([A-Z]\d+:[A-Z0-9]+)\] (.*)$", re.M)
AMOUNT = r"[-(]?\s*(?:[A-Z]{3}\s*)?[$€£৳₹]?\s*\d[\d.,' ]*\d(?:\s*[A-Z]{3})?\)?"

LABELS = {
    "invoice_number": r"(?:tax\s+)?invoice\s*(?:no\.?|number|#|num)|inv\s*(?:no\.?|#)|receipt\s*(?:no\.?|#)|credit\s+note\s*(?:no\.?|#)|bill\s*no\.?",
    "invoice_date": r"(?:invoice|issue|bill)?\s*date(?!\s*due)|dated",
    "due_date": r"due\s*date|payment\s+due|due",
    "po_number": r"p\.?o\.?\s*(?:no\.?|number|#)?|purchase\s+order",
    "subtotal": r"sub[\s-]?total|net\s+amount|total\s+before\s+tax",
    "tax": r"(?:total\s+)?(?:tax|vat|gst)(?:\s*\(?\d+(?:[.,]\d+)?\s*%\)?)?(?:\s+amount)?",
    "discount": r"discount",
    "shipping": r"shipping|delivery|freight",
    "total": r"(?:grand\s+)?total(?:\s+due)?|amount\s+due|balance\s+due|total\s+amount",
    "customer_name": r"bill(?:ed)?\s+to|customer|sold\s+to|client",
    "supplier_name": r"from|supplier|vendor|seller",
}
HEADER_WORDS = re.compile(r"description|item|product", re.I)


def _doc(user: str) -> str:
    m = re.search(r"<untrusted_document>\n?(.*?)\n?</untrusted_document>", user, re.S)
    return m.group(1) if m else user


def _lines(doc: str) -> list[tuple[str, str]]:
    return LINE.findall(doc)


def _segments(text: str) -> list[str]:
    return [s.strip() for s in text.split(" | ") if s.strip()]


def _hit(lines, field: str):
    pat = re.compile(rf"^\s*(?:{LABELS[field]})\s*[:.\-]?\s*(.*)$", re.I)
    for i, (lid, text) in enumerate(lines):
        segs = _segments(text)
        for j, seg in enumerate(segs):
            m = pat.match(seg)
            if not m:
                continue
            if field in ("subtotal", "total") and re.match(r"sub", seg, re.I) and field == "total":
                continue
            rest = m.group(1).strip()
            if field in ("supplier_name", "customer_name"):
                if rest:
                    return rest, lid, seg
                if i + 1 < len(lines):
                    nxt = _segments(lines[i + 1][1])
                    if nxt:
                        return nxt[0], lines[i + 1][0], nxt[0]
                continue
            if not rest and j + 1 < len(segs):
                rest = segs[j + 1]
                seg = f"{seg} | {rest}"
            if not rest:
                continue
            if field in ("subtotal", "tax", "discount", "shipping", "total"):
                am = re.findall(AMOUNT, rest)
                if not am:
                    continue
                return am[-1].strip(), lid, seg
            return rest.split("  ")[0].strip(), lid, seg
    return None


def _field(value, lid, quote, conf=0.85) -> dict:
    return Field_(value=value, quote=quote, line_id=lid, confidence=conf).model_dump()


def _null() -> dict:
    return Field_(null_reason="not_on_document").model_dump()


def parse_invoice(doc: str) -> InvoiceOut:
    lines = _lines(doc)
    out = {}
    order = ["subtotal", "total", "tax", "discount", "shipping", "invoice_number", "due_date",
             "invoice_date", "po_number", "customer_name", "supplier_name"]
    used = set()
    for f in order:
        rest = [(lid, t) for lid, t in lines if (lid, f) not in used]
        hit = _hit(rest, f)
        if f == "total" and hit and re.match(r"sub", hit[2], re.I):
            hit = None
        out[f] = _field(*hit) if hit else _null()
    if out["supplier_name"]["value"] is None and lines:
        for lid, text in lines[:4]:
            seg = _segments(text)[0]
            if not re.search(r"invoice|receipt|credit note|page", seg, re.I) and len(seg) > 2:
                out["supplier_name"] = _field(seg, lid, seg, 0.6)
                break
    ccy = None
    for lid, text in lines:
        m = re.search(r"\b(USD|EUR|GBP|BDT|INR|AUD|CAD|SGD|JPY|CHF)\b|[€£৳₹]", text)
        if m:
            ccy = (m.group(0), lid, m.group(0))
            break
    if ccy is None:
        for lid, text in lines:
            if "$" in text:
                ccy = ("$", lid, "$")
                break
    out["currency"] = _field(*ccy, conf=0.8) if ccy else _null()

    items, in_table = [], False
    for lid, text in lines:
        segs = _segments(text)
        if HEADER_WORDS.search(text) and len(segs) >= 3:
            in_table = True
            continue
        if in_table:
            if re.match(r"\s*(sub[\s-]?total|total|tax|vat)", text, re.I):
                break
            nums = [s for s in segs if re.fullmatch(AMOUNT, s)]
            if len(segs) >= 3 and len(nums) >= 2:
                desc = segs[0] if not re.fullmatch(AMOUNT, segs[0]) else None
                vals = nums[-3:] if len(nums) >= 3 else [None] + nums[-2:]
                items.append({"description": desc, "quantity": vals[0], "unit_price": vals[1], "amount": vals[2],
                              "quote": text, "line_id": lid})
    doc_type = "credit_note" if re.search(r"credit\s+note", doc, re.I) else (
        "receipt" if re.search(r"\breceipt\b", doc, re.I) else "invoice")
    return InvoiceOut(doc_type=doc_type, line_items=items, **out)


def answer(schema, user: str) -> str:
    doc = _doc(user)
    if schema is InvoiceOut:
        return parse_invoice(doc).model_dump_json()
    if schema is Field_:
        f = re.search(r'field "(\w+)"', user)
        inv = parse_invoice(doc)
        return getattr(inv, f.group(1)).model_dump_json() if f and hasattr(inv, f.group(1)) else Field_().model_dump_json()
    if schema is SameInvoiceOut:
        nums = re.findall(r"invoice\s*(?:no\.?|number|#)\s*[:.]?\s*([A-Z0-9][\w-]+)", doc, re.I)
        same = len(nums) < 2 or nums[0] == nums[1]
        return SameInvoiceOut(same_invoice=same, confidence=0.6).model_dump_json()
    if schema is ColumnMapOut:
        return ColumnMapOut(mapping={}).model_dump_json()
    return json.dumps({})
