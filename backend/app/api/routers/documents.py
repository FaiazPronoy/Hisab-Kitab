import asyncio
import hashlib
import io
import json
import tempfile
import uuid
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Actor, get_actor, require_browser_key, require_key
from app.api.serialize import doc_out
from app.core.config import get_settings
from app.core.ratelimit import limiter
from app.db.models import Document, Job, Page, ProcessingEvent
from app.db.session import get_db
from app.pipeline import images as image_mod
from app.pipeline import pdf as pdf_mod
from app.pipeline.ingest import IngestError, check_file, safe_filename
from app.pipeline.process import emit, revalidate
from app.storage.service import storage

router = APIRouter(tags=["documents"])


def enqueue(document_id: str):
    from app.workers.tasks import ingest
    ingest.delay(document_id)


def _handle_document_storage(db: Session, name: str, digest: str, info, size: int, tmp_path: Path, st,
                             role: str | None = None) -> dict:
    existing = db.scalar(select(Document).where(Document.sha256 == digest))
    if existing:
        tmp_path.unlink(missing_ok=True)
        if existing.status == "failed" and existing.error_code == "ENQUEUE_FAILED":
            existing.status = "queued"
            existing.error_code = None
            existing.error_message = None
            job = Job(document_id=existing.id, queue="ingest")
            db.add(job)
            db.commit()
            try:
                enqueue(str(existing.id))
                return {"filename": name, "document_id": str(existing.id), "job_id": str(job.id), "status": "queued",
                        "duplicate_of": None}
            except Exception as eq_err:
                existing.status, existing.error_code, existing.error_message = "failed", "ENQUEUE_FAILED", str(eq_err)
                db.commit()
                raise HTTPException(503, "Task queue unavailable, document marked failed.")
        return {"filename": name, "document_id": str(existing.id), "status": existing.status,
                "duplicate_of": str(existing.id), "job_id": None}

    key = st.new_key(info.ext)
    dest_path = st.path(key)
    try:
        tmp_path.replace(dest_path)
        doc = Document(sha256=digest, filename=name, mime=info.mime, size_bytes=size, storage_key=key, kind=info.kind,
                       role=role if info.kind == "sheet" else None)
        db.add(doc)
        db.flush()
        job = Job(document_id=doc.id, queue="ingest")
        db.add(job)
        db.commit()
        try:
            enqueue(str(doc.id))
        except Exception as eq_err:
            doc.status, doc.error_code, doc.error_message = "failed", "ENQUEUE_FAILED", str(eq_err)
            db.commit()
            raise HTTPException(503, "Task queue unavailable, document marked failed.")
        return {"filename": name, "document_id": str(doc.id), "job_id": str(job.id), "status": "queued",
                "duplicate_of": None}
    except IntegrityError:
        db.rollback()
        Path(dest_path).unlink(missing_ok=True)
        tmp_path.unlink(missing_ok=True)
        existing = db.scalar(select(Document).where(Document.sha256 == digest))
        if existing:
            if existing.status == "failed" and existing.error_code == "ENQUEUE_FAILED":
                existing.status = "queued"
                existing.error_code = None
                existing.error_message = None
                job = Job(document_id=existing.id, queue="ingest")
                db.add(job)
                db.commit()
                try:
                    enqueue(str(existing.id))
                    return {"filename": name, "document_id": str(existing.id), "job_id": str(job.id), "status": "queued",
                            "duplicate_of": None}
                except Exception as eq_err:
                    existing.status, existing.error_code, existing.error_message = "failed", "ENQUEUE_FAILED", str(eq_err)
                    db.commit()
                    raise HTTPException(503, "Task queue unavailable, document marked failed.")
            return {"filename": name, "document_id": str(existing.id), "status": existing.status,
                    "duplicate_of": str(existing.id), "job_id": None}
        raise
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        Path(dest_path).unlink(missing_ok=True)
        tmp_path.unlink(missing_ok=True)
        raise


