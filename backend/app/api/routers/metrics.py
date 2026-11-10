from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import Document, Invoice, LlmCall
from app.db.session import get_db

router = APIRouter(tags=["metrics"])


@router.get("/metrics/summary")
def summary(db: Session = Depends(get_db)):
    docs = dict(db.execute(select(Document.status, func.count()).group_by(Document.status)).all())
    invs = dict(db.execute(select(Invoice.status, func.count()).group_by(Invoice.status)).all())
    ledger_rows = invs.pop("ledger", 0)
    po_rows = invs.pop("po", 0)
    # Exclude in-flight documents from terminal success/failure rates
    in_flight = docs.get("queued", 0) + docs.get("processing", 0) + docs.get("finalizing", 0)
    terminal_total = sum(docs.values()) - in_flight
    denom = terminal_total if terminal_total > 0 else 1
    ok = docs.get("done", 0) + docs.get("needs_review", 0)
    page = db.execute(text("""
        SELECT source, count(*) n,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) p50,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) p95
        FROM pages WHERE status = 'done' AND duration_ms IS NOT NULL GROUP BY source""")).all()
    llm = db.execute(select(func.count(), func.coalesce(func.sum(LlmCall.cost), 0),
                            func.coalesce(func.sum(LlmCall.tokens_in + LlmCall.tokens_out), 0))
                     .where(LlmCall.cached.is_(False))).one()
    return {
        "documents": docs, "invoices": invs,
        "success_rate": round(ok / denom, 4), "failure_rate": round(docs.get("failed", 0) / denom, 4),
        "completed_with_errors_rate": round(docs.get("completed_with_errors", 0) / denom, 4),
        "needs_review": invs.get("needs_review", 0), "ledger_rows": ledger_rows, "po_rows": po_rows,
        "approved_unpaid": db.scalar(select(func.count()).select_from(Invoice).where(
            Invoice.status == "approved", Invoice.payment_batch_id.is_(None))),
        "page_timing_ms": {r.source: {"n": r.n, "p50": r.p50, "p95": r.p95} for r in page},
        "llm": {"calls": llm[0], "cost_usd": round(float(llm[1]), 5), "tokens": int(llm[2])},
    }
