from app.db.models import Document, Invoice


def doc_out(d: Document, detail: bool = False) -> dict:
    out = {"id": str(d.id), "filename": d.filename, "kind": d.kind, "status": d.status, "size_bytes": d.size_bytes,
           "page_count": d.page_count, "pages_done": d.pages_done, "pages_failed": d.pages_failed,
           "error_code": d.error_code, "error_message": d.error_message, "created_at": d.created_at.isoformat()}
    if detail:
        out["pages"] = [{"page_no": p.page_no, "status": p.status, "source": p.source, "reason": p.reason,
                         "ocr_conf": p.ocr_conf, "duration_ms": p.duration_ms, "error": p.error} for p in sorted(d.pages, key=lambda p: p.page_no)]
        out["invoices"] = [inv_summary(i) for i in d.invoices]
    return out


def _s(v):
    return None if v is None else str(v)


def inv_summary(i: Invoice) -> dict:
    return {"id": str(i.id), "document_id": str(i.document_id), "status": i.status, "doc_type": i.doc_type,
            "invoice_number": i.invoice_number, "invoice_date": _s(i.invoice_date), "supplier_name": i.supplier_name,
            "customer_name": i.customer_name, "currency": i.currency, "total": _s(i.total),
            "page_start": i.page_start, "page_end": i.page_end, "sheet_name": i.sheet_name, "row_index": i.row_index,
            "overall_confidence": i.overall_confidence,
            "findings": {sev: sum(f.severity == sev for f in i.findings) for sev in ("critical", "error", "warning", "info")}}


def inv_detail(i: Invoice, corrections) -> dict:
    out = inv_summary(i)
    out.update({
        "version": i.version, "flags": i.flags or [], "boundary_confidence": i.boundary_confidence,
        "subtotal": _s(i.subtotal), "tax": _s(i.tax), "discount": _s(i.discount), "shipping": _s(i.shipping),
        "due_date": _s(i.due_date), "po_number": i.po_number, "tax_lines": i.tax_lines or [],
        "fields": {f.name: {"value_raw": f.value_raw, "value": f.value_norm, "confidence": f.confidence, "page": f.page_no,
                            "line_id": f.line_id, "bbox": f.bbox, "quote": f.evidence_quote, "source": f.source,
                            "null_reason": f.null_reason, "verified": f.verified} for f in i.fields},
        "line_items": [{"idx": li.idx, "description": li.description, "quantity": _s(li.quantity), "unit_price": _s(li.unit_price),
                        "amount": _s(li.amount), "confidence": li.confidence, "evidence": li.evidence} for li in i.line_items],
        "findings_list": [{"rule_code": f.rule_code, "severity": f.severity, "field": f.field, "message": f.message,
                           "expected": f.expected, "actual": f.actual,
                           "related_invoice_id": _s(f.related_invoice_id)} for f in i.findings],
        "corrections": [{"field": c.field, "old_value": c.old_value, "new_value": c.new_value, "reason": c.reason,
                         "corrected_by": c.corrected_by, "created_at": c.created_at.isoformat()} for c in corrections],
    })
    return out
