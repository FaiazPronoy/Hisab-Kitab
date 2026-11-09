# Design decisions

Short records of the choices that shape the system: the context, what was chosen, what else was considered and why.

## 1. Python for API and pipeline (FastAPI, not NestJS)

OCR, PDF parsing, pandas and the LLM SDKs are Python libraries. A Node API would still need a Python worker for all of them, so the system would carry two languages, two sets of models and a network hop between them. FastAPI with Pydantic v2 lets one set of models describe the API, the LLM response schema and the stored records.

## 2. Celery and Redis with an atomic page counter

OCR is CPU-bound, so prefork processes fit better than an async event loop. Celery gives `acks_late`, soft time limits, per-queue routing and retry with backoff out of the box. A large PDF fans out into page ranges; each finished page runs `UPDATE documents SET pages_done = pages_done + 1 ... RETURNING`, and the task that sees `done + failed == page_count` starts finalize. A Celery chord was rejected: chords keep state in the result backend, fail as a unit and are hard to resume after one bad page.

Scans over 60 pages go to a separate `ocr_heavy` queue so a one-page receipt never waits behind them.

## 3. One database: PostgreSQL 16 with pgvector, pg_trgm and tsvector

Relational integrity, the audit trail, full-text search, fuzzy matching on invoice numbers and vector search all live in one store, so hybrid search is a single SQL query with shared filters. A separate vector database would add a second source of truth to keep in sync for a few thousand 384-dimension vectors.

## 4. Page-level text-layer vs OCR decision

Every PDF page is classified on its own: at least 40 alphanumeric characters, at least 85% normal characters (broken CID fonts produce symbol floods and replacement characters) and no single image covering more than 85% of the page. A PDF that mixes typed and scanned pages is common; deciding per file would OCR good text or miss scanned pages.

## 5. RapidOCR first, Tesseract as fallback

RapidOCR runs PP-OCR models on ONNX Runtime: no torch or PaddlePaddle, a small image, CPU speed, and line boxes with confidences. Tesseract is the fallback when RapidOCR fails or reads with low confidence after preprocessing. Both sit behind one `OcrEngine` interface. The measured comparison on the degraded set is in EVALUATION.md.

Preprocessing runs only when a raw pass scores below 0.68 mean confidence, and each step (upscale, deskew, CLAHE, denoise) only runs when the image needs it. Blanket binarization was rejected because it destroys light print and coloured stamps.

## 6. Line-numbered layout text for the LLM

Words are grouped into lines by vertical position, wide gaps become ` | ` and each line gets an id such as `[P3:L14]`. The model has to cite the line id and a verbatim quote for every value. That makes three things possible: code can check the value, the UI can draw a box around the evidence, and the prompt stays small.

## 7. No invented values, enforced in code

The prompt asks the model to copy, never compute. That is not trusted. After every call, each value is kept only if its quote is found in the page text (exact or fuzzy at 0.9 or more to tolerate OCR noise) and the value itself can be read from the quote (its digits for amounts and dates, fuzzy text match for names). Otherwise the value becomes null with reason `unverified` and the rule `GROUNDING_FAILED` sends the invoice to review. Final confidence is the minimum of model confidence, OCR confidence of the evidence line and the quote match score.

## 8. Money in Decimal, maths in Python

Amounts are parsed into `Decimal` and stored as `NUMERIC(18,4)`. All arithmetic checks (line maths, subtotal, total, tax) run in Python with configurable tolerances in `config/validation.yaml`. The LLM never does arithmetic and never validates.

Number format is voted over every amount on the document (`1.234,56` versus `1,234.56`). Ambiguous dates such as `03/04/2026` are decided by other unambiguous dates on the same document, then by currency (USD month-first; GBP, EUR, BDT, INR and similar day-first). If still unsure, a best value is kept with an `ambiguous_date` warning.

## 9. Tolerances

| Check | Tolerance | Why |
| --- | --- | --- |
| Line maths | max(0.02, 0.05%) | unit prices are often rounded to 2 places on the document |
| Subtotal | max(0.02, 0.01 per line) | each line can carry one cent of rounding |
| Total | max(0.05, 0.01 per line and tax line) | tax rounded per line versus on the total |
| Tax lines | 0.02 | |
| Ledger amount | 0.02 | a payment should match its invoice to the cent |

