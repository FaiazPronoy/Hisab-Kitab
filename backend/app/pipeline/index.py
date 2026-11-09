import logging
from functools import lru_cache

from sqlalchemy import text

log = logging.getLogger(__name__)
MODEL = "BAAI/bge-small-en-v1.5"


@lru_cache
def _embedder():
    from fastembed import TextEmbedding
    return TextEmbedding(MODEL)


def embed(texts: list[str]) -> list[list[float]] | None:
    try:
        return [list(map(float, v)) for v in _embedder().embed(texts)]
    except Exception:
        log.warning("embedding failed", extra={"ctx": {"stage": "index"}})
        return None


def card(inv, items) -> str:
    """The short text that semantic search compares against."""
    parts = [f"Invoice {inv.invoice_number or ''}", f"from {inv.supplier_name or ''}", f"to {inv.customer_name or ''}",
             f"dated {inv.invoice_date or ''}", f"total {inv.total or ''} {inv.currency or ''}"]
    parts += [it.description for it in items if it.description][:20]
    return ". ".join(p for p in parts if p.strip())


def index_invoice(db, inv):
    db.execute(text("""
        UPDATE invoices SET search_tsv =
          setweight(to_tsvector('simple', coalesce(invoice_number,'')), 'A') ||
          setweight(to_tsvector('english', coalesce(supplier_name,'') || ' ' || coalesce(customer_name,'')), 'A') ||
          setweight(to_tsvector('english', coalesce(:items,'')), 'B') ||
          setweight(to_tsvector('english', coalesce(:pages,'')), 'C')
        WHERE id = :id"""), {"id": inv.id, "items": " ".join(i.description or "" for i in inv.line_items),
                             "pages": _page_text(db, inv)[:20000]})
    vec = embed([card(inv, inv.line_items)])
    if vec:
        # plain UPDATE so indexing does not bump the invoice version a reviewer is holding
        db.execute(text("UPDATE invoices SET embedding = CAST(:v AS vector) WHERE id = :id"),
                   {"v": str(vec[0]), "id": inv.id})


def _page_text(db, inv) -> str:
    if inv.page_start is None:
        return ""
    rows = db.execute(text("SELECT text FROM pages WHERE document_id=:d AND page_no BETWEEN :a AND :b"),
                      {"d": inv.document_id, "a": inv.page_start, "b": inv.page_end}).scalars().all()
    return " ".join(r or "" for r in rows)


def index_pages(db, document_id):
    db.execute(text("UPDATE pages SET tsv = to_tsvector('english', coalesce(text,'')) WHERE document_id=:d"),
               {"d": document_id})
