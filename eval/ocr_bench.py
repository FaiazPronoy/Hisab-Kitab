"""RapidOCR vs Tesseract on the degraded scans: character error rate against
the text layer of the clean source PDF, and seconds per page."""
import time
from pathlib import Path

import pymupdf
from rapidfuzz.distance import Levenshtein

from app.pipeline import images
from app.pipeline.ocr.engines import get_engine


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def cer(pred: str, ref: str) -> float:
    ref, pred = _norm(ref), _norm(pred)
    return Levenshtein.distance(pred, ref) / max(len(ref), 1)


def _ref_text(pdf: Path) -> str:
    with pymupdf.open(pdf) as d:
        return d[0].get_text()


def run(scans: list[dict], gen: Path, per_tier: int = 6) -> dict:
    out = {}
    for engine in ("rapidocr", "tesseract"):
        eng = get_engine(engine)
        for tier in ("clean", "medium", "heavy"):
            rows = [s for s in scans if s["tier"] == tier][:per_tier]
            errs, secs = [], []
            for s in rows:
                img = images.load_frames(gen / "scans" / s["file"], 80_000_000)[0] if not s["file"].endswith(".pdf") else None
                if img is None:
                    with pymupdf.open(gen / "scans" / s["file"]) as d:
                        from app.pipeline.pdf import render
                        img = render(d[0], 200, 60_000_000)
                t0 = time.perf_counter()
                words = eng.words(img)
                secs.append(time.perf_counter() - t0)
                errs.append(cer(" ".join(w["t"] for w in sorted(words, key=lambda w: (round(w["y0"], 2), w["x0"]))),
                                _ref_text(gen / "pdf" / s["source_pdf"])))
            if rows:
                out.setdefault(engine, {})[tier] = {"n": len(rows), "cer": round(sum(errs) / len(errs), 4),
                                                    "sec_per_page": round(sum(secs) / len(secs), 3)}
    return out
