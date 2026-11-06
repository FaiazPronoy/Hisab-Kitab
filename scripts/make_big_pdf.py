"""Builds the large test files and, with --upload, times them end to end.

python -m scripts.make_big_pdf            # writes data/big/*.pdf
python -m scripts.make_big_pdf --upload   # also uploads and reports measured numbers"""
import argparse
import io
import json
import os
import random
import time
from pathlib import Path

import httpx
import pymupdf
from faker import Faker

from eval import degrade, generator

OUT = Path(os.environ.get("BIG_DIR", "/data/storage/big"))


def build(pages: int, scanned: int, seed: int = 11):
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    fake = Faker("en_GB")
    tmp = OUT / "_one.pdf"
    big = pymupdf.open()
    i = 0
    while big.page_count < pages:
        inv = generator.make(fake, rng, i, rng.choice(["classic", "wholesale", "eu_vat", "multipage"]))
        inv["invoice_number"] = f"INV-BIG-{seed}-{(i // 50):02d}"
        generator.render(inv, tmp)
        with pymupdf.open(tmp) as one:
            big.insert_pdf(one, to_page=min(one.page_count, pages - big.page_count) - 1)
        i += 1
    big.save(OUT / f"digital_{pages}.pdf", garbage=3, deflate=True)
    scan = pymupdf.open()
    with pymupdf.open(OUT / f"digital_{pages}.pdf") as src:
        for n in range(scanned):
            img = degrade.degrade_image(
                __import__("PIL.Image", fromlist=["Image"]).open(io.BytesIO(src[n].get_pixmap(dpi=150).tobytes("png"))),
                "medium", rng)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=70)
            pg = scan.new_page(width=595, height=842)
            pg.insert_image(pg.rect, stream=buf.getvalue())
    scan.save(OUT / f"scanned_{scanned}.pdf", deflate=True)
    tmp.unlink(missing_ok=True)
    return [OUT / f"digital_{pages}.pdf", OUT / f"scanned_{scanned}.pdf"], i


def upload_and_time(path: Path, api: str, key: str) -> dict:
    h = {"X-API-Key": key}
    with httpx.Client(timeout=300) as c:
        t0 = time.time()
        with open(path, "rb") as f:
            resp = c.post(f"{api}/documents", files=[("files", (path.name, f))], headers=h).json()
            doc_id = resp[0]["document_id"]
        while True:
            d = c.get(f"{api}/documents/{doc_id}", headers=h).json()
            print(f"[{path.name}] {d.get('pages_done', 0)}/{d.get('page_count', '?')} pages ({d.get('status')})...", flush=True)
            if d["status"] in ("done", "needs_review", "completed_with_errors", "failed"):
                break
            time.sleep(3)
        wall = time.time() - t0
        hist = c.get(f"{api}/documents/{doc_id}/history", headers=h).json()
    rss = [int(e["message"].split("rss_mb=")[1]) for e in hist if e["message"] and "rss_mb=" in e["message"]]
    return {"file": path.name, "pages": d["page_count"], "status": d["status"], "wall_seconds": round(wall, 1),
            "pages_per_minute": round(d["page_count"] / wall * 60, 1), "pages_failed": d["pages_failed"],
            "invoices": len(d.get("invoices", [])), "peak_worker_rss_mb": max(rss) if rss else None,
            "workers": os.environ.get("WORKERS", "1 worker (concurrency 2)")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1000)
    ap.add_argument("--scanned", type=int, default=100)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--api", default=os.environ.get("API_URL", "http://api:8000/api/v1"))
    a = ap.parse_args()
    files, n = build(a.pages, a.scanned, a.seed)
    print(f"built {files} from {n} synthetic invoices")
    if a.upload:
        key = os.environ.get("API_KEY", "local-dev-key")
        res = [upload_and_time(p, a.api, key) for p in files]
        print(json.dumps(res, indent=2))
        Path("/data/storage/big/measured.json").write_text(json.dumps(res, indent=2))
