# API

Base path `/api/v1`. Every route needs the `X-API-Key` header (the browser query param `?api_key=` is a demo stand-in supported only on SSE `/documents/{id}/events` and page image `/documents/{id}/pages/{n}/image` routes because browsers cannot set custom headers on `EventSource` and `<img>`). Interactive docs at `http://localhost:8000/docs`.

Ids in paths and bodies are UUIDs; anything else gets a 422.

Corrections, approvals, role changes and payment files also need a signed-in reviewer (`Authorization: Bearer <token>` from `/auth/login`) unless `REQUIRE_LOGIN=false`. A clerk gets a 403 when approving an invoice at or above `APPROVAL_LIMIT`.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/documents` | multipart, field `files` (many) and optional `role` (`auto`, `invoices`, `ledger`) for spreadsheets. 202 with `[{document_id, job_id, status, duplicate_of}]`. A file that fails the type check comes back as `rejected` with `error_code`; a single rejected file returns 422. Over the size limit: 413. |
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
| POST | `/invoices/{id}/approve` | optional `{version}`, 409 if it is stale. Marks the document done once none of its invoices wait for review. Returns the next invoice waiting for review. |
| GET | `/review-queue` | needs-review invoices, most severe first |
| GET | `/search` | `q`, `mode=keyword, semantic or hybrid`, plus the invoice filters and `has_findings` |
| POST | `/reconciliations` | `{kind: ledger, ledger_document_id}` or `{kind: duplicate_copy, left_invoice_id, right_invoice_id}` |
| GET | `/reconciliations`, `/reconciliations/{id}` | runs and their items with references to both sources |
| GET | `/invoices/export?format=csv` | CSV with formula injection neutralized |
| GET | `/metrics/summary` | counts, success and failure rates, p50 and p95 per page source, LLM calls and cost |
| POST | `/maintenance/sweep` | `timeout_seconds` query param (300 to 86400, default 900). Recovers stuck finalizing documents, re-dispatches pending pages, or fails timed-out runs |
| PATCH | `/documents/{id}` | `{role: invoices or ledger}` for a spreadsheet; re-runs the checks on its rows |
| POST | `/auth/login` | `{username, password}`, returns a session token for the `Authorization: Bearer` header |
| GET | `/auth/me` | the signed-in reviewer and the approval limit |
| GET | `/compare?left=&right=` | two invoices side by side with their differences; nothing is stored |
| GET | `/payments/ready` | approved invoices not yet in a payment file, earliest due first |
| POST | `/payments/batches` | `{invoice_ids, format: pain001 or csv, execution_date}`, approver only. 409 if an invoice is not approved or already paid, 422 if bank details are missing |
| GET | `/payments/batches`, `/payments/batches/{id}/file` | payment files and their download |
| GET | `/health` | database check |

## Example

```bash
curl -H "X-API-Key: local-dev-key" -F "files=@invoice.pdf" -F "files=@ledger.xlsx" http://localhost:8000/api/v1/documents
curl -H "X-API-Key: local-dev-key" "http://localhost:8000/api/v1/search?q=INV-2041&mode=hybrid"
curl -X PATCH -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"version": 3, "corrections": [{"field": "total", "value": "1250.00", "reason": "misread"}]}' \
  http://localhost:8000/api/v1/invoices/<id>
```
