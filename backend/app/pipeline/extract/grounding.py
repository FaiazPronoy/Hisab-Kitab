"""The no-invented-values check, enforced in code. A value survives only if
its quote is really on the cited page and the value can be read from the
quote. Anything else becomes null with null_reason "unverified"."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from rapidfuzz import fuzz

NUMERIC_TOKENS = re.compile(r"\(?[-+]?[$€£৳₹]?\s*\d[\d.,'  ]*\d\)?|\b\d+\b")


def parse_token_amount(token: str, style: str = "us") -> Decimal | None:
    if not token:
        return None
    s = str(token).strip()
    if not s:
        return None
    neg = False
    if re.search(r"\(\s*[^)]*\d[^)]*\)", s) or re.search(r"\b(CR|Cr)\b", s) or re.search(r"\d-\s*$", s):
        neg = True
    if re.search(r"(^|[\s:])-\s*[\d.,]", s) or s.startswith("-") or "−" in s:
        neg = True
    m = re.search(r"\d[\d.,'  ]*", s)
    if not m:
        return None
    num = m.group(0).strip().replace("'", "").replace(" ", "").replace(" ", "")
    if not num:
        return None

    has_comma = "," in num
    has_dot = "." in num

    if has_comma and has_dot:
        if num.rfind(".") > num.rfind(","):
            num = num.replace(",", "")
        else:
            num = num.replace(".", "").replace(",", ".")
    elif has_comma:
        if re.fullmatch(r"\d+,\d{3}", num):
            num = num.replace(",", ".") if style == "eu" else num.replace(",", "")
        elif re.fullmatch(r"\d{1,3}(?:,\d{3})+", num):
            num = num.replace(",", "")
        else:
            num = num.replace(",", ".")
    elif has_dot:
        if re.fullmatch(r"\d+\.\d{3}", num):
            num = num.replace(".", "") if style == "eu" else num
        elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", num):
            num = num.replace(".", "")

    try:
        val = Decimal(num.rstrip("."))
    except InvalidOperation:
        return None
    return -val if neg else val


def parse_model_value(value: str, style: str = "us") -> Decimal | None:
    if not value:
        return None
    s = str(value).strip()
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", s):
        try:
            return Decimal(s)
        except InvalidOperation:
            return None
    return parse_token_amount(s, style=style)


def _extract_decimals(text: str, style: str = "us") -> list[Decimal]:
    out = []
    for token in NUMERIC_TOKENS.findall(text or ""):
        d = parse_token_amount(token, style=style)
        if d is not None and d not in out:
            out.append(d)
    return out


def _extract_candidate_dates(quote: str) -> list[date]:
    from app.pipeline.extract.normalize import MONTHS, _mk
    candidates = []
    for m in re.finditer(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", quote):
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d and d not in candidates:
            candidates.append(d)
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-./]+([A-Za-z]{3,9})\.?[\s\-./,]+(\d{2,4})\b", quote):
        mon = m.group(2)[:3].lower()
        if mon in MONTHS:
            d = _mk(int(m.group(3)), MONTHS[mon], int(m.group(1)))
            if d and d not in candidates:
                candidates.append(d)
    for m in re.finditer(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{2,4})\b", quote):
        mon = m.group(1)[:3].lower()
        if mon in MONTHS:
            d = _mk(int(m.group(3)), MONTHS[mon], int(m.group(2)))
            if d and d not in candidates:
                candidates.append(d)
    for m in re.finditer(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b", quote):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12 >= b:
            d = _mk(y, b, a)
            if d and d not in candidates:
                candidates.append(d)
        elif b > 12 >= a:
            d = _mk(y, a, b)
            if d and d not in candidates:
                candidates.append(d)
        elif a <= 12 and b <= 12:
            d1 = _mk(y, b, a)
            d2 = _mk(y, a, b)
            if d1 and d1 not in candidates:
                candidates.append(d1)
            if d2 and d2 not in candidates:
                candidates.append(d2)
    return candidates


def _ws(s: str) -> str:
    # " | " is the column marker from layout text; page text has plain spaces there
    return re.sub(r"\s+", " ", (s or "").replace(" | ", " ")).strip().lower()


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def quote_score(quote: str, page_text: str) -> float:
    q, t = _ws(quote), _ws(page_text)
    if not q:
        return 0.0
    if q in t:
        return 1.0
    return fuzz.partial_ratio(q, t) / 100.0


def value_in_quote(field: str, value: str, quote: str, kind: str, style: str = "us") -> bool:
    if not value or not quote:
        return False

    if kind == "amount":
        val_dec = parse_model_value(value, style=style)
        if val_dec is not None:
            quote_decs = _extract_decimals(quote, style=style)
            return any(val_dec == qd for qd in quote_decs)
        return False

    if field in ("invoice_number", "po_number"):
        v_norm = re.sub(r"[^A-Za-z0-9]", "", value).upper()
        q_norm = re.sub(r"[^A-Za-z0-9]", "", quote).upper()
        return bool(v_norm) and v_norm in q_norm

    if field in ("supplier_name", "customer_name"):
        # Name rule: casefolded, punctuation-stripped containment; or fuzzy ratio >= 95 with identical digit sequences.
        v_norm = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", value.casefold())).strip()
        q_norm = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", quote.casefold())).strip()
        if not v_norm or not q_norm:
            return False
        if v_norm in q_norm:
            return True
        v_digits = re.findall(r"\d+", value)
        q_digits = re.findall(r"\d+", quote)
        return fuzz.ratio(v_norm, q_norm) >= 95 and v_digits == q_digits

    if field == "currency" or kind == "currency":
        from app.pipeline.extract.normalize import CURRENCY_SYMBOLS, DOLLAR_PREFIX, ISO_CODES
        val_upper = value.strip().upper()
        symbols_to_check = set()
        if val_upper in ISO_CODES:
            symbols_to_check.add(val_upper)
            for sym, code in CURRENCY_SYMBOLS.items():
                if code == val_upper:
                    symbols_to_check.add(sym)
            for p, code in DOLLAR_PREFIX.items():
                if code == val_upper:
                    symbols_to_check.add(p)
            if val_upper == "USD":
                symbols_to_check.add("$")
        else:
            symbols_to_check.add(value.strip())

        for sym in symbols_to_check:
            if re.fullmatch(r"[A-Z]{3}", sym):
                if re.search(rf"\b{re.escape(sym)}\b", quote, re.I):
                    return True
            else:
                if sym in quote:
                    return True
        return False

    if kind == "date":
        from app.pipeline.extract.normalize import parse_date
        val_date, _ = parse_date(value)
        if not val_date:
            return False
        candidates = _extract_candidate_dates(quote)
        return any(val_date == cd for cd in candidates)

    v_norm = _ws(value)
    q_norm = _ws(quote)
    return bool(v_norm) and v_norm in q_norm


def number_on_page(value: str, page_text: str, style: str = "us") -> bool:
    """The value's decimal amount must appear in one printed line."""
    val_dec = parse_model_value(value, style=style)
    if val_dec is not None:
        for line in (page_text or "").splitlines():
            line_decs = _extract_decimals(line, style=style)
            if any(val_dec == ld for ld in line_decs):
                return True
        return False
    return False


