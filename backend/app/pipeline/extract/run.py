"""One invoice segment in, grounded and normalized fields out.
Order: regex hints, one LLM call, a targeted pass for a missing key field,
and vision only as a last resort on poorly read scans."""
import re
from datetime import date

from app.core.config import validation_config
from app.pipeline.extract import prompts
from app.pipeline.extract.grounding import ground, suspicious
from app.pipeline.extract.normalize import (
    infer_day_first, norm_invoice_number, norm_supplier, number_style, parse_amount, parse_currency, parse_date,
)
from app.pipeline.extract.providers import call_structured
from app.pipeline.extract.schema import AMOUNTS, DATES, SCALARS, Field_, InvoiceOut

LONG_SEGMENT = 10
ITEM_CHUNK = 8
SECOND_PASS = ("invoice_number", "total", "invoice_date")

HINT_PATTERNS = {
    "dates": r"\b\d{1,4}[-/.]\d{1,2}[-/.]\d{2,4}\b|\b\d{1,2}\s+[A-Z][a-z]{2,8}\.?\s+\d{4}\b|\b[A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}\b",
    "currencies": r"\b(?:USD|EUR|GBP|BDT|INR|AUD|CAD|SGD|JPY|CHF)\b|[$€£৳₹]",
    "invoice_numbers": r"\b(?:INV|BILL|CN|RCPT)[-/]?\w*\d[\w-]*\b|#\s?\d{3,}\b",
}


def hints(text: str) -> str:
    out = []
    for name, pat in HINT_PATTERNS.items():
        found = list(dict.fromkeys(re.findall(pat, text)))[:8]
        if found:
            out.append(f"{name}: {', '.join(found)}")
    return "\n".join(out) or "none"


def _kind(field: str) -> str:
    return "amount" if field in AMOUNTS else "date" if field in DATES else "text"


def _segment_text(pages) -> str:
    if len(pages) <= LONG_SEGMENT:
        return "\n".join(p.layout or "" for p in pages)
    keep = pages[:2] + pages[-2:]
    return "\n".join(p.layout or "" for p in keep)


def extract_segment(db, pages, image_loader=None) -> dict:
    cfg = validation_config()
    min_q = cfg["grounding"]["quote_match_min"]
    full_text = "\n".join(p.text or "" for p in pages)
    lines = [ln for p in pages for ln in (p.lines or {}).get("lines", [])]
    doc = _segment_text(pages)
    flags = []
    if suspicious(full_text):
        flags.append("suspicious_content")
    if len(pages) > LONG_SEGMENT:
        flags.append("long_segment")

    out = call_structured(db, purpose="extract", version=prompts.EXTRACT_VERSION, schema=InvoiceOut,
                          system=prompts.EXTRACT_SYSTEM, user=prompts.EXTRACT_USER.format(hints=hints(doc), document=doc))
    if out is None:
        flags.append("extraction_failed")
        out = InvoiceOut()

    if len(pages) > LONG_SEGMENT:
        items = []
        for i in range(0, min(len(pages), 16), ITEM_CHUNK):
            chunk = "\n".join(p.layout or "" for p in pages[i:i + ITEM_CHUNK])
            part = call_structured(db, purpose="extract_items", version=prompts.EXTRACT_VERSION, schema=InvoiceOut,
                                   system=prompts.EXTRACT_SYSTEM, user=prompts.EXTRACT_USER.format(hints="none", document=chunk))
            if part:
                items.extend(part.line_items)
        out.line_items = items or out.line_items

    source = "llm"
    fields = {f: ground(f, getattr(out, f), full_text, lines, _kind(f), min_q) for f in SCALARS}

    for f in SECOND_PASS:
        if fields[f]["value_raw"] is None and fields[f]["null_reason"] == "not_on_document":
            again = call_structured(db, purpose=f"missing_{f}", version=prompts.MISSING_VERSION, schema=Field_,
                                    user=prompts.MISSING_USER.format(field=f, document=doc))
            if again and again.value:
                fields[f] = ground(f, again, full_text, lines, _kind(f), min_q)

    low_ocr = any(p.source == "ocr" and (p.ocr_conf or 0) < cfg["confidence"]["ocr_page_min"] for p in pages)
    key_missing = fields["total"]["value_raw"] is None or fields["invoice_number"]["value_raw"] is None
    if image_loader and low_ocr and key_missing:
        img = image_loader(pages[0])
        if img is not None:
            vis = call_structured(db, purpose="vision", version=prompts.VISION_VERSION, schema=InvoiceOut,
                                  user=prompts.VISION_USER, image=img, vision=True)
            if vis:
                source = "vision"
                for f in SCALARS:
                    if fields[f]["value_raw"] is None:
                        v = getattr(vis, f)
                        if v.value:
                            # no line ids from an image: keep the value, mark it, never verified by text
                            fields[f] = {"value_raw": v.value, "quote": v.quote, "line_id": None, "bbox": None,
                                         "page": pages[0].page_no, "model_conf": v.confidence,
                                         "confidence": min(v.confidence, 0.7), "verified": False,
                                         "null_reason": None, "source": "vision"}
                flags.append("vision_used")

    return normalize(fields, out, full_text, lines, flags, source, min_q)


