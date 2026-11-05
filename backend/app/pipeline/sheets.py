"""Spreadsheets in two shapes:
register mode, one row (or group of rows) per invoice, parsed in code after
the columns are mapped; and form mode, one invoice laid out on a sheet, sent
through normal extraction as cell text."""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from charset_normalizer import from_bytes

from app.pipeline.ingest import IngestError

# header text -> canonical field. Checked after lowercasing and stripping symbols.
SYNONYMS = {
    "invoice_number": ["invoice number", "invoice no", "invoice", "inv no", "inv number", "invoice id", "bill no", "reference", "ref"],
    "invoice_date": ["invoice date", "date", "inv date", "bill date", "issue date"],
    "due_date": ["due date", "due"],
    "supplier_name": ["supplier", "vendor", "supplier name", "vendor name", "seller", "payee"],
    "customer_name": ["customer", "client", "customer name", "buyer", "bill to"],
    "subtotal": ["subtotal", "sub total", "net", "net amount", "amount before tax"],
    "tax": ["tax", "vat", "gst", "tax amount", "vat amount"],
    "total": ["total", "amount", "gross", "total amount", "invoice total", "grand total", "amount due"],
    "currency": ["currency", "ccy", "cur"],
    "po_number": ["po", "po number", "purchase order"],
    "description": ["description", "item", "product"],
    "quantity": ["qty", "quantity"],
    "unit_price": ["unit price", "price", "rate"],
}
TOTAL_ROW = re.compile(r"^\s*(grand\s+)?totals?\b", re.I)


@dataclass
class Sheet:
    name: str
    index: int
    rows: list[list]  # cell values, None for empty
    formula_missing: list[tuple[int, int]] = field(default_factory=list)
    mode: str = "form"
    header_row: int | None = None
    columns: dict[str, int] = field(default_factory=dict)


def _clean(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def excel_serial(v) -> date | None:
    if isinstance(v, (int, float)) and 20000 < v < 80000:
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).date()
    return None


def read_csv(data: bytes, max_rows: int) -> list[Sheet]:
    best = from_bytes(data).best()
    text = str(best) if best else data.decode("utf-8", "replace")
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = []
    for i, r in enumerate(csv.reader(io.StringIO(text), dialect)):
        if i >= max_rows:
            raise IngestError("TOO_MANY_ROWS", f"The CSV has more than {max_rows} rows.")
        rows.append([_clean(c) for c in r])
    return [Sheet("csv", 1, rows)]


def read_xlsx(path: Path, max_rows: int) -> list[Sheet]:
    import openpyxl
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
        wf = openpyxl.load_workbook(path, data_only=False) if path.stat().st_size < 5_000_000 else None
    except Exception:
        raise IngestError("CORRUPT_FILE", "The workbook is damaged and cannot be opened.")
    sheets = []
    for idx, ws in enumerate(wb.worksheets, start=1):
        if ws.sheet_state != "visible":
            continue
        if ws.max_row > max_rows:
            raise IngestError("TOO_MANY_ROWS", f"Sheet '{ws.title}' has more than {max_rows} rows.")
        # forward-fill merged ranges so every cell of a merge carries the value
        merged = {}
        for rng in ws.merged_cells.ranges:
            v = ws.cell(rng.min_row, rng.min_col).value
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    merged[(r, c)] = v
        rows, missing = [], []
        for r, row in enumerate(ws.iter_rows(values_only=True), start=1):
            out = []
            for c, v in enumerate(row, start=1):
                v = merged.get((r, c), v)
                if v is None and wf is not None:
                    raw = wf[ws.title].cell(r, c).value
                    if isinstance(raw, str) and raw.startswith("="):
                        missing.append((r, c))
                out.append(_clean(v))
            rows.append(out)
        sheets.append(Sheet(ws.title, idx, rows, missing))
    return sheets


def read_xls(path: Path, max_rows: int) -> list[Sheet]:
    from python_calamine import CalamineWorkbook
    try:
        wb = CalamineWorkbook.from_path(str(path))
    except Exception:
        raise IngestError("CORRUPT_FILE", "The workbook is damaged and cannot be opened.")
    sheets = []
    for idx, name in enumerate(wb.sheet_names, start=1):
        data = wb.get_sheet_by_name(name).to_python(skip_empty_area=False)
        if len(data) > max_rows:
            raise IngestError("TOO_MANY_ROWS", f"Sheet '{name}' has more than {max_rows} rows.")
        sheets.append(Sheet(name, idx, [[_clean(c) if c != "" else None for c in r] for r in data]))
    return sheets


def read_sheets(path: Path, ext: str, max_rows: int) -> list[Sheet]:
    if ext == ".csv":
        sheets = read_csv(path.read_bytes(), max_rows)
    elif ext == ".xlsx":
        sheets = read_xlsx(path, max_rows)
    else:
        sheets = read_xls(path, max_rows)
    sheets = [s for s in sheets if any(any(c is not None for c in r) for r in s.rows)]
    if not sheets:
        raise IngestError("EMPTY_FILE", "The spreadsheet has no data.")
    for s in sheets:
        classify(s)
    return sheets


def _norm_header(v) -> str:
    return re.sub(r"[^a-z ]", "", str(v).lower().replace("_", " ").replace("#", " number")).strip()


def map_columns(header: list) -> dict[str, int]:
    cols = {}
    for i, h in enumerate(header):
        if h is None:
            continue
        key = _norm_header(h)
        for canon, names in SYNONYMS.items():
            if canon not in cols and key in names:
                cols[canon] = i
                break
    return cols


def classify(s: Sheet):
    """Header row = first row with 3+ text cells followed by rows whose types
    agree with it. Register mode needs an invoice number or total column."""
    for r, row in enumerate(s.rows[:30]):
        texts = [c for c in row if isinstance(c, str)]
        if len(texts) < 3:
            continue
        data_rows = [x for x in s.rows[r + 1:r + 6] if any(c is not None for c in x)]
        if len(data_rows) < 2:
            continue
        cols = map_columns(row)
        if "total" in cols and ("invoice_number" in cols or "supplier_name" in cols):
            s.mode, s.header_row, s.columns = "register", r, cols
            return
    s.mode = "form"


def register_records(s: Sheet) -> list[dict]:
    """Every data row becomes a record; values stay raw strings for the
    normalizers. Total rows and blank rows are skipped."""
    out = []
    for r in range(s.header_row + 1, len(s.rows)):
        row = s.rows[r]
        if not any(c is not None for c in row):
            continue
        first = next((c for c in row if c is not None), "")
        if isinstance(first, str) and TOTAL_ROW.match(first):
            continue
        rec = {"_row": r + 1}
        for canon, i in s.columns.items():
            v = row[i] if i < len(row) else None
            d = excel_serial(v) if canon.endswith("date") else None
            rec[canon] = d.isoformat() if d else (v.isoformat() if isinstance(v, (date, datetime)) else v)
        if rec.get("invoice_number") is None and rec.get("total") is None:
            continue
        out.append(rec)
    return out


def form_cells(s: Sheet) -> list[tuple[int, int, str]]:
    cells = []
    for r, row in enumerate(s.rows, start=1):
        for c, v in enumerate(row, start=1):
            if v is None:
                continue
            if isinstance(v, (date, datetime)):
                v = v.date().isoformat() if isinstance(v, datetime) else v.isoformat()
            cells.append((r, c, str(v)))
    return cells
