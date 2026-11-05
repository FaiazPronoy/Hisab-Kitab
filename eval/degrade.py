"""Turns clean PDFs into scans: rasterize, rotate, blur, add noise and
shadow, compress. Three tiers so OCR quality can be reported per tier."""
import io
import random
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageFilter

TIERS = {
    "clean": dict(dpi=200, rot=0.0, blur=0.0, noise=0, jpeg=92, shadow=False),
    "medium": dict(dpi=150, rot=2.0, blur=0.6, noise=8, jpeg=60, shadow=False),
    "heavy": dict(dpi=110, rot=3.5, blur=1.1, noise=16, jpeg=35, shadow=True),
}


def degrade_image(img: Image.Image, tier: str, rng: random.Random) -> Image.Image:
    t = TIERS[tier]
    img = img.convert("L")
    if t["rot"]:
        img = img.rotate(rng.uniform(-t["rot"], t["rot"]), expand=True, fillcolor=255, resample=Image.BICUBIC)
    if t["blur"]:
        img = img.filter(ImageFilter.GaussianBlur(t["blur"]))
    a = np.asarray(img).astype(np.int16)
    if t["noise"]:
        a = a + np.random.default_rng(rng.randint(0, 10**6)).normal(0, t["noise"], a.shape).astype(np.int16)
    if t["shadow"]:
        grad = np.linspace(0, 70, a.shape[1])[None, :]
        a = a - grad.astype(np.int16)
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=t["jpeg"])
    return Image.open(io.BytesIO(buf.getvalue()))


def pdf_to_scans(src: Path, tier: str, rng: random.Random) -> list[Image.Image]:
    with pymupdf.open(src) as doc:
        z = TIERS[tier]["dpi"] / 72
        pages = [Image.open(io.BytesIO(p.get_pixmap(matrix=pymupdf.Matrix(z, z)).tobytes("png"))) for p in doc]
    return [degrade_image(p, tier, rng) for p in pages]


def write(src: Path, out_dir: Path, tier: str, fmt: str, rng: random.Random) -> Path:
    """fmt: pdf (image-only PDF), jpg, png or tiff (multi-frame)."""
    imgs = pdf_to_scans(src, tier, rng)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{src.stem}_{tier}"
    if fmt == "pdf":
        p = out_dir / f"{stem}.pdf"
        imgs[0].convert("RGB").save(p, save_all=True, append_images=[i.convert("RGB") for i in imgs[1:]], resolution=TIERS[tier]["dpi"])
    elif fmt == "tiff":
        p = out_dir / f"{stem}.tiff"
        imgs[0].save(p, save_all=True, append_images=imgs[1:], compression="tiff_deflate")
    else:
        p = out_dir / f"{stem}.{fmt}"
        imgs[0].convert("RGB").save(p, quality=85) if fmt == "jpg" else imgs[0].save(p)
    return p
