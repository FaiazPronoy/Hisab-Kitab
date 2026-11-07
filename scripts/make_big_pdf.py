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
    p_dig = OUT / f"digital_{pages}.pdf"
    p_scan = OUT / f"scanned_{scanned}.pdf"
    meta_p = OUT / f"meta_{pages}_{scanned}_{seed}.json"
    if p_dig.exists() and p_scan.exists() and meta_p.exists():
        try:
            with pymupdf.open(p_dig) as d1, pymupdf.open(p_scan) as d2:
                if d1.page_count == pages and d2.page_count == scanned:
                    m = json.loads(meta_p.read_text())
                    return [p_dig, p_scan], m.get("invoices", 0)
        except Exception:
            pass
    rng = random.Random(seed)
    fake = Faker("en_GB")
    tmp = OUT / "_one.pdf"
    big = pymupdf.open()
    i = 0
    while big.page_count < pages:
        inv = generator.make(fake, rng, i, rng.choice(["classic", "wholesale", "eu_vat"]))
        inv["line_items"] = inv["line_items"] * 260
        generator.render(inv, tmp)
        with pymupdf.open(tmp) as one:
            big.insert_pdf(one, to_page=min(one.page_count, pages - big.page_count) - 1)
        i += 1
    big.save(OUT / f"digital_{pages}.pdf", garbage=3, deflate=True)
    scan = pymupdf.open()
    with pymupdf.open(OUT / f"digital_{pages}.pdf") as src:
        for n in range(scanned):
            pix = src[n].get_pixmap(dpi=150)
            raw = __import__("PIL.Image", fromlist=["Image"]).open(io.BytesIO(pix.tobytes("png")))
            del pix
            img = degrade.degrade_image(raw, "medium", rng)
            raw.close()
            del raw
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=70)
            img.close()
            del img
            pg = scan.new_page(width=595, height=842)
            pg.insert_image(pg.rect, stream=buf.getvalue())
            del buf
    scan.save(OUT / f"scanned_{scanned}.pdf", deflate=True)
    tmp.unlink(missing_ok=True)
    meta_p.write_text(json.dumps({"invoices": i, "pages": pages, "scanned": scanned, "seed": seed}))
    return [OUT / f"digital_{pages}.pdf", OUT / f"scanned_{scanned}.pdf"], i


def upload_and_time(path: Path, api: str, key: str, workers_label: str | None = None) -> dict:
    h = {"X-API-Key": key}
    workers = workers_label or os.environ.get("WORKERS", "1 worker (concurrency 2)")
    with httpx.Client(timeout=600) as c:
        t0 = time.time()
        with open(path, "rb") as f:
            resp = c.post(f"{api}/documents", files=[("files", (path.name, f))], headers=h)
            if resp.status_code >= 400:
                raise RuntimeError(f"upload failed: {resp.status_code} {resp.text}")
            doc_id = resp.json()[0]["document_id"]
        poll_t0 = time.time()
        while True:
            if time.time() - poll_t0 > 1800:
                raise TimeoutError(f"polling timed out after 1800s for {path.name}")
            r = c.get(f"{api}/documents/{doc_id}?detail=false", headers=h)
            if r.status_code >= 400:
                raise RuntimeError(f"status poll failed: {r.status_code} {r.text}")
            d = r.json()
            status = d.get("status", "unknown")
            print(f"[{path.name}] {d.get('pages_done', 0)}/{d.get('page_count', '?')} pages ({status})...", flush=True)
            if status in ("done", "needs_review", "completed_with_errors", "failed"):
                break
            time.sleep(3)
        wall = time.time() - t0
        d = c.get(f"{api}/documents/{doc_id}", headers=h).json()
        hist = c.get(f"{api}/documents/{doc_id}/history", headers=h).json()
    rss = [int(e["message"].split("rss_mb=")[1].split()[0]) for e in hist if e.get("message") and "rss_mb=" in e["message"]]
    return {"file": path.name, "pages": d["page_count"], "status": d["status"], "wall_seconds": round(wall, 1),
            "pages_per_minute": round(d["page_count"] / wall * 60, 1), "pages_failed": d["pages_failed"],
            "invoices": len(d.get("invoices", [])), "peak_worker_rss_mb": max(rss) if rss else None,
            "workers": workers}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1000)
    ap.add_argument("--scanned", type=int, default=100)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--workers", default=None, help="Explicit worker count label")
    ap.add_argument("--api", default=os.environ.get("API_URL", "http://api:8000/api/v1"))
    a = ap.parse_args()
    files, n = build(a.pages, a.scanned, a.seed)
    print(f"built {files} from {n} synthetic invoices")
    if a.upload:
        key = os.environ.get("API_KEY", "local-dev-key")
        res = [upload_and_time(p, a.api, key, workers_label=a.workers) for p in files]
        print(json.dumps(res, indent=2))
        import subprocess
        try:
            commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        except Exception:
            commit = "unknown"
        data = {"commit": commit, "results": res}
        (OUT / "measured.json").write_text(json.dumps(data, indent=2))
