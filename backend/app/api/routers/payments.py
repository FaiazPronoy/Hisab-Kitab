import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Actor, get_actor
from app.api.serialize import inv_summary
from app.db.models import Correction, Document, Invoice, PaymentBatch
from app.db.session import get_db
from app.pipeline import payments as pay
from app.pipeline.extract.bank import iban_ok, mask

router = APIRouter(tags=["payments"])


@router.get("/payments/ready")
def ready(db: Session = Depends(get_db)):
    """Approved invoices that are not in a payment file yet, earliest due first."""
    rows = db.scalars(select(Invoice).join(Document).where(
        Invoice.status == "approved", Invoice.payment_batch_id.is_(None), Document.role.is_distinct_from("ledger"))
        .order_by(Invoice.due_date.asc().nullslast(), Invoice.created_at)).all()
    return [{**inv_summary(i), "due_date": i.due_date.isoformat() if i.due_date else None,
             "account": mask(i.bank_account), "iban": bool(i.bank_account and iban_ok(i.bank_account)),
             "approved_by": i.approved_by} for i in rows]


class BatchIn(BaseModel):
    invoice_ids: list[uuid.UUID]
    format: str = "pain001"
    execution_date: date | None = None


def _out(b: PaymentBatch) -> dict:
    return {"id": str(b.id), "format": b.format, "invoice_count": b.invoice_count, "totals": b.totals,
            "filename": b.filename, "created_by": b.created_by, "created_at": b.created_at.isoformat()}


@router.post("/payments/batches", status_code=201)
def create_batch(body: BatchIn, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)):
    if actor.role != "approver":
        raise HTTPException(403, "Only an approver can create a payment file.")
    if body.format not in ("pain001", "csv"):
        raise HTTPException(422, "format must be pain001 or csv.")
    ids = list(dict.fromkeys(body.invoice_ids))
    if not ids:
        raise HTTPException(422, "Choose at least one invoice.")
    # lock the rows so two people cannot put the same invoice in two files
    invs = db.scalars(select(Invoice).where(Invoice.id.in_(ids)).order_by(Invoice.id).with_for_update()).all()
    if len(invs) != len(ids):
        raise HTTPException(404, "Some invoices were not found.")
    bad = [i.invoice_number or str(i.id)[:8] for i in invs if i.status != "approved" or i.payment_batch_id]
    if bad:
        raise HTTPException(409, f"Not approved or already paid: {', '.join(bad)}.")
    issues = pay.problems(invs, body.format)
    if issues:
        raise HTTPException(422, "; ".join(issues))
    batch_id = uuid.uuid4()
    when = body.execution_date or date.today()
    content = pay.pain001(invs, batch_id, when) if body.format == "pain001" else pay.to_csv(invs)
    sums = defaultdict(Decimal)
    for i in invs:
        sums[i.currency] += abs(i.total).quantize(Decimal("0.01"))
    totals = {c: f"{v:.2f}" for c, v in sums.items()}
    ext = "xml" if body.format == "pain001" else "csv"
    b = PaymentBatch(id=batch_id, created_by=actor.name, format=body.format, invoice_count=len(invs),
                     totals=totals, filename=f"payments-{when.isoformat()}-{batch_id.hex[:6]}.{ext}", content=content)
    db.add(b)
    for i in invs:
        i.payment_batch_id = batch_id
        db.add(Correction(invoice_id=i.id, field="payment", new_value=b.filename, reason="payment file",
                          corrected_by=actor.name))
    db.commit()
    return _out(b)


@router.get("/payments/batches")
def batches(db: Session = Depends(get_db)):
    rows = db.scalars(select(PaymentBatch).order_by(PaymentBatch.created_at.desc()).limit(50)).all()
    return [_out(b) for b in rows]


@router.get("/payments/batches/{batch_id}/file")
def batch_file(batch_id: uuid.UUID, db: Session = Depends(get_db)):
    b = db.get(PaymentBatch, batch_id)
    if not b:
        raise HTTPException(404, "Payment file not found.")
    media = "application/xml" if b.format == "pain001" else "text/csv"
    return Response(b.content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{b.filename}"'})
