# Database schema

PostgreSQL 16 with the `vector` and `pg_trgm` extensions. Money is `NUMERIC(18,4)`; ids are UUIDs.

```mermaid
erDiagram
  documents ||--o{ pages : has
  documents ||--o{ invoices : contains
  documents ||--o{ jobs : runs
  documents ||--o{ processing_events : logs
  invoices ||--o{ extracted_fields : has
  invoices ||--o{ line_items : has
  invoices ||--o{ validation_results : has
  invoices ||--o{ corrections : audited_by
  reconciliation_runs ||--o{ reconciliation_items : has
  payment_batches ||--o{ invoices : pays

  documents {
    uuid id PK
    text sha256 UK
    text filename
    text kind "pdf, image, sheet"
    text role "sheets: invoices or ledger"
    text status
    int page_count
    int pages_done
    int pages_failed
    text error_code
  }
  pages {
    uuid document_id PK
    int page_no PK
    text source "text_layer, ocr, sheet"
    text status
    int attempts
    text text
    text layout "numbered lines sent to the LLM"
    jsonb words "t, x0, y0, x1, y1, c, line_id"
    jsonb lines "line id to box"
    float ocr_conf
    text content_hash "OCR cache key"
    tsvector tsv
  }
  invoices {
    uuid id PK
    uuid document_id FK
    int page_start
    int page_end
    text sheet_name
    int row_index
    text status
    text invoice_number
    text invoice_number_norm
    date invoice_date
    text supplier_norm
    numeric subtotal
    numeric tax
    numeric total
    text currency
    text bank_account "IBAN or account read from the page"
    jsonb bank_evidence
    text approved_by
    timestamptz approved_at
    uuid payment_batch_id FK
    int version "optimistic locking"
    tsvector search_tsv
    vector embedding "384"
  }
  extracted_fields {
    uuid invoice_id FK
    text name
    text value_raw
    text value_norm
    float confidence
    int page_no
    text line_id
    jsonb bbox
    text evidence_quote
    text source "llm, vision, sheet, rule, user"
    text null_reason
    bool verified
  }
  line_items {
    uuid invoice_id FK
    int idx
    text description
    numeric quantity
    numeric unit_price
    numeric amount
    jsonb evidence
  }
  validation_results {
    uuid invoice_id FK
    text rule_code
    text severity
    text field
    text expected
    text actual
    uuid related_invoice_id
  }
  corrections {
    uuid invoice_id FK
    text field
    text old_value
    text new_value
    text reason
    text corrected_by
  }
  reconciliation_items {
    uuid run_id FK
    text category
    text field
    text left_value
    text right_value
    text delta
    jsonb left_ref
    jsonb right_ref
  }
  payment_batches {
    uuid id PK
    text format "pain001 or csv"
    int invoice_count
    jsonb totals "per currency"
    text filename
    text content
    text created_by
  }
  users {
    int id PK
    text username UK
    text name
    text role "clerk or approver"
    text password_hash "scrypt"
  }
  supplier_labels {
    int id PK
    text supplier_norm
    text field
    text label
    int hits
  }
  supplier_aliases {
    text alias_norm PK
    text supplier_norm
    text supplier_name
  }
```

Also `jobs`, `processing_events` (stage timeline per document and page), `failed_tasks` (dead letters) and `llm_calls` (prompt version, model, input hash, tokens, cost, latency, cached structured answer; no document text).

## Indexes

- `documents.sha256` unique (idempotent uploads)
- `invoices (supplier_norm, invoice_number_norm)` for duplicate lookups
- partial index on `invoices.created_at WHERE status = 'needs_review'` for the review queue
- GIN on `invoices.search_tsv` and `pages.tsv`
- trigram GIN on `supplier_norm` and `invoice_number_norm`
- HNSW (`vector_cosine_ops`) on `invoices.embedding`
