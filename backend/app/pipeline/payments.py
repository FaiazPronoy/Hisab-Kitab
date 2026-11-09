"""Payment files for approved invoices: ISO 20022 pain.001.001.09 credit
transfers for invoices with an IBAN, or a plain CSV for any bank upload."""
import csv
import io
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from xml.etree import ElementTree as ET

from app.core.config import get_settings
from app.pipeline.extract.bank import iban_ok

NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"


def _sub(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, tag, attrs)
    if text is not None:
        el.text = text
    return el


def _amount(inv) -> Decimal:
    return abs(inv.total).quantize(Decimal("0.01"))


def problems(invoices, fmt: str) -> list[str]:
    out = []
    for inv in invoices:
        name = inv.invoice_number or str(inv.id)[:8]
        if inv.total is None or inv.total <= 0:
            out.append(f"{name}: no positive total to pay")
        elif not inv.currency:
            out.append(f"{name}: no currency")
        elif not inv.bank_account:
            out.append(f"{name}: no bank account on the invoice")
        elif fmt == "pain001" and not iban_ok(inv.bank_account):
            out.append(f"{name}: account is not an IBAN, use the CSV format")
    return out


def _txt(v, n: int = 140) -> str:
    # OCR can leave control characters, which XML does not allow
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(v or ""))[:n]


def pain001(invoices, batch_id: uuid.UUID, execution: date) -> str:
    """One PmtInf block per currency, so each CtrlSum adds up amounts in one currency."""
    s = get_settings()
    by_ccy: dict[str, list] = {}
    for inv in invoices:
        by_ccy.setdefault(inv.currency, []).append(inv)
    ET.register_namespace("", NS)
    root = ET.Element(f"{{{NS}}}Document")
    cct = _sub(root, f"{{{NS}}}CstmrCdtTrfInitn")
    hdr = _sub(cct, f"{{{NS}}}GrpHdr")
    _sub(hdr, f"{{{NS}}}MsgId", batch_id.hex[:35])
    _sub(hdr, f"{{{NS}}}CreDtTm", datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    _sub(hdr, f"{{{NS}}}NbOfTxs", str(len(invoices)))
    _sub(hdr, f"{{{NS}}}CtrlSum", f"{sum((_amount(i) for i in invoices), Decimal('0')):.2f}")
    _sub(_sub(hdr, f"{{{NS}}}InitgPty"), f"{{{NS}}}Nm", _txt(s.payer_name))

    k = 0
    for n, (ccy, group) in enumerate(sorted(by_ccy.items()), start=1):
        pmt = _sub(cct, f"{{{NS}}}PmtInf")
        _sub(pmt, f"{{{NS}}}PmtInfId", f"{batch_id.hex[:30]}-{n}")
        _sub(pmt, f"{{{NS}}}PmtMtd", "TRF")
        _sub(pmt, f"{{{NS}}}NbOfTxs", str(len(group)))
        _sub(pmt, f"{{{NS}}}CtrlSum", f"{sum((_amount(i) for i in group), Decimal('0')):.2f}")
        _sub(_sub(pmt, f"{{{NS}}}ReqdExctnDt"), f"{{{NS}}}Dt", execution.isoformat())
        _sub(_sub(pmt, f"{{{NS}}}Dbtr"), f"{{{NS}}}Nm", _txt(s.payer_name))
        _sub(_sub(_sub(pmt, f"{{{NS}}}DbtrAcct"), f"{{{NS}}}Id"), f"{{{NS}}}IBAN", s.payer_iban)
        _sub(_sub(_sub(pmt, f"{{{NS}}}DbtrAgt"), f"{{{NS}}}FinInstnId"), f"{{{NS}}}BICFI", s.payer_bic)
        for inv in group:
            k += 1
            tx = _sub(pmt, f"{{{NS}}}CdtTrfTxInf")
            ids = _sub(tx, f"{{{NS}}}PmtId")
            _sub(ids, f"{{{NS}}}InstrId", f"{batch_id.hex[:28]}-{k}")
            _sub(ids, f"{{{NS}}}EndToEndId", _txt(inv.invoice_number or inv.id, 35))
            _sub(_sub(tx, f"{{{NS}}}Amt"), f"{{{NS}}}InstdAmt", f"{_amount(inv):.2f}", Ccy=ccy)
            _sub(_sub(tx, f"{{{NS}}}Cdtr"), f"{{{NS}}}Nm", _txt(inv.supplier_name or "Unknown"))
            _sub(_sub(_sub(tx, f"{{{NS}}}CdtrAcct"), f"{{{NS}}}Id"), f"{{{NS}}}IBAN", inv.bank_account)
            _sub(_sub(tx, f"{{{NS}}}RmtInf"), f"{{{NS}}}Ustrd", _txt(f"Invoice {inv.invoice_number or ''}".strip()))
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def to_csv(invoices) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["supplier", "invoice_number", "due_date", "amount", "currency", "account", "reference"])
    for inv in invoices:
        # a leading = + - @ would run as a formula in a spreadsheet
        safe = [("'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v) for v in (
            inv.supplier_name or "", inv.invoice_number or "", inv.due_date.isoformat() if inv.due_date else "",
            f"{_amount(inv):.2f}", inv.currency, inv.bank_account, f"Invoice {inv.invoice_number or ''}".strip())]
        w.writerow(safe)
    return buf.getvalue()