@router.post("/documents", status_code=202)
# uploads are the expensive call, so they get a tighter limit than the default
@limiter.limit(lambda: get_settings().upload_rate_limit)
async def upload(request: Request, files: list[UploadFile] = File(...), role: str | None = Form(None),
                 db: Session = Depends(get_db), idempotency_key: str | None = Header(None),
                 api_key: str = Depends(require_key)):
    s = get_settings()
    if role in ("", "auto"):
        role = None
    if role not in (None, *ROLES):
        raise HTTPException(422, "role must be invoices, ledger, purchase_orders or auto.")
    rc = None
    idemp_redis_key = None
    if idempotency_key:
        idemp_redis_key = f"docintel:idemp:{api_key}:{idempotency_key}"
        try:
            rc = aioredis.from_url(s.redis_url)
            reserved = await rc.set(idemp_redis_key, "pending", ex=300, nx=True)
            if not reserved:
                val = await rc.get(idemp_redis_key)
                if val in (b"pending", "pending"):
                    await rc.aclose()
                    raise HTTPException(409, "A request with this idempotency key is already in progress.")
                if val:
                    await rc.aclose()
                    val_str = val.decode() if isinstance(val, bytes) else val
                    return json.loads(val_str)
        except HTTPException:
            raise
        except Exception:
            pass

    try:
        if len(files) > s.max_files_per_request:
            raise HTTPException(413, f"At most {s.max_files_per_request} files per request.")
        limit = s.max_upload_mb * 1024 * 1024
        out = []
        st = storage()
        for uf in files:
            name = safe_filename(uf.filename or "file")
            hasher = hashlib.sha256()
            with tempfile.NamedTemporaryFile(delete=False, dir=st.root) as tmp:
                size = 0
                while chunk := await uf.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        tmp.close()
                        Path(tmp.name).unlink(missing_ok=True)
                        raise HTTPException(413, f"{name} is larger than {s.max_upload_mb} MB.")
                    hasher.update(chunk)
                    tmp.write(chunk)
            tmp_path = Path(tmp.name)
            digest = hasher.hexdigest()
            try:
                info = await run_in_threadpool(check_file, name, tmp_path)
            except IngestError as e:
                tmp_path.unlink(missing_ok=True)
                out.append({"filename": name, "status": "rejected", "error_code": e.code, "error_message": e.message})
                continue
            res = await run_in_threadpool(_handle_document_storage, db, name, digest, info, size, tmp_path, st, role)
            out.append(res)

        if out and all(o["status"] == "rejected" for o in out) and len(out) == 1:
            raise HTTPException(422, {"error_code": out[0]["error_code"], "message": out[0]["error_message"]})

        if idemp_redis_key and rc:
            try:
                await rc.set(idemp_redis_key, json.dumps(out), ex=3600)
            except Exception:
                pass

        return out
    except Exception:
        if idemp_redis_key and rc:
            try:
                val = await rc.get(idemp_redis_key)
                if val in (b"pending", "pending"):
                    await rc.delete(idemp_redis_key)
            except Exception:
                pass
        raise
    finally:
        if rc:
            try:
                await rc.aclose()
            except Exception:
                pass


@router.get("/documents")
def list_documents(status: str | None = None, kind: str | None = None, cursor: str | None = None, limit: int = 50,
                   db: Session = Depends(get_db), _key: str = Depends(require_key)):
    q = select(Document).order_by(Document.created_at.desc(), Document.id.desc())
    if status:
        q = q.where(Document.status == status)
    if kind:
        q = q.where(Document.kind == kind)
    limit = min(max(limit, 1), 200)
    if cursor:
        try:
            ref = db.get(Document, uuid.UUID(cursor))
        except ValueError:
            raise HTTPException(422, "Invalid cursor.")
        if ref:
            q = q.where(
                or_(
                    Document.created_at < ref.created_at,
                    and_(Document.created_at == ref.created_at, Document.id < ref.id)
                )
            )
    rows = db.scalars(q.limit(limit + 1)).all()
    items = rows[:limit]
    return {"items": [doc_out(d) for d in items], "next_cursor": str(items[-1].id) if len(rows) > limit else None}


def _doc(db, document_id) -> Document:
    d = db.get(Document, document_id)
    if not d:
        raise HTTPException(404, "Document not found.")
    return d


