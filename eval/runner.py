"""make eval: build the dataset, push every file through the HTTP API in a
separate database, score the results and write EVALUATION.md.

Runs Celery tasks inline (CELERY_EAGER) so each upload returns when the
document is finished, which makes per-document timing exact."""
import argparse
import json
import os
import random
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
GEN = ROOT / "generated"


def _setup_db():
    base = os.environ.get("DATABASE_URL", "postgresql+psycopg://docintel:docintel@postgres:5432/docintel")
    eval_url = base.rsplit("/", 1)[0] + "/docintel_eval"
    os.environ["DATABASE_URL"] = eval_url
    os.environ["CELERY_EAGER"] = "true"
    os.environ["UPLOAD_RATE_LIMIT"] = "100000/minute"
    from sqlalchemy import create_engine, text
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS docintel_eval WITH (FORCE)"))
        c.execute(text("CREATE DATABASE docintel_eval"))
    eng = create_engine(eval_url)
    with eng.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        c.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    from app.db.models import Base
    Base.metadata.create_all(eng)


def build_dataset(n: int, seed: int) -> dict:
    from eval import degrade, generator, sheets_gen, zoo
    rng = random.Random(seed)
    pdf_dir = GEN / "pdf"
    labels = generator.build(n, pdf_dir, seed)
    singles = [x for x in labels if not x.get("multi")]
    test = [x for x in singles if x["split"] == "test" and not x.get("planted")]
    scans = []
    for k, lab in enumerate(rng.sample(test, min(45, len(test)))):
        tier = ["clean", "medium", "heavy"][k % 3]
        fmt = ["pdf", "jpg", "tiff", "png"][k % 4]
        p = degrade.write(pdf_dir / lab["file"], GEN / "scans", tier, fmt, rng)
        scans.append({**lab, "file": p.name, "dir": "scans", "tier": tier, "fmt": fmt, "source_pdf": lab["file"]})
    ledger = sheets_gen.ledger([x for x in singles if x["split"] == "test"], GEN / "sheets", rng)
    zoo_files = zoo.build(GEN / "zoo")
    return {"pdf": labels, "scans": scans, "ledger": ledger, "zoo": zoo_files}


def upload(client, path: Path, headers) -> tuple[dict, float]:
    t0 = time.perf_counter()
    with open(path, "rb") as f:
        r = client.post("/api/v1/documents", files=[("files", (path.name, f))], headers=headers)
    return {"code": r.status_code, "body": r.json()}, time.perf_counter() - t0


def run(n: int, seed: int, include_scans: bool):
    _setup_db()
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import app
    import logging
    logging.getLogger().setLevel(logging.WARNING)
    data = build_dataset(n, seed)
    s = get_settings()
    h = {"X-API-Key": s.api_key}
    client = TestClient(app)
    results = []

    def push(kind, lab, path):
        resp, secs = upload(client, path, h)
        doc_id = resp["body"][0]["document_id"] if resp["code"] == 202 and resp["body"][0].get("document_id") else None
        detail = client.get(f"/api/v1/documents/{doc_id}", headers=h).json() if doc_id else None
        invs = []
        for i in (detail or {}).get("invoices", []):
            invs.append(client.get(f"/api/v1/invoices/{i['id']}", headers=h).json())
        results.append({"kind": kind, "label": lab, "file": path.name, "secs": secs, "upload": resp,
                        "document": detail, "invoices": invs})

    # dev invoices go in too, unscored, so planted duplicates have their original
    for lab in data["pdf"]:
        if lab["split"] == "dev" and not lab.get("multi"):
            push("dev", lab, GEN / "pdf" / lab["file"])
    for lab in data["pdf"]:
        if lab["split"] == "test" and not lab.get("multi"):
            push("pdf", lab, GEN / "pdf" / lab["file"])
    for z in data["zoo"]:
        push("zoo", z, GEN / "zoo" / z["file"])
    # later uploads can change earlier invoices (a duplicate flags both), so read every result again at the end
    for r in results:
        r["invoices"] = [client.get(f"/api/v1/invoices/{i['id']}", headers=h).json() for i in r["invoices"]]
    led = data["ledger"]
    push("ledger", led, GEN / "sheets" / led["file"])
    ledger_doc = results[-1]["document"]["id"]
    # the ledger is compared with the digital test invoices only; scans and multi-invoice files are copies of them
    test_docs = [r["document"]["id"] for r in results if r["kind"] == "pdf" and not r["label"].get("multi") and r["document"]]
    recon = client.post("/api/v1/reconciliations", headers=h, json={"kind": "ledger", "ledger_document_id": ledger_doc,
                                                                     "invoice_document_ids": test_docs}).json()
    metrics = client.get("/api/v1/metrics/summary", headers=h).json()

    # scans and multi-invoice files are copies of test invoices; in the same database
    # they would all be real duplicates, so they run in a second, empty phase
    from sqlalchemy import text

    from app.db.session import engine
    with engine.begin() as c:
        c.execute(text("TRUNCATE documents, reconciliation_runs, llm_calls, failed_tasks CASCADE"))
    for lab in data["pdf"]:
        if lab.get("multi"):
            push("pdf", lab, GEN / "pdf" / lab["file"])
    if include_scans:
        for lab in data["scans"]:
            push("scan", lab, GEN / "scans" / lab["file"])
    phase2 = client.get("/api/v1/metrics/summary", headers=h).json()
    metrics["page_timing_ms"].update({k: v for k, v in phase2["page_timing_ms"].items() if k == "ocr"})
    for k in ("calls", "tokens", "cost_usd"):
        metrics["llm"][k] += phase2["llm"][k]

    from eval import ocr_bench, report, scorer
    bench = ocr_bench.run(data["scans"], GEN) if include_scans else {}
    scores = scorer.score(results, recon, led, metrics)
    scores["ocr_engines"] = bench
    scores["config"] = {"llm_provider": s.llm_provider, "llm_model": s.llm_model if s.llm_provider != "mock" else "mock (rule parser)",
                        "n_generated": n, "seed": seed}
    OUT.mkdir(parents=True, exist_ok=True)
    p_name = "gemini" if s.llm_provider == "gemini" else "mock"
    (OUT / f"results_{p_name}.json").write_text(json.dumps(scores, indent=2, default=str), encoding="utf-8")
    (OUT / "results.json").write_text(json.dumps(scores, indent=2, default=str), encoding="utf-8")

    mock_p = OUT / "results_mock.json"
    gemini_p = OUT / "results_gemini.json"
    if mock_p.exists() and gemini_p.exists():
        try:
            scores["comparison"] = {
                "mock": json.loads(mock_p.read_text(encoding="utf-8")),
                "gemini": json.loads(gemini_p.read_text(encoding="utf-8")),
            }
        except Exception:
            pass

    out_file = Path("/repo/EVALUATION.md") if Path("/repo/EVALUATION.md").exists() else (ROOT.parent / "EVALUATION.md")
    report.write(scores, out_file)
    if out_file != ROOT.parent / "EVALUATION.md":
        report.write(scores, ROOT.parent / "EVALUATION.md")
    print(json.dumps(scores["headline"], indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=180)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-scans", action="store_true")
    a = ap.parse_args()
    run(a.n, a.seed, not a.no_scans)
