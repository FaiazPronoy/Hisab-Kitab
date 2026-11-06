from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import Invoice
from app.db.session import get_db
from app.pipeline.index import embed

router = APIRouter(tags=["search"])
RRF_K = 60
TOP = 50


def _filters(supplier, currency, status, date_from, date_to, min_total, max_total, has_findings):
    where, params = ["TRUE"], {}
    if supplier:
        where.append("i.supplier_norm % :supplier OR i.supplier_norm ILIKE :supplier_like")
        params.update(supplier=supplier.lower(), supplier_like=f"%{supplier.lower()}%")
    if currency:
        where.append("i.currency = :currency")
        params["currency"] = currency.upper()
    if status:
        where.append("i.status = :status")
        params["status"] = status
    if date_from:
        where.append("i.invoice_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        where.append("i.invoice_date <= :date_to")
        params["date_to"] = date_to
    if min_total is not None:
        where.append("i.total >= :min_total")
        params["min_total"] = min_total
    if max_total is not None:
        where.append("i.total <= :max_total")
        params["max_total"] = max_total
    if has_findings:
        where.append("EXISTS (SELECT 1 FROM validation_results v WHERE v.invoice_id = i.id AND v.severity IN ('error','critical'))")
    return " AND ".join(f"({w})" for w in where), params


@router.get("/search")
def search(q: str = "", mode: str = "hybrid", supplier: str | None = None, currency: str | None = None,
           status: str | None = None, date_from: date | None = None, date_to: date | None = None,
           min_total: Decimal | None = None, max_total: Decimal | None = None, has_findings: bool = False,
           limit: int = 20, db: Session = Depends(get_db)):
    if mode not in ("keyword", "semantic", "hybrid"):
        raise HTTPException(422, "mode must be keyword, semantic or hybrid")
    where, params = _filters(supplier, currency, status, date_from, date_to, min_total, max_total, has_findings)
    ranks: dict[str, dict[str, int]] = {}
    snippets: dict[str, str] = {}

    if q and mode in ("keyword", "hybrid"):
        rows = db.execute(text(f"""
            SELECT i.id::text AS id,
                   ts_rank_cd(i.search_tsv, websearch_to_tsquery('english', :q)) +
                   greatest(similarity(coalesce(i.invoice_number_norm,''), upper(regexp_replace(:q, '[^A-Za-z0-9]', '', 'g'))), 0) AS score,
                   ts_headline('english', coalesce(i.supplier_name,'') || ' ' || coalesce(i.invoice_number,'') || ' ' ||
                               coalesce(i.customer_name,''), websearch_to_tsquery('english', :q)) AS snip
            FROM invoices i
            WHERE ({where}) AND (i.search_tsv @@ websearch_to_tsquery('english', :q)
                   OR i.invoice_number_norm % upper(regexp_replace(:q, '[^A-Za-z0-9]', '', 'g')))
            ORDER BY score DESC LIMIT {TOP}"""), {**params, "q": q}).all()
        ranks["keyword"] = {r.id: n for n, r in enumerate(rows, start=1)}
        snippets.update({r.id: r.snip for r in rows})

    if q and mode in ("semantic", "hybrid"):
        vec = embed([q])
        if vec:
            rows = db.execute(text(f"""
                SELECT i.id::text AS id FROM invoices i
                WHERE ({where}) AND i.embedding IS NOT NULL
                ORDER BY i.embedding <=> CAST(:v AS vector) LIMIT {TOP}"""), {**params, "v": str(vec[0])}).all()
            ranks["semantic"] = {r.id: n for n, r in enumerate(rows, start=1)}

    if not q:
        rows = db.execute(text(f"SELECT i.id::text AS id FROM invoices i WHERE {where} ORDER BY i.created_at DESC LIMIT :lim"),
                          {**params, "lim": limit}).all()
        ranks["filter"] = {r.id: n for n, r in enumerate(rows, start=1)}

    # reciprocal rank fusion over whichever lists ran
    fused: dict[str, float] = {}
    for lst in ranks.values():
        for iid, rank in lst.items():
            fused[iid] = fused.get(iid, 0.0) + 1.0 / (RRF_K + rank)
    order = sorted(fused, key=fused.get, reverse=True)[:limit]
    out = []
    for iid in order:
        inv = db.get(Invoice, iid)
        out.append({"id": iid, "invoice_number": inv.invoice_number, "supplier_name": inv.supplier_name,
                    "customer_name": inv.customer_name, "invoice_date": str(inv.invoice_date) if inv.invoice_date else None,
                    "total": f"{inv.total:.2f}" if inv.total is not None else None, "currency": inv.currency, "status": inv.status,
                    "document_id": str(inv.document_id), "score": round(fused[iid], 5), "snippet": snippets.get(iid),
                    "matched_by": [k for k, lst in ranks.items() if iid in lst]})
    return {"mode": mode, "count": len(out), "results": out}
