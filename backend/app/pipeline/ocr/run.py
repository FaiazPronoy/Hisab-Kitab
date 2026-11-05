import logging

from PIL import Image

from app.pipeline.ocr.engines import get_engine, mean_conf
from app.pipeline.ocr.preprocess import preprocess

log = logging.getLogger(__name__)
RETRY_BELOW = 0.68


def ocr_image(img: Image.Image, primary: str = "rapidocr") -> dict:
    """Raw pass first; preprocess and retry only when confidence is low;
    fall back to the other engine if the primary fails or reads nothing."""
    tried = []
    best = {"words": [], "conf": 0.0, "engine": None, "steps": []}

    def attempt(engine_name, image, steps):
        nonlocal best
        try:
            words = get_engine(engine_name).words(image)
        except Exception as e:  # engine crash on one page must not kill the page
            log.warning("ocr engine failed", extra={"ctx": {"stage": engine_name}})
            tried.append((engine_name, f"error:{type(e).__name__}"))
            return
        conf = mean_conf(words)
        tried.append((engine_name, round(conf, 3)))
        if conf > best["conf"] or (not best["words"] and words):
            best = {"words": words, "conf": conf, "engine": engine_name, "steps": steps}

    attempt(primary, img, [])
    if best["conf"] < RETRY_BELOW:
        fixed, steps = preprocess(img)
        attempt(primary, fixed, steps)
        if best["conf"] < RETRY_BELOW:
            other = "tesseract" if primary == "rapidocr" else "rapidocr"
            attempt(other, fixed, steps)
    best["tried"] = tried
    return best
