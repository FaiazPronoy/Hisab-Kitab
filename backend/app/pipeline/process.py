"""Pipeline stages as plain functions; app.workers.tasks wraps them in Celery.
Keeping them plain makes them easy to test and to run inline in the eval."""
import hashlib
import io
import json
import logging
import time
import traceback
from datetime import datetime, timedelta, timezone

import psutil
import redis
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.logging import log as jlog
from app.db.models import (
    Document, ExtractedField, FailedTask, Invoice, Job, LineItem, Page, ProcessingEvent, ValidationResult,
)
from app.pipeline import images as image_mod
from app.pipeline import pdf as pdf_mod
from app.pipeline import sheets as sheet_mod
from app.pipeline.extract import prompts
from app.pipeline.extract.normalize import (
    infer_day_first, number_style, parse_amount, parse_currency, parse_date,
)
from app.pipeline.extract.providers import BudgetExceeded, LlmError, call_structured
from app.pipeline.extract.run import extract_segment, typed
from app.pipeline.extract.schema import SCALARS, ColumnMapOut, SameInvoiceOut
from app.pipeline.ingest import IngestError

try:
    from celery.exceptions import SoftTimeLimitExceeded
except ImportError:
    class SoftTimeLimitExceeded(Exception):
        pass
from app.pipeline.layout import build_lines, cells_to_lines
from app.pipeline.ocr.run import ocr_image
from app.pipeline.segment import segment
from app.pipeline.validate import duplicates, routing, rules
from app.storage.service import storage

logger = logging.getLogger(__name__)
PAGE_ATTEMPTS = 3
_redis = None


def now():
    return datetime.now(timezone.utc)


def emit(db, doc: Document, stage: str, status: str, page_no=None, duration_ms=None, message=None):
    db.add(ProcessingEvent(document_id=doc.id, page_no=page_no, stage=stage, status=status,
                           duration_ms=duration_ms, message=message))
    payload = {"document_id": str(doc.id), "stage": stage, "status": status, "page_no": page_no,
               "pages_done": doc.pages_done, "pages_failed": doc.pages_failed, "page_count": doc.page_count,
               "doc_status": doc.status}
    global _redis
    try:
        _redis = _redis or redis.Redis.from_url(get_settings().redis_url)
        _redis.publish(f"doc:{doc.id}", json.dumps(payload))
    except Exception:
        pass  # progress is best effort; the database row is the record


def fail_document(db, doc: Document, code: str, message: str):
    doc.status, doc.error_code, doc.error_message = "failed", code, message
    for j in db.scalars(select(Job).where(Job.document_id == doc.id, Job.status.in_(["queued", "running"]))):
        j.status, j.error, j.finished_at = "failed", code, now()
    emit(db, doc, "ingest", "failed", message=code)
    jlog(logger, "document failed", document_id=doc.id, error_code=code)


# ---------- ingest ----------

def run_ingest(db, doc_id) -> list[tuple[int, int]]:
    """Opens the file, records the page count and returns page ranges to fan out.
    Spreadsheets are handled here completely."""
    s = get_settings()
    doc = db.get(Document, doc_id)
    path = storage().path(doc.storage_key)
    doc.status = "processing"
    for j in db.scalars(select(Job).where(Job.document_id == doc.id, Job.status == "queued")):
        j.status, j.started_at, j.attempts = "running", now(), j.attempts + 1
    try:
        if doc.kind == "pdf":
            with pdf_mod.open_pdf(path) as pdf:
                count = pdf.page_count
        elif doc.kind == "image":
            count = image_mod.get_image_frame_count(path, s.max_image_pixels)
        else:
            run_sheet(db, doc, path)
            return []
    except IngestError as e:
        fail_document(db, doc, e.code, e.message)
        return []
    if count > s.max_pages:
        fail_document(db, doc, "TOO_MANY_PAGES", f"The file has {count} pages; the limit is {s.max_pages}.")
        return []
    existing_pages = list(db.scalars(select(Page).where(Page.document_id == doc.id)))
    existing = {p.page_no for p in existing_pages}
    done_count = sum(1 for p in existing_pages if p.status == "done")
    failed_count = sum(1 for p in existing_pages if p.status == "failed")
    doc.page_count = count
    doc.pages_done = done_count
    doc.pages_failed = failed_count
    db.add_all(Page(document_id=doc.id, page_no=n) for n in range(1, count + 1) if n not in existing)
    emit(db, doc, "ingest", "done", message=f"{count} pages")
    if done_count + failed_count >= count and count > 0:
        return []
    b = s.page_batch_size
    return [(a, min(a + b - 1, count)) for a in range(1, count + 1, b)]


