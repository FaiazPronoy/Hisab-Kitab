# API

Base path `/api/v1`. Every route needs the `X-API-Key` header (the SSE and page image routes also accept `?api_key=` because browsers cannot set headers on `EventSource` and `<img>`). Interactive docs at `http://localhost:8000/docs`.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/documents` | multipart, field `files` (many). 202 with `[{document_id, job_id, status, duplicate_of}]`. A file that fails the type check comes back as `rejected` with `error_code`; a single rejected file returns 422. Over the size limit: 413. |
| GET | `/documents` | `status`, `kind`, `cursor`, `limit` |
| GET | `/documents/{id}` | progress, pages (source, reason, OCR confidence), invoices |
| GET | `/documents/{id}/pages/{n}` | page text and numbered lines with boxes |
| GET | `/documents/{id}/pages/{n}/image` | rendered page for the viewer |
| GET | `/documents/{id}/events` | server-sent events: `{stage, status, page_no, pages_done, page_count}` |
| GET | `/documents/{id}/history` | processing timeline |
| POST | `/documents/{id}/reprocess` | `{scope: failed_only or all}`; `failed_only` re-runs only failed pages |
| GET | `/invoices` | filters: `status, supplier, currency, date_from, date_to, min_total, max_total, document_id` |
| GET | `/invoices/{id}` | fields with evidence (quote, line id, box, confidence, source), line items, findings, correction history |
| PATCH | `/invoices/{id}` | `{corrections: [{field, value, reason}], version}`. Writes audit rows, re-validates and returns the new findings. 409 if `version` is stale. Line items use `line_items[2].amount`. |
| POST | `/invoices/{id}/approve` | returns the next invoice waiting for review |
| GET | `/review-queue` | needs-review invoices, most severe first |
| GET | `/search` | `q`, `mode=keyword, semantic or hybrid`, plus the invoice filters and `has_findings` |
| POST | `/reconciliations` | `{kind: ledger, ledger_document_id}` or `{kind: duplicate_copy, left_invoice_id, right_invoice_id}` |
| GET | `/reconciliations`, `/reconciliations/{id}` | runs and their items with references to both sources |
| GET | `/invoices/export?format=csv` | CSV with formula injection neutralized |
| GET | `/metrics/summary` | counts, success and failure rates, p50 and p95 per page source, LLM calls and cost |
| POST | `/maintenance/sweep` | `timeout_seconds` query param (300 to 86400, default 900). Recovers stuck finalizing documents, re-dispatches pending pages, or fails timed-out runs |
| GET | `/health` | database check |

## Example

```bash
curl -H "X-API-Key: local-dev-key" -F "files=@invoice.pdf" -F "files=@ledger.xlsx" http://localhost:8000/api/v1/documents
curl -H "X-API-Key: local-dev-key" "http://localhost:8000/api/v1/search?q=INV-2041&mode=hybrid"
curl -X PATCH -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"version": 3, "corrections": [{"field": "total", "value": "1250.00", "reason": "misread"}]}' \
  http://localhost:8000/api/v1/invoices/<id>
```
