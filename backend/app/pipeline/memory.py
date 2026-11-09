"""Supplier memory. When a reviewer fixes a field, we look for the fixed value
on the page and keep the label printed before it ("Our ref", "Factuur nr").
The next invoice from that supplier is searched for the same label. A value
found that way still has to pass the normal grounding check, so memory can
only point at text that is really on the page; it never supplies a value.

A corrected supplier name is kept as an alias, so a misspelt header on the
next invoice is filed under the right supplier."""
import re

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.db.models import Page, SupplierAlias, SupplierLabel
from app.pipeline.extract.grounding import _extract_decimals, ground
from app.pipeline.extract.normalize import norm_supplier, number_style, parse_amount, parse_date
from app.pipeline.extract.schema import AMOUNTS, DATES, Field_

# fields that are printed after a label; names and currency are not
LEARNABLE = ["invoice_number", "po_number", "invoice_date", "due_date", "subtotal", "tax", "total"]
MAX_LABEL = 40
ALIAS_MIN = 75
DATE_RE = r"\d{1,4}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}\s+[A-Z][a-z]{2,8}\.?\s+\d{4}|[A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}"
AMOUNT_RE = r"[-(]?\s*(?:[A-Z]{3}\s*)?[$€£৳₹]?\s*\d[\d.,']*\d(?:\s*[A-Z]{3})?\)?|\d"


def _segments(text: str) -> list[str]:
    return [s.strip() for s in text.split(" | ") if s.strip()]


def _clean_label(s: str) -> str | None:
    # the last few words before the value, stopping at anything with a digit
    words = []
    for w in reversed(re.sub(r"[\s:#.\-]+$", "", s).split()):
        if re.search(r"\d", w) or len(words) == 4:
            break
        words.insert(0, w)
    label = re.sub(r"[\s:#.\-]+$", "", " ".join(words)).strip()
    if not label or len(label) > MAX_LABEL or not re.search(r"[A-Za-z]", label):
        return None
    return label


def _value_at(seg: str, field: str, value: str, style: str) -> int | None:
    """Where the corrected value starts inside one line segment, or None."""
    if field in AMOUNTS:
        want = parse_amount(value, style)
        if want is None:
            return None
        for m in re.finditer(r"[-(]?[$€£৳₹]?\s*\d[\d.,' ]*\d|\d", seg):
            if parse_amount(m.group(0), style) == want:
                return m.start()
        return None
    if field in DATES:
        for m in re.finditer(DATE_RE, seg):
            for day_first in (True, False):
                d, _ = parse_date(m.group(0), day_first)
                if d and d.isoformat() == value:
                    return m.start()
        return None
    i = seg.lower().find(value.lower())
    return i if i >= 0 else None


def label_for(lines: list[dict], field: str, value: str, style: str = "us") -> str | None:
    # an amount often repeats (a one-line invoice has amount = subtotal = total);
    # totals sit at the bottom, so the last labelled match is the one meant
    found = None
    for ln in lines:
        segs = _segments(ln.get("text") or "")
        for j, seg in enumerate(segs):
            at = _value_at(seg, field, value, style)
            if at is None:
                continue
            label = _clean_label(seg[:at])
            if label is None and at == 0 and j > 0:
                label = _clean_label(segs[j - 1])
            if label:
                if field not in AMOUNTS:
                    return label
                found = label
    return found


def canonical_supplier(db, name: str | None) -> tuple[str | None, str | None]:
    """(supplier_norm, display name) after following a learned alias."""
    n = norm_supplier(name)
    if not n:
        return n, name
    a = db.get(SupplierAlias, n)
    return (a.supplier_norm, a.supplier_name) if a else (n, name)


def learn(db, inv, field: str, new_value: str | None, old_supplier_norm: str | None = None) -> str | None:
    """Called after a reviewer's correction. Returns what was learned, for the audit trail."""
    if not get_settings().supplier_memory or new_value in (None, ""):
        return None
    if field == "supplier_name":
        new_norm = norm_supplier(new_value)
        # a typo fix, not a different supplier: re-filing a whole supplier needs a close match
        close = bool(old_supplier_norm and new_norm) and fuzz.ratio(old_supplier_norm, new_norm) >= ALIAS_MIN
        if close and old_supplier_norm != new_norm:
            db.merge(SupplierAlias(alias_norm=old_supplier_norm, supplier_norm=new_norm, supplier_name=new_value))
            return f"alias {old_supplier_norm} -> {new_norm}"
        return None
    if field not in LEARNABLE or not inv.supplier_norm or inv.page_start is None:
        return None
    pages = db.scalars(select(Page).where(Page.document_id == inv.document_id,
                                          Page.page_no.between(inv.page_start, inv.page_end or inv.page_start))).all()
    lines = [ln for p in pages for ln in (p.lines or {}).get("lines", [])]
    style = number_style([p.text or "" for p in pages])
    label = label_for(lines, field, str(new_value), style)
    if not label:
        return None
    row = db.scalar(select(SupplierLabel).where(SupplierLabel.supplier_norm == inv.supplier_norm,
                                                SupplierLabel.field == field, SupplierLabel.label == label))
    if row:
        row.hits += 1
    else:
        try:
            with db.begin_nested():
                db.add(SupplierLabel(supplier_norm=inv.supplier_norm, field=field, label=label, learned_from=inv.id))
        except IntegrityError:
            pass  # another reviewer taught the same label a moment ago
    return f"label {field} = {label!r}"


def recall(db, fields: dict, full_text: str, lines: list[dict], min_q: float, style: str) -> list[str]:
    """Fills fields that came back empty, using labels learned for this
    supplier. Changes `fields` in place and returns the names it filled."""
    if not get_settings().supplier_memory:
        return []
    sup = fields.get("supplier_name") or {}
    norm, _ = canonical_supplier(db, sup.get("value_raw"))
    if not norm:
        return []
    learned = db.scalars(select(SupplierLabel).where(SupplierLabel.supplier_norm == norm)
                         .order_by(SupplierLabel.hits.desc())).all()
    filled = []
    for sl in learned:
        rec = fields.get(sl.field)
        if rec is None or rec.get("value_raw") is not None:
            continue
        kind = "amount" if sl.field in AMOUNTS else "date" if sl.field in DATES else "text"
        hit = _find_after_label(lines, sl.label, kind)
        if not hit:
            continue
        value, quote, line_id = hit
        if kind == "amount" and not _extract_decimals(value, style=style):
            continue
        got = ground(sl.field, Field_(value=value, quote=quote, line_id=line_id, confidence=0.9),
                     full_text, lines, kind, min_q, style=style)
        if got.get("value_raw") is not None:
            got["source"] = "memory"
            fields[sl.field] = got
            filled.append(sl.field)
    return filled


def _first_value(rest: str, kind: str) -> str | None:
    pat = DATE_RE if kind == "date" else AMOUNT_RE if kind == "amount" else r"\S+"
    m = re.search(pat, rest)
    return m.group(0).strip() if m else None


def _find_after_label(lines: list[dict], label: str, kind: str):
    pat = re.compile(rf"(?:^|\s){re.escape(label)}\s*[:#.\-]?\s*(.*)$", re.I)
    for ln in lines:
        segs = _segments(ln.get("text") or "")
        for j, seg in enumerate(segs):
            m = pat.search(seg)
            if not m:
                continue
            rest = m.group(1).strip()
            if not rest and j + 1 < len(segs):
                rest = segs[j + 1]
            value = _first_value(rest, kind) if rest else None
            if value:
                return value, seg if rest in seg else f"{seg} {rest}", ln["id"]
    return None
