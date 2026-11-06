import asyncio
import io
import tempfile
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serialize import doc_out
from app.core.config import get_settings
from app.core.ratelimit import limiter
from app.db.models import Document, Job, Page, ProcessingEvent
from app.db.session import get_db
from app.pipeline import images as image_mod
from app.pipeline import pdf as pdf_mod
from app.pipeline.ingest import IngestError, check_file, safe_filename, sha256_file
from app.storage.service import storage

router = APIRouter(tags=["documents"])


def enqueue(document_id: str):
    from app.workers.tasks import ingest
    ingest.delay(document_id)


@router.post("/documents", status_code=202)
# uploads are the expensive call, so they get a tighter limit than the default
@limiter.limit(lambda: get_settings().upload_rate_limit)
async def upload(request: Request, files: list[UploadFile] = File(...), db: Session = Depends(get_db),
                 idempotency_key: str | None = Header(None)):
    s = get_settings()
    if len(files) > s.max_files_per_request:
        raise HTTPException(413, f"At most {s.max_files_per_request} files per request.")
    limit = s.max_upload_mb * 1024 * 1024
    out = []
    st = storage()
    for uf in files:
        name = safe_filename(uf.filename or "file")
        with tempfile.NamedTemporaryFile(delete=False, dir=st.root) as tmp:
            size = 0
            while chunk := await uf.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    tmp.close()
                    Path(tmp.name).unlink(missing_ok=True)
                    raise HTTPException(413, f"{name} is larger than {s.max_upload_mb} MB.")
                tmp.write(chunk)
        tmp_path = Path(tmp.name)
        try:
            info = check_file(name, tmp_path)
        except IngestError as e:
            tmp_path.unlink(missing_ok=True)
            out.append({"filename": name, "status": "rejected", "error_code": e.code, "error_message": e.message})
            continue
        digest = sha256_file(tmp_path)
        existing = db.scalar(select(Document).where(Document.sha256 == digest))
        if existing:
            tmp_path.unlink(missing_ok=True)
            out.append({"filename": name, "document_id": str(existing.id), "status": existing.status,
                        "duplicate_of": str(existing.id), "job_id": None})
            continue
        key = st.new_key(info.ext)
        tmp_path.replace(st.path(key))
        doc = Document(sha256=digest, filename=name, mime=info.mime, size_bytes=size, storage_key=key, kind=info.kind)
        db.add(doc)
        db.flush()
        job = Job(document_id=doc.id, queue="ingest")
        db.add(job)
        db.commit()
        enqueue(str(doc.id))
        out.append({"filename": name, "document_id": str(doc.id), "job_id": str(job.id), "status": "queued",
                    "duplicate_of": None})
    if out and all(o["status"] == "rejected" for o in out) and len(out) == 1:
        raise HTTPException(422, {"error_code": out[0]["error_code"], "message": out[0]["error_message"]})
    return out


@router.get("/documents")
def list_documents(status: str | None = None, kind: str | None = None, cursor: str | None = None, limit: int = 50,
                   db: Session = Depends(get_db)):
    q = select(Document).order_by(Document.created_at.desc(), Document.id.desc())
    if status:
        q = q.where(Document.status == status)
    if kind:
        q = q.where(Document.kind == kind)
    if cursor:
        ref = db.get(Document, cursor)
        if ref:
            q = q.where(Document.created_at < ref.created_at)
    rows = db.scalars(q.limit(min(limit, 200) + 1)).all()
    items = rows[:limit]
    return {"items": [doc_out(d) for d in items], "next_cursor": str(items[-1].id) if len(rows) > limit else None}


def _doc(db, document_id) -> Document:
    d = db.get(Document, document_id)
    if not d:
        raise HTTPException(404, "Document not found.")
    return d


@router.get("/documents/{document_id}")
def get_document(document_id: str, detail: bool = True, db: Session = Depends(get_db)):
    return doc_out(_doc(db, document_id), detail=detail)


@router.get("/documents/{document_id}/pages/{n}")
def get_page(document_id: str, n: int, db: Session = Depends(get_db)):
    p = db.get(Page, (document_id, n))
    if not p:
        raise HTTPException(404, "Page not found.")
    return {"page_no": p.page_no, "source": p.source, "status": p.status, "reason": p.reason, "ocr_conf": p.ocr_conf,
            "text": p.text, "lines": (p.lines or {}).get("lines", []), "width": p.width, "height": p.height}


@router.get("/documents/{document_id}/pages/{n}/image")
def page_image(document_id: str, n: int, db: Session = Depends(get_db)):
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
            frames = image_mod.load_frames(path, s.max_image_pixels)
            if not 1 <= n <= len(frames):
                raise HTTPException(404, "Page not found.")
            img = frames[n - 1].convert("RGB")
            img.thumbnail((1400, 1400))
        else:
            raise HTTPException(404, "Spreadsheets have no page image.")
    except IngestError as e:
        raise HTTPException(422, e.message)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/documents/{document_id}/history")
def history(document_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(ProcessingEvent).where(ProcessingEvent.document_id == document_id).order_by(ProcessingEvent.id)).all()
    return [{"stage": e.stage, "status": e.status, "page_no": e.page_no, "duration_ms": e.duration_ms, "message": e.message,
             "at": e.created_at.isoformat()} for e in rows]


@router.get("/documents/{document_id}/events")
async def events(document_id: str, request: Request):
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
def reprocess(document_id: str, body: Reprocess, db: Session = Depends(get_db)):
    d = _doc(db, document_id)
    if d.kind == "sheet" or d.status == "failed" or body.scope == "all":
        if body.scope == "all":
            for p in d.pages:
                p.status = "pending"
        d.pages_done, d.pages_failed, d.status, d.error_code, d.error_message = 0, 0, "queued", None, None
        db.add(Job(document_id=d.id, type="reprocess", queue="ingest"))
        db.commit()
        enqueue(str(d.id))
        return {"document_id": str(d.id), "status": "queued", "scope": body.scope}
    failed = [p.page_no for p in d.pages if p.status == "failed"]
    if not failed:
        raise HTTPException(409, "Nothing failed on this document.")
    for p in d.pages:
        if p.status == "failed":
            p.status, p.attempts = "pending", 0
    d.pages_failed = 0
    d.pages_done = sum(p.status == "done" for p in d.pages)
    d.status = "processing"
    db.add(Job(document_id=d.id, type="reprocess_failed", queue="ocr"))
    db.commit()
    from app.workers.tasks import pages
    for n in failed:
        pages.delay(str(d.id), n, n)
    return {"document_id": str(d.id), "status": "processing", "pages": failed}