@router.get("/documents/{document_id}")
def get_document(document_id: uuid.UUID, detail: bool = True, db: Session = Depends(get_db),
                 _key: str = Depends(require_key)):
    return doc_out(_doc(db, document_id), detail=detail)


ROLES = ("invoices", "ledger", "purchase_orders")


class RoleIn(BaseModel):
    role: str


@router.patch("/documents/{document_id}")
def set_role(document_id: uuid.UUID, body: RoleIn, db: Session = Depends(get_db), _key: str = Depends(require_key),
             actor: Actor = Depends(get_actor)):
    d = _doc(db, document_id)
    if d.kind != "sheet":
        raise HTTPException(422, "Only spreadsheets have a role.")
    if body.role not in ROLES:
        raise HTTPException(422, "role must be invoices, ledger or purchase_orders.")
    if any(i.status == "approved" or i.payment_batch_id for i in d.invoices) and body.role != "invoices":
        raise HTTPException(409, "Some rows are already approved; they have to stay invoices.")
    if d.role != body.role:
        d.role = body.role
        if body.role == "invoices":
            for i in d.invoices:
                i.status = "extracted"
        db.flush()
        for i in d.invoices:
            revalidate(db, i, pages_failed=d.pages_failed)
        if d.status in ("done", "needs_review"):
            d.status = "needs_review" if any(i.status == "needs_review" for i in d.invoices) else "done"
        emit(db, d, "role", "changed", message=f"{body.role} by {actor.name}")
        db.commit()
    return doc_out(d, detail=True)


@router.get("/documents/{document_id}/pages/{n}")
def get_page(document_id: uuid.UUID, n: int, db: Session = Depends(get_db),
             _key: str = Depends(require_key)):
    p = db.get(Page, (document_id, n))
    if not p:
        raise HTTPException(404, "Page not found.")
    return {"page_no": p.page_no, "source": p.source, "status": p.status, "reason": p.reason, "ocr_conf": p.ocr_conf,
            "text": p.text, "lines": (p.lines or {}).get("lines", []), "width": p.width, "height": p.height}


@router.get("/documents/{document_id}/pages/{n}/image")
def page_image(document_id: uuid.UUID, n: int, db: Session = Depends(get_db),
               _key: str = Depends(require_browser_key)):
    d = _doc(db, document_id)
    path = storage().path(d.storage_key)
    s = get_settings()
    try:
        if d.kind == "pdf":
            with pdf_mod.open_pdf(path) as pdf:
                if not 1 <= n <= pdf.page_count:
                    raise HTTPException(404, "Page not found.")
                img = pdf_mod.render(pdf[n - 1], 110, s.max_image_pixels)
        elif d.kind == "image":
            if not 1 <= n <= (d.page_count or 1):
                raise HTTPException(404, "Page not found.")
            img = image_mod.load_single_frame(path, n - 1, s.max_image_pixels)
            img.thumbnail((1400, 1400))
        else:
            raise HTTPException(404, "Spreadsheets have no page image.")
    except IngestError as e:
        raise HTTPException(422, e.message)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/documents/{document_id}/history")
def history(document_id: uuid.UUID, db: Session = Depends(get_db),
            _key: str = Depends(require_key)):
    rows = db.scalars(select(ProcessingEvent).where(ProcessingEvent.document_id == document_id).order_by(ProcessingEvent.id)).all()
    return [{"stage": e.stage, "status": e.status, "page_no": e.page_no, "duration_ms": e.duration_ms, "message": e.message,
             "at": e.created_at.isoformat()} for e in rows]


@router.get("/documents/{document_id}/events")
async def events(document_id: uuid.UUID, request: Request,
                 _key: str = Depends(require_browser_key)):
    """Server-sent events from Redis pub/sub. The client polls if this drops."""
    r = aioredis.from_url(get_settings().redis_url)
    ps = r.pubsub()
    await ps.subscribe(f"doc:{document_id}")

    async def stream():
        try:
            yield "retry: 2000\n\n"
            while not await request.is_disconnected():
                msg = await ps.get_message(ignore_subscribe_messages=True, timeout=15)
                if msg and msg["type"] == "message":
                    yield f"data: {msg['data'].decode()}\n\n"
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0)
        finally:
            await ps.unsubscribe()
            await r.aclose()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


