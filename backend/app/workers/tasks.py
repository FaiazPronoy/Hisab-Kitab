"""Thin Celery wrappers. Deterministic file problems never retry; network
and LLM errors retry with backoff; whoever finishes the last page starts
finalize (an atomic counter, not a chord)."""
import logging

from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import get_settings
from app.db.models import Document
from app.db.session import SessionLocal
from app.pipeline import index as index_mod
from app.pipeline import process
from app.pipeline.extract.providers import BudgetExceeded, LlmError
from app.workers.celery_app import celery

logger = logging.getLogger(__name__)
HEAVY_PAGES = 60

retry_kw = dict(autoretry_for=(LlmError, ConnectionError, TimeoutError), retry_backoff=True, retry_backoff_max=60,
                retry_jitter=True, max_retries=3) if not s.celery_eager else dict()


def _scoped():
    return SessionLocal()


@celery.task(bind=True, acks_late=True, **retry_kw)
def ingest(self, document_id: str):
    with SessionLocal() as db:
        ranges = process.run_ingest(db, document_id)
        doc = db.get(Document, document_id)
        heavy = doc.page_count > HEAVY_PAGES
        db.commit()
    # big scans go to their own queue so a one-page receipt never waits behind them
    task = pages_heavy if heavy else pages
    for a, b in ranges:
        task.delay(document_id, a, b)


def _pages(self, document_id, start, end):
    try:
        last = process.run_pages(_scoped, document_id, start, end)
    except SoftTimeLimitExceeded:
        process.record_task_failure(_scoped, "pages", [document_id, start, end], TimeoutError("page range time limit"))
        raise
    if last:
        finalize.delay(document_id)


s = get_settings()


@celery.task(bind=True, acks_late=True, soft_time_limit=s.page_time_limit_s * s.page_batch_size, **retry_kw)
def pages(self, document_id: str, start: int, end: int):
    _pages(self, document_id, start, end)


@celery.task(bind=True, acks_late=True, soft_time_limit=s.page_time_limit_s * s.page_batch_size, **retry_kw)
def pages_heavy(self, document_id: str, start: int, end: int):
    _pages(self, document_id, start, end)


@celery.task(bind=True, acks_late=True, **retry_kw)
def finalize(self, document_id: str):
    try:
        with SessionLocal() as db:
            ids = process.run_finalize(db, document_id)
            db.commit()
    except BudgetExceeded:
        with SessionLocal() as db:
            doc = db.get(Document, document_id)
            process.fail_document(db, doc, "LLM_BUDGET", "The LLM spending cap was reached.")
            db.commit()
        return
    except LlmError as e:
        with SessionLocal() as db:
            doc = db.get(Document, document_id)
            if doc:
                process.fail_document(db, doc, "LLM_ERROR", f"LLM call failed: {e}")
                db.commit()
        if not s.celery_eager:
            if self.request.retries >= self.max_retries:
                process.record_task_failure(_scoped, "finalize", [document_id], e)
            raise
        return
    index.delay(document_id, [str(i) for i in ids])


@celery.task(bind=True, acks_late=True, max_retries=2)
def index(self, document_id: str, invoice_ids: list[str]):
    from app.db.models import Invoice
    with SessionLocal() as db:
        index_mod.index_pages(db, document_id)
        for iid in invoice_ids:
            inv = db.get(Invoice, iid)
            if inv:
                index_mod.index_invoice(db, inv)
        db.commit()
