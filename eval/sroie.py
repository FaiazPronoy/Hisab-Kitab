"""Real receipts from a public benchmark: ICDAR 2019 SROIE (scanned receipts
from Malaysian shops, labelled with company, date, address and total).

Our own generator writes the layouts it later reads, which flatters the
numbers. These are photographed and scanned receipts nobody here designed.
A fixed sample of 40 is downloaded at run time from the public mirror and is
never committed. Scoring follows the SROIE task 3 idea of exact match after
normalisation: company letters and digits, date as a calendar date, total as
a number."""
import json
import re
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

BASE = "https://raw.githubusercontent.com/zzzDavid/ICDAR-2019-SROIE/master/data"
SAMPLE = [f"{i:03d}" for i in range(0, 626, 16)][:40]


def fetch(folder: Path) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    got = []
    for sid in SAMPLE:
        img, key = folder / f"sroie_{sid}.jpg", folder / f"sroie_{sid}.json"
        try:
            for url, path in ((f"{BASE}/img/{sid}.jpg", img), (f"{BASE}/key/{sid}.json", key)):
                if not path.exists():
                    with urllib.request.urlopen(url, timeout=30) as r:
                        path.write_bytes(r.read())
            got.append(sid)
        except OSError:
            continue
    return got


def _company(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def _total(s):
    try:
        return Decimal(re.sub(r"[^\d.]", "", str(s or ""))).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _date(s):
    from app.pipeline.extract.normalize import parse_date
    d, _ = parse_date(str(s or ""), True)
    return d


def run(client, h, gen_dir: Path) -> dict:
    folder = gen_dir / "sroie"
    ids = fetch(folder)
    score = {f: {"right": 0, "n": 0} for f in ("company", "date", "total")}
    all_right = processed = 0
    for sid in ids:
        truth = json.loads((folder / f"sroie_{sid}.json").read_text(encoding="utf-8"))
        with open(folder / f"sroie_{sid}.jpg", "rb") as f:
            r = client.post("/api/v1/documents", files=[("files", (f"sroie_{sid}.jpg", f))], headers=h)
        body = r.json()[0] if r.status_code == 202 else {}
        d = client.get(f"/api/v1/documents/{body['document_id']}", headers=h).json() if body.get("document_id") else {}
        inv = client.get(f"/api/v1/invoices/{d['invoices'][0]['id']}", headers=h).json() if d.get("invoices") else {}
        if inv:
            processed += 1
        got = {"company": _company(inv.get("supplier_name")) or None,
               "date": inv.get("invoice_date"),
               "total": _total((inv.get("fields") or {}).get("total", {}).get("value"))}
        want = {"company": _company(truth.get("company")), "date": _date(truth.get("date")), "total": _total(truth.get("total"))}
        ok_all = True
        for f in score:
            if not want[f]:
                continue
            score[f]["n"] += 1
            w = want[f].isoformat() if f == "date" else want[f]
            right = got[f] is not None and got[f] == w
            score[f]["right"] += right
            ok_all &= right
        all_right += ok_all
    return {"n": len(ids), "processed": processed, "fields": score, "all_three_right": all_right}
