"""OCR behind one small interface. RapidOCR (ONNX PP-OCR models) is the
primary engine; Tesseract is the fallback when RapidOCR fails or reads less."""
import logging
from functools import lru_cache
from statistics import mean

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)


class OcrEngine:
    name = "base"

    def words(self, img: Image.Image) -> list[dict]:
        """Returns [{t, x0, y0, x1, y1, c}] normalized to the image size."""
        raise NotImplementedError


class RapidEngine(OcrEngine):
    name = "rapidocr"

    def __init__(self):
        from rapidocr import RapidOCR
        self.engine = RapidOCR()

    def words(self, img):
        w, h = img.size
        res = self.engine(np.array(img.convert("RGB")))
        boxes = getattr(res, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return []
        out = []
        for box, txt, score in zip(boxes, res.txts, res.scores):
            # numpy floats do not serialize to JSON, so convert here
            xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
            out.append({"t": str(txt), "x0": min(xs) / w, "y0": min(ys) / h,
                        "x1": max(xs) / w, "y1": max(ys) / h, "c": round(float(score), 3)})
        return out


class TesseractEngine(OcrEngine):
    name = "tesseract"

    def words(self, img):
        import pytesseract
        w, h = img.size
        d = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config="--psm 6")
        out = []
        for i, txt in enumerate(d["text"]):
            conf = float(d["conf"][i])
            if not txt.strip() or conf < 0:
                continue
            x, y, bw, bh = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
            out.append({"t": txt, "x0": x / w, "y0": y / h, "x1": (x + bw) / w, "y1": (y + bh) / h,
                        "c": round(conf / 100, 3)})
        return out


@lru_cache
def get_engine(name: str) -> OcrEngine:
    return RapidEngine() if name == "rapidocr" else TesseractEngine()


def mean_conf(words: list[dict]) -> float:
    if not words:
        return 0.0
    # weight by text length so a long confident line counts more than a stray mark
    total = sum(len(w["t"]) for w in words)
    return sum(w["c"] * len(w["t"]) for w in words) / total if total else mean(w["c"] for w in words)