def normalize(fields: dict, out: InvoiceOut, full_text: str, lines: list, flags: list, source: str, min_q: float) -> dict:
    style = number_style([full_text])
    ccy_raw = fields["currency"]["value_raw"]
    if ccy_raw is None:
        # currency is often only printed next to the total
        ccy_raw = fields["total"]["value_raw"]
    ccy, ambiguous_ccy = parse_currency(ccy_raw)
    if ambiguous_ccy:
        flags.append("ambiguous_currency")
    day_first = infer_day_first([full_text], ccy)

    for name, rec in fields.items():
        rec.setdefault("source", source if rec.get("value_raw") is not None else None)
        raw = rec["value_raw"]
        if raw is None:
            rec["value_norm"] = None
            continue
        if name in AMOUNTS:
            v = parse_amount(raw, style)
            rec["value_norm"] = str(v) if v is not None else None
        elif name in DATES:
            d, amb = parse_date(raw, day_first)
            rec["value_norm"] = d.isoformat() if d else None
            if amb:
                rec["ambiguous_date"] = True
                flags.append(f"ambiguous_date:{name}")
        elif name == "currency":
            rec["value_norm"] = ccy
        else:
            rec["value_norm"] = re.sub(r"\s+", " ", raw).strip()
        if rec["value_norm"] is None:
            rec.update(null_reason="unparseable")
    if fields["currency"]["value_norm"] is None and ccy:
        fields["currency"].update(value_norm=ccy, source="rule", confidence=0.6)

    items = []
    for i, it in enumerate(out.line_items):
        q = it.quote or " ".join(x for x in (it.description, it.quantity, it.unit_price, it.amount) if x)
        ok = bool(q) and (q.lower() in full_text.lower() or ground("amount", Field_(value=it.amount or "", quote=q, line_id=it.line_id, confidence=0.9),
                                                                     full_text, lines, "amount", min_q)["verified"])
        items.append({
            "idx": i, "description": it.description,
            "quantity": _dec(it.quantity, style), "unit_price": _dec(it.unit_price, style), "amount": _dec(it.amount, style),
            "evidence": {"quote": it.quote, "line_id": it.line_id, "verified": ok},
            "confidence": 0.9 if ok else 0.4,
        })

    tax_lines = [{"label": t.label, "rate": t.rate, "amount": _dec(t.amount, style)} for t in out.tax_lines]
    key = validation_config()["key_fields"]
    confs = [fields[f].get("confidence", 0.0) or 0.0 for f in key]
    return {
        "doc_type": out.doc_type if out.doc_type != "other" else "invoice",
        "fields": fields, "line_items": items, "tax_lines": tax_lines, "flags": sorted(set(flags)),
        "overall_confidence": round(min(confs), 3) if confs else 0.0, "style": style,
    }


def _dec(v, style):
    d = parse_amount(v, style)
    return str(d) if d is not None else None


def typed(result: dict) -> dict:
    """Column values for the invoices row."""
    f = result["fields"]

    def val(n):
        return f[n].get("value_norm")

    def d(n):
        v = val(n)
        return date.fromisoformat(v) if v else None

    from decimal import Decimal
    return {
        "invoice_number": val("invoice_number"), "invoice_number_norm": norm_invoice_number(val("invoice_number")),
        "invoice_date": d("invoice_date"), "due_date": d("due_date"),
        "supplier_name": val("supplier_name"), "supplier_norm": norm_supplier(val("supplier_name")),
        "customer_name": val("customer_name"), "po_number": val("po_number"), "currency": val("currency"),
        **{n: (Decimal(val(n)) if val(n) else None) for n in AMOUNTS},
    }
