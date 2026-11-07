"""Raw printed strings to typed values. Money is Decimal end to end."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

EU_NUM = re.compile(r"\d{1,3}(?:\.\d{3})+,\d{1,2}\b|\b\d+,\d{2}\b(?!\d)")
US_NUM = re.compile(r"\d{1,3}(?:,\d{3})+\.\d{1,2}\b|\b\d+\.\d{2}\b")

CURRENCY_SYMBOLS = {"€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR", "৳": "BDT", "Tk": "BDT", "₽": "RUB", "₩": "KRW"}
DOLLAR_PREFIX = {"US$": "USD", "A$": "AUD", "AU$": "AUD", "C$": "CAD", "CA$": "CAD", "NZ$": "NZD", "S$": "SGD", "HK$": "HKD"}
ISO_CODES = {"USD", "EUR", "GBP", "BDT", "INR", "AUD", "CAD", "NZD", "SGD", "HKD", "JPY", "CHF", "SEK", "NOK", "DKK",
             "PLN", "CZK", "AED", "SAR", "MYR", "THB", "CNY", "ZAR", "BRL", "MXN", "PKR", "LKR", "NPR"}
DAY_FIRST_CCY = {"GBP", "EUR", "AUD", "NZD", "BDT", "INR", "PKR", "LKR", "NPR", "SGD", "HKD", "ZAR", "AED", "SAR", "MYR"}

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def number_style(texts: list[str]) -> str:
    """'eu' (1.234,56) or 'us' (1,234.56), voted over every amount on the document."""
    joined = "\n".join(t for t in texts if t)
    eu, us = len(EU_NUM.findall(joined)), len(US_NUM.findall(joined))
    return "eu" if eu > us else "us"


def parse_amount(raw, style: str = "us") -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, (int, Decimal)):
        return Decimal(raw)
    if isinstance(raw, float):
        return Decimal(str(raw))
    s = str(raw).strip()
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
    if style == "eu":
        num = num.replace(".", "").replace(",", ".")
    else:
        # lone comma with two decimals in a US-style document, e.g. "12,50"
        if "," in num and "." not in num and re.fullmatch(r"\d+,\d{2}", num):
            num = num.replace(",", ".")
        num = num.replace(",", "")
    if num.count(".") > 1:
        head, _, tail = num.rpartition(".")
        num = head.replace(".", "") + "." + tail
    try:
        val = Decimal(num.rstrip("."))
    except InvalidOperation:
        return None
    return -val if neg else val


def parse_currency(raw: str | None) -> tuple[str | None, bool]:
    """Returns (ISO code, ambiguous). A bare '$' is ambiguous."""
    if not raw:
        return None, False
    s = str(raw).strip()
    up = s.upper()
    for code in sorted(ISO_CODES):
        if re.search(rf"\b{code}\b", up):
            return code, False
    for p, code in DOLLAR_PREFIX.items():
        if p.upper() in up:
            return code, False
    for sym, code in CURRENCY_SYMBOLS.items():
        if sym in s:
            return code, False
    if "$" in s:
        return "USD", True
    if re.search(r"\b(taka|tk)\b", s, re.I):
        return "BDT", False
    return None, False


def _mk(y, m, d) -> date | None:
    try:
        if y < 100:
            y += 2000
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(raw, day_first: bool | None = None) -> tuple[date | None, bool]:
    """Returns (date, ambiguous). day_first comes from document context when known."""
    if raw is None:
        return None, False
    if isinstance(raw, datetime):
        return raw.date(), False
    if isinstance(raw, date):
        return raw, False
    s = str(raw).strip()
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3])), False
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?[\s\-./]+([A-Za-z]{3,9})\.?[\s\-./,]+(\d{2,4})", s)
    if m and m[2][:3].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1])), False
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{2,4})", s)
    if m and m[1][:3].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])), False
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if a > 12:
            return _mk(y, b, a), False
        if b > 12:
            return _mk(y, a, b), False
        if a == b:
            return _mk(y, a, b), False
        first = True if day_first is None else day_first
        d = _mk(y, b, a) if first else _mk(y, a, b)
        return d, day_first is None
    return None, False


def infer_day_first(texts: list[str], currency: str | None) -> bool | None:
    """Unambiguous dates elsewhere on the document decide; then currency."""
    votes = 0
    for t in texts:
        for a, b in re.findall(r"\b(\d{1,2})[-/.](\d{1,2})[-/.]\d{2,4}\b", t or ""):
            a, b = int(a), int(b)
            if a > 12 >= b:
                votes += 1
            elif b > 12 >= a:
                votes -= 1
    if votes:
        return votes > 0
    if currency == "USD":
        return False
    if currency in DAY_FIRST_CCY:
        return True
    return None


LEGAL = re.compile(r"\b(ltd|limited|inc|incorporated|llc|plc|gmbh|co|corp|corporation|company|pvt|private|sa|ag|bv|srl)\b\.?", re.I)


def norm_supplier(name: str | None) -> str | None:
    if not name:
        return None
    s = LEGAL.sub(" ", name.lower())
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip() or None


def norm_invoice_number(num: str | None) -> str | None:
    if not num:
        return None
    s = re.sub(r"[\s\-_/.#:]", "", str(num).upper())
    s = re.sub(r"^(INVOICE|INV|NO|NUMBER)+", "", s) or s
    return s or None


def ocr_variant(a: str | None, b: str | None) -> bool:
    """INV-108 vs INV-1O8: same after folding characters OCR confuses."""
    if not a or not b or a == b:
        return False
    fold = str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2", "G": "6"})
    return a.translate(fold) == b.translate(fold)
