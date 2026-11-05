# Architecture

## Components

```mermaid
flowchart LR
  UI[Next.js web app] -->|REST, SSE| API[FastAPI]
  API --> PG[(PostgreSQL 16<br/>pgvector, pg_trgm, tsvector)]
  API --> FS[(File storage<br/>UUID keys)]
  API -->|enqueue| R[(Redis)]
  R --> W[Celery workers]
  W --> PG
  W --> FS
  W --> LLM[LLM API<br/>Gemini or mock]
  W -.progress pub/sub.-> R
  R -.events.-> API
```

`api` and `worker` are the same image with different commands. Workers are stateless; `docker compose up --scale worker=4` adds capacity.

## Pipeline

```mermaid
flowchart TD
  U[Upload: size cap, magic bytes, SHA-256] -->|same hash| DUP[return existing document]
  U --> ING[ingest: open test, page count, encryption, bombs]
  ING -->|failure| FAIL[failed with error_code, no retry]
  ING -->|PDF or image| FAN[fan out page ranges of 20]
  ING -->|spreadsheet| SH[register mode: parse rows in code<br/>form mode: cells as lines]
  FAN --> P[per page: text layer or OCR<br/>3 tries, then page marked failed]
  P -->|last page done, atomic counter| FIN[finalize]
  FIN --> SEG[split into invoices]
  SEG --> EX[extract: hints, one LLM call, grounding, normalization]
  EX --> VAL[validate: rules, duplicates, routing]
  SH --> VAL
  VAL --> IDX[index: tsvector and embedding]
```

Queues: `ingest`, `ocr`, `ocr_heavy` (scans over 60 pages), `extract`, `index`.

## Per page decision

```mermaid
flowchart LR
  A[PDF page] --> B{text layer has 40+ real chars,<br/>85%+ normal characters,<br/>no image over 85% of page?}
  B -->|yes| T[text layer words with boxes]
  B -->|no| R[render at 220 DPI]
  R --> O1[RapidOCR raw]
  O1 -->|mean conf under 0.68| PRE[conditional preprocess:<br/>upscale, deskew, CLAHE, denoise]
  PRE --> O2[RapidOCR again]
  O2 -->|still low| O3[Tesseract]
```

## Status models

```mermaid
stateDiagram-v2
  [*] --> queued
  queued --> processing
  processing --> done
  processing --> needs_review
  processing --> completed_with_errors: a page failed after 3 tries
  processing --> failed: file problem
  completed_with_errors --> processing: reprocess failed pages
  failed --> queued: reprocess all
```

Invoice: `extracted` then `auto_validated` or `needs_review`, then `approved` by a reviewer. A correction to an approved invoice sends it back to `needs_review` until approved again.

Job: `queued`, `running`, `succeeded` or `failed`. Transient errors (LLM 429 and 5xx, timeouts, network) retry with exponential backoff and jitter up to 3 times; failures are kept in `failed_tasks`.
