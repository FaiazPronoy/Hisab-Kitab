"""Payment details printed on the invoice. Found by pattern in code, so like
every other value they come with the line they were read from. An IBAN must
pass its mod-97 check; a bare account number needs a label in front of it."""
import re

IBAN = re.compile(r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?)\b")
ACCOUNT = re.compile(r"(?:account\s*(?:no\.?|number|#)|a/c\s*(?:no\.?)?|acct\.?)\s*[:#.]?\s*(\d[\d\s-]{5,22}\d)", re.I)


def iban_ok(raw: str) -> bool:
    s = re.sub(r"\s+", "", raw).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    digits = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(digits) % 97 == 1


def find_bank(lines: list[dict]) -> dict | None:
    for ln in lines:
        text = ln.get("text") or ""
        for m in IBAN.finditer(text):
            if iban_ok(m.group(1)):
                return _rec(re.sub(r"\s+", "", m.group(1)).upper(), "iban", ln, m.group(0))
        m = ACCOUNT.search(text)
        if m:
            return _rec(re.sub(r"[\s-]+", "", m.group(1)), "account", ln, m.group(0))
    return None


def _rec(value, kind, ln, quote):
    p = re.match(r"P(\d+):", ln.get("id") or "")
    return {"value": value, "kind": kind, "quote": quote, "line_id": ln.get("id"), "bbox": ln.get("bbox"),
            "page": int(p.group(1)) if p else None}


def mask(acct: str | None) -> str:
    return "" if not acct else ("..." + acct[-4:] if len(acct) > 4 else acct)