# ---------- pages ----------

def _page_from_words(page: Page, words: list[dict]):
    lines, layout = build_lines(words, page.page_no)
    page.words = words
    page.lines = {"lines": lines}
    page.layout = layout
    page.text = "\n".join(ln["text"].replace(" | ", "  ") for ln in lines)


def _cached_ocr(db, content_hash: str) -> Page | None:
    return db.scalars(select(Page).where(Page.content_hash == content_hash, Page.status == "done",
                                         Page.source == "ocr").limit(1)).first()


def process_page(db, doc: Document, page: Page, pdf=None, frames=None, image_path=None):
    s = get_settings()
    t0 = time.monotonic()
    img = None
    if doc.kind == "pdf":
        pg = pdf[page.page_no - 1]
        page.width, page.height = pg.rect.width, pg.rect.height
        source, reason, raw = pdf_mod.classify_page(pg)
        page.reason = reason
        if source == "text_layer":
            page.source, page.ocr_conf = "text_layer", 1.0
            _page_from_words(page, pdf_mod.text_words(pg, raw))
        else:
            img = pdf_mod.render(pg, s.render_dpi, s.max_image_pixels)
    else:
        if frames is not None:
            img = frames[page.page_no - 1]
        elif image_path is not None:
            img = image_mod.load_single_frame(image_path, page.page_no - 1, s.max_image_pixels)
        else:
            img = None
        if img is not None:
            page.width, page.height = img.size
            page.reason = "image"
    if img is not None:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page.content_hash = hashlib.sha256(buf.getvalue()).hexdigest()
        hit = _cached_ocr(db, page.content_hash)
        if hit:
            page.words, page.lines, page.layout, page.text, page.ocr_conf = hit.words, None, None, hit.text, hit.ocr_conf
            _page_from_words(page, [dict(w) for w in hit.words])
            page.reason = (page.reason or "") + "+cache"
        else:
            res = ocr_image(img)
            page.ocr_conf = round(res["conf"], 3)
            if res["steps"]:
                page.reason = f"{page.reason}+{','.join(res['steps'])}"
            _page_from_words(page, res["words"])
        page.source = "ocr"
        del img
    page.duration_ms = int((time.monotonic() - t0) * 1000)


def _count(db, doc_id, ok: bool) -> tuple[int, int, int]:
    col = "pages_done" if ok else "pages_failed"
    row = db.execute(text(f"UPDATE documents SET {col} = {col} + 1, updated_at = now() WHERE id = :id "
                          "RETURNING pages_done, pages_failed, page_count"), {"id": doc_id}).one()
    return row.pages_done, row.pages_failed, row.page_count