The first version used 0.5% of the total. The evaluation showed why that is wrong: a planted error of 100.00 on a 42,159.91 invoice is 0.24%, inside the tolerance, and none of the four planted wrong totals in the test split was caught. Rounding adds cents per line, not a percentage of the amount, so the tolerances are now counted in cents per line.

A total that only reconciles when prices already include tax is an `info` finding, not an error.

## 10. Review routing

One function decides: any critical or error finding, more than one warning, any key field missing or unverified, any failed page, any duplicate or suspicious content sends the invoice to review. Everything else is `auto_validated`. A correction re-runs every rule immediately.

## 11. Spreadsheets: map columns once, parse rows in code

A register sheet (one invoice per row) is never sent to the LLM row by row. Column headers are mapped with a synonym list; only if that fails is the LLM shown the headers and five sample rows once. All rows are then parsed deterministically, so a 100,000-row ledger costs at most one call. Form-style sheets (one invoice laid out in cells) are serialized as `[S1:R4C2] value` lines and go through normal extraction.

## 12. Gemini 3.5 Flash-Lite, temperature 0, with a provider interface

The cheapest current model with JSON-schema structured output: $0.30 per million input tokens and $2.50 per million output tokens (Gemini pricing page, checked 2026-11-06). Gemini 3.5 Flash ($1.50 in, $9.00 out) is the vision fallback. Provider and model are environment variables. A `MockProvider` runs a label-based parser so the whole system and its tests work offline; it doubles as the rule-based baseline in the evaluation. The published Gemini numbers in EVALUATION.md come from Gemini 3.1 Flash-Lite, because the free tier allows 500 requests a day per model and the 3.5 quota was used up by earlier runs that day.

Every call is cached by hash of prompt version, model and input, so reruns and repeated evals cost nothing. A token bucket, a concurrency semaphore and a spending cap (`LLM_BUDGET_USD`) bound cost.

## 13. Invoice boundaries in multi-invoice PDFs

Each page boundary is scored from cheap signals: "Page k of N", a changed invoice number, a title in the top quarter, a total near the bottom of the previous page, repeated column headers. Only boundaries the signals leave undecided (score between 0.35 and 0.65) go to the LLM with the first 400 characters of both pages. Blank pages separate invoices.

## 14. Duplicates in four tiers

Same file hash (the upload returns the existing document), same supplier and number and total (`DUP_INVOICE`), same supplier and number with a different total (`DUP_CONFLICT`, possible tampering) and near-duplicates: similar supplier, same total, dates within 3 days, number different or an OCR variant such as `INV-1O8` for `INV-108` (`DUP_SUSPECTED`).

## 15. Reconciliation never guesses

Ledger rows match invoices by normalized invoice number first, then by fuzzy supplier plus amount plus date window. More than one candidate is reported as `ambiguous` instead of picking one. Line items in a copy comparison are paired with the Hungarian algorithm on description similarity and amount.

## 16. Hybrid search with reciprocal rank fusion

Keyword search uses `websearch_to_tsquery` with weighted fields plus trigram similarity for exact ids such as `INV-88392`; semantic search embeds a short invoice card with local `BAAI/bge-small-en-v1.5` (no API, CPU). Both lists are fused with RRF (k = 60). Keyword plus filters is the main tool; semantic search helps with descriptive queries.

## 17. UI components written by hand

The brief suggested shadcn/ui. The screens need a button, a card, a status chip and a confidence pill, so these are four small components in `web/components/ui.tsx` in the same style, without the generator and its Radix dependencies.

## 18. Security choices

API key on every route (constant-time compare), CORS locked to the web origin, upload rate limit, size, file-count, page, frame, row and pixel caps, magic-byte checks, UUID storage keys, macro workbook and zip-bomb rejection, encrypted PDFs rejected with a clear reason, CSV export that neutralizes formula injection, non-root containers and structured logs that carry ids and counts only, never document text or field values. Text inside documents is wrapped in `<untrusted_document>` tags; instruction-like text raises `SUSPICIOUS_CONTENT`. The residual risk: a fake total that is really printed passes grounding; arithmetic checks and reconciliation are what catch it.
