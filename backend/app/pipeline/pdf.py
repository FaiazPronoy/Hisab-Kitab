import io

import pymupdf
from PIL import Image

from app.pipeline.ingest import IngestError

MIN_CHARS = 40
MIN_GOOD_RATIO = 0.85
MAX_IMAGE_COVER = 0.85


def open_pdf(path) -> pymupdf.Document:
    try:
        doc = pymupdf.open(path)
    except Exception:
        raise IngestError("CORRUPT_FILE", "The PDF is damaged and cannot be opened.")
    if doc.needs_pass and not doc.authenticate(""):
        raise IngestError("ENCRYPTED_PDF", "The PDF is password protected.")
    if doc.page_count == 0:
        raise IngestError("EMPTY_PDF", "The PDF has no pages.")
    return doc


def classify_page(page: pymupdf.Page) -> tuple[str, str, list]:
    """Decide per page whether the text layer can be trusted.
    Returns (source, reason, raw words)."""
    words = page.get_text("words")
    text = "".join(w[4] for w in words)
    real = sum(ch.isalnum() for ch in text)
    if real < MIN_CHARS:
        return "ocr", f"few_chars:{real}", words
    good = sum(ch.isalnum() or ch in ".,:;/-$%()#@&'\"€£" for ch in text)
    ratio = good / max(len(text), 1)
    if ratio < MIN_GOOD_RATIO or "�" in text:
        return "ocr", f"garbled:{ratio:.2f}", words
    area = abs(page.rect)
    covered = 0.0
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & page.rect
        covered = max(covered, abs(r) / area if area else 0)
    if covered > MAX_IMAGE_COVER:
        return "ocr", f"image_cover:{covered:.2f}", words
    return "text_layer", "text_ok", words


def text_words(page: pymupdf.Page, raw) -> list[dict]:
    w, h = page.rect.width, page.rect.height
    return [{"t": x[4], "x0": x[0] / w, "y0": x[1] / h, "x1": x[2] / w, "y1": x[3] / h, "c": 1.0}
            for x in raw if x[4].strip()]


def render(page: pymupdf.Page, dpi: int, max_pixels: int) -> Image.Image:
    zoom = dpi / 72
    px = page.rect.width * zoom * page.rect.height * zoom
    if px > max_pixels:
        zoom *= (max_pixels / px) ** 0.5
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def tables_text(path, page_no: int) -> str:
    """Digital tables as row text, used as an extra hint for line items."""
    import pdfplumber
    try:
        with pdfplumber.open(path, pages=[page_no]) as pdf:
            rows = []
            for t in pdf.pages[0].extract_tables():
                for r in t:
                    cells = [(c or "").replace("\n", " ").strip() for c in r]
                    if any(cells):
                        rows.append(" | ".join(cells))
            return "\n".join(rows)
    except Exception:
        return ""