def date_on_page(value: str, page_text: str) -> bool:
    """The date must be printed on one line. Dates are not amounts: 16.01.2026
    read as a number would never match."""
    from app.pipeline.extract.normalize import parse_date
    val_date, _ = parse_date(value)
    if not val_date:
        return False
    return any(val_date in _extract_candidate_dates(line) for line in (page_text or "").splitlines())


def find_line(lines: list[dict], quote: str, line_id: str | None) -> dict | None:
    by_id = {ln["id"]: ln for ln in lines}
    if line_id and line_id in by_id and fuzz.partial_ratio(_ws(quote), _ws(by_id[line_id]["text"])) >= 80:
        return by_id[line_id]
    best, score = None, 0
    for ln in lines:
        s = fuzz.partial_ratio(_ws(quote), _ws(ln["text"]))
        if s > score:
            best, score = ln, s
    return best if score >= 85 else None


def ground(field: str, out, page_text: str, lines: list[dict], kind: str, min_score: float, style: str = "us") -> dict:
    """out is a schema Field_. Returns the evidence record kept for the field."""
    rec = {"value_raw": out.value, "quote": out.quote, "line_id": out.line_id, "model_conf": out.confidence,
           "null_reason": out.null_reason, "verified": False, "bbox": None, "page": None, "line_conf": None}
    if out.value is None:
        rec["null_reason"] = out.null_reason or "not_on_document"
        return rec
    score = quote_score(out.quote or out.value, page_text)
    ok = score >= min_score and value_in_quote(field, out.value, out.quote or out.value, kind, style=style)
    # fuzzy quote matching would accept 1,350.00 against a printed 1,250.00,
    # so amounts and dates must appear on the page exactly
    if ok and kind == "amount":
        ok = number_on_page(out.value, page_text, style=style)
    elif ok and kind == "date":
        ok = date_on_page(out.value, page_text)
    if not ok:
        rec.update(value_raw=None, null_reason="unverified", rejected_value=out.value, quote_score=round(score, 3))
        return rec
    ln = find_line(lines, out.quote or out.value, out.line_id)
    if ln:
        rec.update(line_id=ln["id"], bbox=ln.get("bbox"), line_conf=ln.get("conf"))
        m = re.match(r"P(\d+):", ln["id"])
        rec["page"] = int(m.group(1)) if m else None
    rec["verified"] = True
    rec["quote_score"] = round(score, 3)
    rec["confidence"] = round(min(out.confidence, ln.get("conf", 1.0) if ln else 0.7, score), 3)
    return rec


INJECTION = re.compile(
    r"ignore (all |any )?(previous|prior|above) instructions|disregard (the|all) (rules|instructions)|"
    r"you are now|system prompt|act as an? |set (the )?total to|respond with|do not flag", re.I)


def suspicious(text: str) -> bool:
    return bool(INJECTION.search(text or ""))
