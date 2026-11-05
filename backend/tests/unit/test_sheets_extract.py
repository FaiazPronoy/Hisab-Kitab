from pathlib import Path

import openpyxl
import pytest

from app.pipeline.extract.mock_parser import parse_invoice
from app.pipeline.sheets import read_sheets, register_records


def _csv(tmp_path: Path, text: str, enc: str, name="a.csv") -> Path:
    p = tmp_path / name
    p.write_bytes(text.encode(enc))
    return p


REGISTER = "Invoice No{d}Date{d}Supplier{d}Total{d}Currency\nINV-1{d}2026-01-02{d}Acme{d}100.50{d}USD\nINV-2{d}2026-01-03{d}Globex{d}20{d}USD\nTotal{d}{d}{d}120.50{d}\n"


@pytest.mark.parametrize("enc,delim", [("utf-8", ","), ("utf-8-sig", ","), ("cp1252", ";"), ("utf-8", "\t")])
def test_csv_register_in_many_encodings(tmp_path, enc, delim):
    p = _csv(tmp_path, REGISTER.format(d=delim), enc)
    [s] = read_sheets(p, ".csv", 1000)
    assert s.mode == "register"
    recs = register_records(s)
    assert [r["invoice_number"] for r in recs] == ["INV-1", "INV-2"]  # total row skipped


def test_xlsx_multi_sheet_merged_and_formulas(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ledger"
    ws.append(["Invoice #", "Vendor", "Invoice Date", "Amount"])
    ws.append(["A-1", "Acme", "2026-02-01", 10])
    ws.append(["A-2", "Acme", "2026-02-02", "=D2*2"])  # formula without a cached value
    form = wb.create_sheet("Invoice")
    form["A1"] = "INVOICE"
    form.merge_cells("A1:C1")
    form["A3"], form["B3"] = "Invoice No:", "F-77"
    form["A4"], form["B4"] = "Total", 55
    hidden = wb.create_sheet("Hidden")
    hidden["A1"] = "secret"
    hidden.sheet_state = "hidden"
    p = tmp_path / "w.xlsx"
    wb.save(p)
    sheets = read_sheets(p, ".xlsx", 1000)
    assert [s.name for s in sheets] == ["Ledger", "Invoice"]
    assert sheets[0].mode == "register" and sheets[0].formula_missing == [(3, 4)]
    assert sheets[1].mode == "form" and sheets[1].rows[0][:3] == ["INVOICE"] * 3


DOC = """[P1:L1] Acme Supplies Ltd
[P1:L2] INVOICE
[P1:L3] Invoice No: INV-2041 | Date: 12/03/2026
[P1:L4] Bill To:
[P1:L5] Globex Corp
[P1:L6] Description | Qty | Unit Price | Amount
[P1:L7] Bolts M6 | 10 | 2.50 | 25.00
[P1:L8] Washers | 100 | 0.10 | 10.00
[P1:L9] Subtotal | 35.00
[P1:L10] VAT 20% | 7.00
[P1:L11] Total | GBP 42.00"""


def test_mock_parser_reads_labels_and_items():
    out = parse_invoice(DOC)
    assert out.invoice_number.value == "INV-2041" and out.invoice_number.line_id == "P1:L3"
    assert out.supplier_name.value == "Acme Supplies Ltd"
    assert out.customer_name.value == "Globex Corp"
    assert out.subtotal.value == "35.00" and out.tax.value == "7.00" and out.total.value.endswith("42.00")
    assert out.currency.value == "GBP"
    assert [i.description for i in out.line_items] == ["Bolts M6", "Washers"]
