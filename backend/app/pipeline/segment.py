"""Splits a multi-page PDF into invoices. Each page boundary is scored from
cheap signals at the top and bottom of the page; only boundaries the
signals cannot decide go to the LLM."""
import re

TITLE = re.compile(r"\b(tax\s+invoice|invoice|credit\s+note|receipt|bill)\b", re.I)
NUMBER = re.compile(r"(?:invoice|inv|receipt|credit\s+note|bill)\s*(?:no\.?|number|#)?\s*[:.]?\s*([A-Z]{0,5}[-/]?\d[\w/-]{2,})", re.I)
PAGE_OF = re.compile(r"page\s+(\d+)\s*(?:of|/)\s*(\d+)", re.I)
END = re.compile(r"\b(grand\s+total|total\s+due|amount\s+due|balance\s+due|total)\b", re.I)
HEADER = re.compile(r"\b(description|qty|quantity|unit\s+price)\b", re.I)


def page_signals(text: str) -> dict:
    text = text or ""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    n = len(lines)
    top = "\n".join(lines[: max(3, n // 4)])
    bottom = "\n".join(lines[-max(3, n // 4):]) if lines else ""
    num = NUMBER.search(top) or NUMBER.search(text)
    po = PAGE_OF.search(text)
    return {
        "blank": len(re.sub(r"\s", "", text)) < 15,
        "title": bool(TITLE.search(top)),
        "number": num.group(1).upper() if num else None,
        "page_of": (int(po.group(1)), int(po.group(2))) if po else None,
        "ends": bool(END.search(bottom)),
        "header_row": bool(HEADER.search(top)),
        "first_line": lines[0].strip().lower() if lines else "",
    }


def boundary_score(prev: dict, cur: dict) -> float:
    """> 0.5 means a new invoice starts on cur. 0.5 means undecided."""
    if cur["page_of"]:
        return 0.95 if cur["page_of"][0] == 1 else 0.05
    score = 0.5
    if prev["number"] and cur["number"]:
        return 0.95 if prev["number"] != cur["number"] else 0.05
    if cur["title"]:
        score += 0.2
    if prev["ends"]:
        score += 0.15
    if cur["first_line"] and prev["first_line"] and cur["first_line"] != prev["first_line"]:
        score += 0.05
    if not cur["title"] and cur["header_row"]:
        score -= 0.25
    if not prev["ends"]:
        score -= 0.15
    return max(0.0, min(1.0, score))


def segment(texts: list[str], ask_same=None) -> list[dict]:
    """texts: page texts in order (index 0 = page 1). ask_same(a, b) -> (same, conf)
    is only called for undecided boundaries. Blank pages separate invoices and
    are not part of either."""
    sig = [page_signals(t) for t in texts]
    segs, cur, conf = [], [], 1.0
    prev = None
    for i, s in enumerate(sig):
        if s["blank"]:
            if cur:
                segs.append((cur, conf))
            cur, conf, prev = [], 1.0, None
            continue
        if prev is None:
            cur = [i]
        else:
            sc = boundary_score(sig[prev], s)
            if 0.35 <= sc <= 0.65 and ask_same is not None:
                same, c = ask_same(texts[prev][:400], texts[i][:400])
                sc = 1 - c if same else c
            if sc > 0.5:
                segs.append((cur, conf))
                cur, conf = [i], 1.0
            else:
                cur.append(i)
            conf = min(conf, abs(sc - 0.5) * 2)
        prev = i
    if cur:
        segs.append((cur, conf))
    return [{"page_start": p[0] + 1, "page_end": p[-1] + 1, "confidence": round(c if len(p) > 1 else 1.0, 2)}
            for p, c in segs]