class Reprocess(BaseModel):
    scope: str = "failed_only"  # failed_only | all
    force_vision: bool = False


@router.post("/documents/{document_id}/reprocess", status_code=202)
def reprocess(document_id: uuid.UUID, body: Reprocess, db: Session = Depends(get_db),
              _key: str = Depends(require_key)):
    if body.scope not in ("failed_only", "all"):
        raise HTTPException(422, "Invalid reprocess scope. Allowed values: failed_only, all.")
    d = _doc(db, document_id)
    if d.status in ("queued", "processing", "finalizing"):
        raise HTTPException(409, f"Document is currently {d.status}; cannot reprocess.")

    # Ingest-failed or 0-page document: re-ingest
    if not d.page_count:
        for inv in list(d.invoices):
            db.delete(inv)
        for p in d.pages:
            p.status, p.attempts = "pending", 0
        d.pages_done, d.pages_failed, d.status, d.error_code, d.error_message = 0, 0, "queued", None, None
        db.add(Job(document_id=d.id, type="reprocess", queue="ingest"))
        db.commit()
        enqueue(str(d.id))
        return {"document_id": str(d.id), "status": "queued", "scope": body.scope}

    if d.kind == "sheet" or body.scope == "all":
        for inv in list(d.invoices):
            db.delete(inv)
        for p in d.pages:
            p.status, p.attempts = "pending", 0
        d.pages_done, d.pages_failed, d.status, d.error_code, d.error_message = 0, 0, "queued", None, None
        db.add(Job(document_id=d.id, type="reprocess", queue="ingest"))
        db.commit()
        enqueue(str(d.id))
        return {"document_id": str(d.id), "status": "queued", "scope": body.scope}

    # scope == "failed_only"
    failed = [p.page_no for p in d.pages if p.status == "failed"]
    if failed:
        for inv in list(d.invoices):
            if inv.status != "approved":
                if inv.page_start is None or inv.page_end is None:
                    db.delete(inv)
                elif any(inv.page_start - 1 <= fp <= inv.page_end + 1 for fp in failed):
                    db.delete(inv)
        for p in d.pages:
            if p.status == "failed":
                p.status, p.attempts = "pending", 0
        d.pages_failed = 0
        d.pages_done = sum(1 for p in d.pages if p.status == "done")
        d.status = "processing"
        heavy = (d.page_count or 0) > 60
        db.add(Job(document_id=d.id, type="reprocess_failed", queue="ocr_heavy" if heavy else "ocr"))
        db.commit()
        from app.workers.tasks import pages, pages_heavy
        task = pages_heavy if heavy else pages
        for n in failed:
            task.delay(str(d.id), n, n)
        return {"document_id": str(d.id), "status": "processing", "pages": failed}

    # No pages failed: check if the document itself failed or needs review (e.g. LLM extraction failure)
    if d.status in ("failed", "needs_review"):
        for inv in list(d.invoices):
            if inv.status != "approved":
                db.delete(inv)
        d.pages_failed = 0
        d.pages_done = sum(1 for p in d.pages if p.status == "done")
        d.status = "processing"
        d.error_code, d.error_message = None, None
        db.add(Job(document_id=d.id, type="reprocess_finalize", queue="extract"))
        db.commit()
        from app.workers.tasks import finalize
        finalize.delay(str(d.id), force_vision=body.force_vision)
        return {"document_id": str(d.id), "status": "processing", "scope": "failed_only"}

    raise HTTPException(409, "Nothing failed on this document.")


@router.post("/maintenance/sweep")
def trigger_sweep(timeout_seconds: int = Query(900, ge=300, le=86400), db: Session = Depends(get_db),
                  _key: str = Depends(require_key)):
    from app.pipeline.process import sweep_stuck_documents
    swept = sweep_stuck_documents(db, timeout_seconds=timeout_seconds)
    return {"swept": swept, "count": len(swept)}