def run_pages(db_factory, doc_id, start: int, end: int) -> bool:
    """Processes pages start..end one at a time. Each page gets up to three
    tries, then is marked failed so the rest of the document carries on.
    Returns True when this call finished the last page of the document."""
    with db_factory() as db:
        doc = db.get(Document, doc_id)
        path = storage().path(doc.storage_key)
        kind = doc.kind
    pdf = pdf_mod.open_pdf(path) if kind == "pdf" else None
    finished = False
    try:
        for n in range(start, end + 1):
            with db_factory() as db:
                doc = db.get(Document, doc_id)
                page = db.get(Page, (doc_id, n))
                if page.status == "done":
                    continue
                ok, err = False, None
                for attempt in range(1, PAGE_ATTEMPTS + 1):
                    page.attempts = (page.attempts or 0) + 1
                    try:
                        process_page(db, doc, page, pdf=pdf, image_path=path if kind == "image" else None)
                        ok = True
                        break
                    except SoftTimeLimitExceeded:
                        raise
                    except Exception as e:
                        err = f"{type(e).__name__}: {e}"[:500]
                        time.sleep(0.5 * attempt)
                page.status = "done" if ok else "failed"
                page.error = None if ok else err
                db.commit()
                done, failed, count = _count(db, doc_id, ok)
                doc = db.get(Document, doc_id)
                db.refresh(doc)
                emit(db, doc, "ocr" if page.source == "ocr" else "text", "done" if ok else "failed",
                     page_no=n, duration_ms=page.duration_ms, message=page.reason if ok else err)
                if not ok:
                    db.add(FailedTask(task_name="page", args=[str(doc_id), n], error=err or "unknown"))
                db.commit()
                if done + failed == count:
                    finished = True
    finally:
        if pdf is not None:
            pdf.close()
        rss = psutil.Process().memory_info().rss // (1024 * 1024)
        with db_factory() as db:
            doc = db.get(Document, doc_id)
            if doc:
                emit(db, doc, "pages", "batch_done", message=f"pages {start}-{end} rss_mb={rss}")
                db.commit()
    return finished


def fail_page_range(db_factory, doc_id, start: int, end: int, reason: str) -> bool:
    finished = False
    with db_factory() as db:
        doc = db.get(Document, doc_id)
        if not doc:
            return False
        for n in range(start, end + 1):
            p = db.get(Page, (doc_id, n))
            if p and p.status not in ("done", "failed"):
                p.status = "failed"
                p.reason = reason
                doc.pages_failed += 1
            elif p and p.status == "failed":
                p.reason = reason
            elif not p:
                p = Page(document_id=doc_id, page_no=n, status="failed", reason=reason)
                db.add(p)
                doc.pages_failed += 1
        db.commit()
        db.refresh(doc)
        if doc.pages_done + doc.pages_failed >= doc.page_count:
            finished = True
    return finished


# ---------- sheets ----------

def run_sheet(db, doc: Document, path):
    s = get_settings()
    ext = "." + doc.filename.rsplit(".", 1)[-1].lower()
    sheets = sheet_mod.read_sheets(path, ext, s.max_sheet_rows)
    doc.page_count = len(sheets)
    form_pages = []
    for sh in sheets:
        if sh.mode != "register":
            _maybe_map_columns(db, sh)
        if sh.mode == "register":
            for rec in sheet_mod.register_records(sh):
                _invoice_from_record(db, doc, sh, rec)
        else:
            lines, layout = cells_to_lines(sheet_mod.form_cells(sh), sh.index)
            p = Page(document_id=doc.id, page_no=sh.index, source="sheet", status="done", reason=f"form:{sh.name}",
                     layout=layout, lines={"lines": lines}, text="\n".join(ln["text"] for ln in lines), ocr_conf=1.0)
            db.merge(p)
            form_pages.append(sh)
        doc.pages_done += 1
    db.flush()
    emit(db, doc, "sheet", "done", message=f"{len(sheets)} sheets")
    if form_pages:
        for sh in form_pages:
            page = db.get(Page, (doc.id, sh.index))
            _save_invoice(db, doc, [page], extract_segment(db, [page]), sheet_name=sh.name)
    finish_document(db, doc)


