from typing import Literal

from pydantic import BaseModel, Field

NullReason = Literal["not_on_document", "illegible", "ambiguous"]

SCALARS = ["invoice_number", "invoice_date", "due_date", "supplier_name", "customer_name", "po_number",
           "currency", "subtotal", "tax", "discount", "shipping", "total"]
AMOUNTS = {"subtotal", "tax", "discount", "shipping", "total"}
DATES = {"invoice_date", "due_date"}


class Field_(BaseModel):
    value: str | None = Field(None, description="Exactly as printed. Null if not printed.")
    quote: str | None = Field(None, description="Verbatim text from the document that contains the value.")
    line_id: str | None = Field(None, description="The [P#:L#] id of the line holding the quote.")
    confidence: float = Field(0.0, ge=0, le=1)
    null_reason: NullReason | None = None


class LineItemOut(BaseModel):
    description: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    amount: str | None = None
    quote: str | None = None
    line_id: str | None = None


class TaxLineOut(BaseModel):
    label: str | None = None
    rate: str | None = None
    amount: str | None = None
    quote: str | None = None
    line_id: str | None = None


class InvoiceOut(BaseModel):
    doc_type: Literal["invoice", "credit_note", "receipt", "other"] = "invoice"
    invoice_number: Field_ = Field_()
    invoice_date: Field_ = Field_()
    due_date: Field_ = Field_()
    supplier_name: Field_ = Field_()
    customer_name: Field_ = Field_()
    po_number: Field_ = Field_()
    currency: Field_ = Field_()
    subtotal: Field_ = Field_()
    tax: Field_ = Field_()
    discount: Field_ = Field_()
    shipping: Field_ = Field_()
    total: Field_ = Field_()
    tax_lines: list[TaxLineOut] = []
    line_items: list[LineItemOut] = []


class SameInvoiceOut(BaseModel):
    same_invoice: bool
    confidence: float = Field(0.5, ge=0, le=1)


class ColumnMapOut(BaseModel):
    mapping: dict[str, str | None] = Field(default_factory=dict, description="canonical field -> column header")
