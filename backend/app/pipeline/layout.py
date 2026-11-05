"""Turns positioned words into numbered lines like "[P3:L14] Total | 1,250.00".

The LLM cites these ids, and the map from id to box lets the UI highlight
the exact line a value came from.
"""
from statistics import median

COLUMN_GAP = 0.035  # horizontal gap (fraction of page width) shown as " | "


def build_lines(words: list[dict], page_no: int) -> tuple[list[dict], str]:
    """words: [{t, x0, y0, x1, y1, c}] with coordinates normalized to 0..1.
    Returns (lines, layout_text). Each word gets its line_id written back."""
    words = [w for w in words if w.get("t", "").strip()]
    if not words:
        return [], ""
    heights = [w["y1"] - w["y0"] for w in words if w["y1"] > w["y0"]]
    tol = (median(heights) if heights else 0.01) * 0.55

    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: ((w["y0"] + w["y1"]) / 2, w["x0"])):
        cy = (w["y0"] + w["y1"]) / 2
        if rows:
            last = rows[-1]
            last_cy = sum((v["y0"] + v["y1"]) / 2 for v in last) / len(last)
            if abs(cy - last_cy) <= tol:
                last.append(w)
                continue
        rows.append([w])

    lines, out = [], []
    for i, row in enumerate(rows, start=1):
        row.sort(key=lambda w: w["x0"])
        line_id = f"P{page_no}:L{i}"
        parts = [row[0]["t"]]
        for prev, w in zip(row, row[1:]):
            parts.append(" | " if w["x0"] - prev["x1"] > COLUMN_GAP else " ")
            parts.append(w["t"])
        text = "".join(parts)
        for w in row:
            w["line_id"] = line_id
        confs = [w.get("c", 1.0) for w in row]
        lines.append({
            "id": line_id, "text": text, "conf": round(min(confs), 3),
            "bbox": [min(w["x0"] for w in row), min(w["y0"] for w in row),
                     max(w["x1"] for w in row), max(w["y1"] for w in row)],
        })
        out.append(f"[{line_id}] {text}")
    return lines, "\n".join(out)


def cells_to_lines(cells: list[tuple[int, int, str]], sheet_index: int) -> tuple[list[dict], str]:
    """Form-mode sheets: each non-empty cell becomes its own line [S1:R4C2]."""
    lines, out = [], []
    for r, c, v in cells:
        line_id = f"S{sheet_index}:R{r}C{c}"
        lines.append({"id": line_id, "text": v, "conf": 1.0, "bbox": None})
        out.append(f"[{line_id}] {v}")
    return lines, "\n".join(out)