def _maybe_map_columns(db, sh):
    """Header row present but our synonym list missed it: ask the LLM once,
    with a few sample rows, to map the headers. All rows are still parsed in code."""
    for r, row in enumerate(sh.rows[:15]):
        headers = [c for c in row if isinstance(c, str)]
        if len(headers) < 3 or len(sh.rows) - r < 4:
            continue
        sample = "\n".join(" | ".join("" if c is None else str(c) for c in x) for x in sh.rows[r + 1:r + 6])
        out = call_structured(db, purpose="columns", version=prompts.COLUMNS_VERSION, schema=ColumnMapOut,
                              user=prompts.COLUMNS_USER.format(headers=headers, rows=sample))
        if not out:
            return
        cols = {k: row.index(v) for k, v in out.mapping.items() if v in row}
        if "total" in cols and ("invoice_number" in cols or "supplier_name" in cols):
            sh.mode, sh.header_row, sh.columns = "register", r, cols
        return


def _invoice_from_record(db, doc, sh, rec):
    style = number_style([str(v) for v in rec.values() if isinstance(v, str)])
    ccy, amb = parse_currency(str(rec.get("currency") or rec.get("total") or ""))
    fields, flags = {}, (["ambiguous_currency"] if amb else [])
    day_first = infer_day_first([str(rec.get("invoice_date") or "")], ccy)
    for f in SCALARS:
        raw = rec.get(f)
        if f in ("subtotal", "tax", "discount", "shipping", "total"):
            v = parse_amount(raw, style)
            norm = str(v) if v is not None else None
        elif f in ("invoice_date", "due_date"):
            d, a = parse_date(raw, day_first)
            norm = d.isoformat() if d else None
        elif f == "currency":
            norm = ccy
        else:
            norm = None if raw is None else str(raw).strip()
        fields[f] = {"value_raw": None if raw is None else str(raw), "value_norm": norm, "quote": None if raw is None else str(raw),
                     "line_id": f"S{sh.index}:R{rec['_row']}", "confidence": 1.0 if norm is not None else 0.0,
                     "null_reason": None if norm is not None else ("not_on_document" if f in sh.columns else "not_in_sheet"),
                     "verified": norm is not None,
                     "source": "sheet", "bbox": None, "page": None}
    result = {"doc_type": "invoice", "fields": fields, "line_items": [], "tax_lines": [], "flags": flags,
              "overall_confidence": 1.0}
    _save_invoice(db, doc, [], result, sheet_name=sh.name, row_index=rec["_row"])


# ---------- finalize ----------

def _ask_same(db):
    def ask(a, b):
        try:
            out = call_structured(db, purpose="boundary", version=prompts.BOUNDARY_VERSION, schema=SameInvoiceOut,
                                  user=prompts.BOUNDARY_USER.format(a=a, b=b))
            return (out.same_invoice, out.confidence) if out else (True, 0.5)
        except LlmError:
            return (True, 0.5)
    return ask


def _image_loader(doc):
    s = get_settings()

    def load(page):
        path = storage().path(doc.storage_key)
        try:
            if doc.kind == "pdf":
                with pdf_mod.open_pdf(path) as pdf:
                    img = pdf_mod.render(pdf[page.page_no - 1], 200, s.max_image_pixels)
            else:
                img = image_mod.load_single_frame(path, page.page_no - 1, s.max_image_pixels)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return None
    return load


