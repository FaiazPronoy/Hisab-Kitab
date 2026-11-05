from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, Invoice, ReconciliationItem, ReconciliationRun
from app.db.session import get_db
from app.pipeline.reconcile.engine import compare_copies, match_ledger

router = APIRouter(tags=["reconciliation"])


class RunIn(BaseModel):
    kind: str  # ledger | duplicate_copy
    ledger_document_id: str | None = None
    invoice_document_ids: list[str] | None = None  # empty: every non-sheet invoice
    left_invoice_id: str | None = None
    right_invoice_id: str | None = None


def _rec(i: Invoice) -> dict:
    ref = {"invoice_id": str(i.id), "document_id": str(i.document_id), "page": i.page_start,
           "sheet": i.sheet_name, "row": i.row_index, "invoice_number": i.invoice_number}
    return {"invoice_number": i.invoice_number, "invoice_number_norm": i.invoice_number_norm, "supplier_name": i.supplier_name,
            "supplier_norm": i.supplier_norm, "customer_name": i.customer_name, "invoice_date": i.invoice_date,
            "currency": i.currency, "subtotal": i.subtotal, "tax": i.tax, "total": i.total, "ref": ref}


@router.post("/reconciliations", status_code=201)
def run(body: RunIn, db: Session = Depends(get_db)):
    if body.kind == "ledger":
        ledger_doc = db.get(Document, body.ledger_document_id) if body.ledger_document_id else None
        if not ledger_doc or ledger_doc.kind != "sheet":
            raise HTTPException(422, "ledger_document_id must be an uploaded spreadsheet.")
        ledger = [_rec(i) for i in db.scalars(select(Invoice).where(Invoice.document_id == ledger_doc.id))]
        q = select(Invoice).join(Document).where(Document.kind != "sheet")
        if body.invoice_document_ids:
            q = q.where(Invoice.document_id.in_(body.invoice_document_ids))
        invoices = [_rec(i) for i in db.scalars(q)]
        items = match_ledger(invoices, ledger)
        left, right = None, ledger_doc.id
    elif body.kind == "duplicate_copy":
        a, b = db.get(Invoice, body.left_invoice_id), db.get(Invoice, body.right_invoice_id)
        if not a or not b:
            raise HTTPException(422, "Both invoice ids are required.")
        li = lambda inv: [{"description": x.description, "amount": x.amount} for x in inv.line_items]  # noqa: E731
        items = compare_copies(_rec(a), _rec(b), li(a), li(b))
        left, right = a.document_id, b.document_id
    else:
        raise HTTPException(422, "kind must be ledger or duplicate_copy")
    summary: dict[str, int] = {}
    for it in items:
        summary[it["category"]] = summary.get(it["category"], 0) + 1
    r = ReconciliationRun(kind=body.kind, left_document_id=left, right_document_id=right, summary=summary)
    db.add(r)
    db.flush()
    db.add_all(ReconciliationItem(run_id=r.id, **it) for it in items)
    db.commit()
    return get(str(r.id), db)


@router.get("/reconciliations")
def list_runs(db: Session = Depends(get_db)):
    rows = db.scalars(select(ReconciliationRun).order_by(ReconciliationRun.created_at.desc()).limit(50)).all()
    return [{"id": str(r.id), "kind": r.kind, "summary": r.summary, "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/reconciliations/{run_id}")
def get(run_id: str, db: Session = Depends(get_db)):
    r = db.get(ReconciliationRun, run_id)
    if not r:
        raise HTTPException(404, "Run not found.")
    return {"id": str(r.id), "kind": r.kind, "summary": r.summary, "created_at": r.created_at.isoformat(),
            "items": [{"category": i.category, "severity": i.severity, "field": i.field, "left_value": i.left_value,
                       "right_value": i.right_value, "delta": i.delta, "left_ref": i.left_ref, "right_ref": i.right_ref}
                      for i in r.items]}
