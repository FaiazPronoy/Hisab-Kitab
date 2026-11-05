"""The no-invented-values check, enforced in code. A value survives only if
its quote is really on the cited page and the value can be read from the
quote. Anything else becomes null with null_reason "unverified"."""
import re

from rapidfuzz import fuzz


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


def value_in_quote(field: str, value: str, quote: str, kind: str) -> bool:
    if not value or not quote:
        return False
    if kind == "amount":
        vd, qd = _digits(value), _digits(quote)
        # 1,250.00 printed, model wrote 1250 or 1250.00: compare without trailing zeros
        return bool(vd) and (vd in qd or vd.rstrip("0") in qd)
    if kind == "date":
        nums = re.findall(r"\d+", value)
        qn = re.findall(r"\d+", quote)
        return bool(nums) and all(n.lstrip("0") in [x.lstrip("0") for x in qn] for n in nums if len(n) >= 1) \
            or _ws(value) in _ws(quote)
    return fuzz.partial_ratio(_ws(value), _ws(quote)) >= 85


def number_on_page(value: str, page_text: str) -> bool:
    """The value's digits must appear in one printed line, in order."""
    vd = _digits(value)
    if not vd:
        return False
    for line in (page_text or "").splitlines():
        ld = _digits(line)
        if vd in ld or vd.rstrip("0") in ld:
            return True
    return False


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


def ground(field: str, out, page_text: str, lines: list[dict], kind: str, min_score: float) -> dict:
    """out is a schema Field_. Returns the evidence record kept for the field."""
    rec = {"value_raw": out.value, "quote": out.quote, "line_id": out.line_id, "model_conf": out.confidence,
           "null_reason": out.null_reason, "verified": False, "bbox": None, "page": None, "line_conf": None}
    if out.value is None:
        rec["null_reason"] = out.null_reason or "not_on_document"
        return rec
    score = quote_score(out.quote or out.value, page_text)
    ok = score >= min_score and value_in_quote(field, out.value, out.quote or out.value, kind)
    if ok and kind in ("amount", "date"):
        # fuzzy quote matching would accept 1,350.00 against a printed 1,250.00,
        # so numbers must appear on the page exactly
        ok = number_on_page(out.value, page_text)
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