def run_finalize(db, doc_id, lease_seconds: int = 300, force_vision: bool = False) -> list:
    doc = db.get(Document, doc_id)
    if not doc:
        return []
    # Atomic claim: transition to finalizing to prevent duplicate finalize executions
    # Also allow recovering stuck finalizing docs where lease has expired
    row = db.execute(
        text("UPDATE documents SET status = 'finalizing', updated_at = now() "
             "WHERE id = :id AND (status IN ('processing', 'queued') "
             "OR (status = 'finalizing' AND updated_at < now() - (:lease || ' seconds')::interval)) "
             "RETURNING id"),
        {"id": doc_id, "lease": lease_seconds}
    ).first()
    if not row:
        return [i.id for i in doc.invoices]
    db.commit()
    doc = db.get(Document, doc_id)
    try:
        pages = db.scalars(select(Page).where(Page.document_id == doc_id, Page.status == "done").order_by(Page.page_no)).all()
        by_no = {p.page_no: p for p in pages}
        texts = [by_no[n].text if n in by_no else "" for n in range(1, doc.page_count + 1)]
        segs = segment(texts, ask_same=_ask_same(db))
        loader = _image_loader(doc)
        vision_left = max(1, doc.page_count // 10)
        existing_segs = {(inv.page_start, inv.page_end) for inv in doc.invoices if inv.page_start is not None}
        for sg in segs:
            if (sg["page_start"], sg["page_end"]) in existing_segs:
                continue
            seg_pages = [by_no[n] for n in range(sg["page_start"], sg["page_end"] + 1) if n in by_no]
            if not seg_pages:
                continue
            result = extract_segment(db, seg_pages, image_loader=loader if vision_left > 0 else None,
                                     force_vision=force_vision)
            if "vision_used" in result["flags"]:
                vision_left -= 1
            _save_invoice(db, doc, seg_pages, result, page_start=sg["page_start"], page_end=sg["page_end"],
                          boundary_confidence=sg["confidence"])
            db.execute(text("UPDATE documents SET updated_at = now() WHERE id = :id"), {"id": doc_id})
            db.commit()
        emit(db, doc, "extract", "done", message=f"{len(segs)} invoices")
        finish_document(db, doc)
        db.commit()
        return [i.id for i in doc.invoices]
    except (BudgetExceeded, LlmError, SoftTimeLimitExceeded):
        raise
    except Exception as e:
        fail_document(db, doc, "FINALIZE_ERROR", f"Finalization failed: {type(e).__name__}")
        db.commit()
        raise


def _save_invoice(db, doc, pages, result, **loc):
    inv = Invoice(document_id=doc.id, doc_type=result["doc_type"], overall_confidence=result["overall_confidence"],
                  flags=result["flags"], tax_lines=[{**t, "amount": t["amount"]} for t in result["tax_lines"]], **loc)
    if result["fields"]:
        vals = {k: v for k, v in typed(result).items()}
        for k, v in vals.items():
            setattr(inv, k, v)
    db.add(inv)
    db.flush()
    for name, r in result["fields"].items():
        db.add(ExtractedField(invoice_id=inv.id, name=name, value_raw=r.get("value_raw"), value_norm=r.get("value_norm"),
                              confidence=r.get("confidence"), page_no=r.get("page"), line_id=r.get("line_id"),
                              bbox=r.get("bbox"), evidence_quote=r.get("quote"), source=r.get("source") or "llm",
                              null_reason=r.get("null_reason"), verified=bool(r.get("verified"))))
    for it in result["line_items"]:
        db.add(LineItem(invoice_id=inv.id, idx=it["idx"], description=it["description"], quantity=it["quantity"],
                        unit_price=it["unit_price"], amount=it["amount"], confidence=it["confidence"], evidence=it["evidence"]))
    db.flush()
    db.refresh(inv)
    revalidate(db, inv, pages_failed=doc.pages_failed)
    return inv


def field_meta(inv: Invoice) -> dict:
    out = {}
    for f in inv.fields:
        out[f.name] = {"confidence": f.confidence, "null_reason": f.null_reason, "verified": f.verified,
                       "source": f.source, "value_norm": f.value_norm, "rejected_value": None}
        if f.null_reason == "unverified":
            out[f.name]["rejected_value"] = "(removed)"
    return out


def revalidate(db, inv: Invoice, pages_failed: int = 0):
    """Runs every rule again from the stored values. Used after extraction
    and after each manual correction."""
    for v in list(inv.findings):
        db.delete(v)
    db.flush()
    values = {c: getattr(inv, c) for c in ("invoice_number", "invoice_date", "due_date", "supplier_name", "customer_name",
                                           "currency", "subtotal", "tax", "discount", "shipping", "total")}
    values["doc_type"] = inv.doc_type
    items = [{"quantity": i.quantity, "unit_price": i.unit_price, "amount": i.amount} for i in inv.line_items]
    meta = field_meta(inv)
    findings = rules.check(values, meta, items, inv.tax_lines or [], inv.flags or [])
    findings += duplicates.find(db, inv)
    for f in findings:
        db.add(ValidationResult(invoice_id=inv.id, rule_code=f["rule_code"], severity=f["severity"], field=f["field"],
                                message=f["message"], expected=f["expected"], actual=f["actual"],
                                related_invoice_id=f.get("related_invoice_id")))
    if inv.status != "approved":
        inv.status = routing.route(findings, meta, pages_failed, inv.flags or [])
    # a duplicate concerns both invoices, whichever arrived first
    for f in findings:
        other = db.get(Invoice, f["related_invoice_id"]) if f.get("related_invoice_id") else None
        if other is None or any(v.rule_code == f["rule_code"] and v.related_invoice_id == inv.id for v in other.findings):
            continue
        db.add(ValidationResult(invoice_id=other.id, rule_code=f["rule_code"], severity=f["severity"], field=f["field"],
                                message=f["message"], expected=inv.invoice_number, actual=other.invoice_number,
                                related_invoice_id=inv.id))
        if other.status != "approved":
            other.status = "needs_review"
    db.flush()
    return findings


def finish_document(db, doc: Document):
    db.flush()
    db.refresh(doc)
    statuses = [i.status for i in doc.invoices]
    if doc.pages_failed:
        doc.status = "completed_with_errors"
    elif not statuses:
        doc.status, doc.error_code = "needs_review", "NO_INVOICE_FOUND"
    elif any(st == "needs_review" for st in statuses):
        doc.status = "needs_review"
    else:
        doc.status = "done"
    for j in db.scalars(select(Job).where(Job.document_id == doc.id, Job.status.in_(["queued", "running"]))):
        j.status, j.finished_at = "succeeded", now()
    emit(db, doc, "finalize", doc.status)


def record_task_failure(db_factory, name: str, args: list, exc: Exception):
    with db_factory() as db:
        db.add(FailedTask(task_name=name, args=[str(a) for a in args], error=str(exc)[:1000],
                          traceback=traceback.format_exc()[-4000:]))
        db.commit()


def sweep_stuck_documents(db, timeout_seconds: int = 900) -> list[str]:
    cutoff = now() - timedelta(seconds=timeout_seconds)
    stuck = db.scalars(
        select(Document).where(Document.status.in_(["queued", "processing", "finalizing"]), Document.updated_at < cutoff)
    ).all()
    swept = []
    from app.workers.tasks import finalize, pages, pages_heavy
    for doc in stuck:
        last_event = db.scalars(
            select(ProcessingEvent.created_at).where(ProcessingEvent.document_id == doc.id).order_by(ProcessingEvent.id.desc()).limit(1)
        ).first()
        if last_event and last_event >= cutoff:
            continue
        if doc.page_count and (doc.pages_done + doc.pages_failed >= doc.page_count):
            doc.status = "processing"
            db.commit()
            finalize.delay(str(doc.id))
            swept.append(f"finalized:{doc.id}")
        elif doc.page_count and doc.page_count > 0:
            pending_pages = db.scalars(
                select(Page.page_no).where(Page.document_id == doc.id, Page.status == "pending").order_by(Page.page_no)
            ).all()
            if pending_pages:
                doc.status = "processing"
                doc.updated_at = now()
                db.commit()
                heavy = (doc.page_count or 0) > 60
                task = pages_heavy if heavy else pages
                for pno in pending_pages:
                    task.delay(str(doc.id), pno, pno)
                swept.append(f"redispatched:{doc.id}")
            else:
                fail_document(db, doc, "STUCK_TIMEOUT", f"Document processing exceeded timeout ({timeout_seconds}s)")
                swept.append(f"failed:{doc.id}")
        else:
            fail_document(db, doc, "STUCK_TIMEOUT", f"Document processing exceeded timeout ({timeout_seconds}s)")
            swept.append(f"failed:{doc.id}")
    if swept:
        db.commit()
    return swept

