"""Supplier memory and supplier history, measured.

Six suppliers each send five invoices. Every supplier prints its invoice
number after its own label ("Our ref", "Factuur nr", ...), which the rule
parser does not know. A simulated reviewer fixes a wrong number and approves
each invoice, the way a person working the queue would. The same stream runs
twice, with supplier memory off and on, so the difference is only memory.

Two suppliers change their IBAN on their fifth invoice; we count how many of
those the BANK_CHANGED check stops, and how many genuine invoices it flags."""
import random
from pathlib import Path

from faker import Faker
from sqlalchemy import text

from eval import generator

LABELS = ["Our ref", "Document No", "Factuur nr", "Bill reference", "Rechnungs-Nr", "Ref. no"]
PER_SUPPLIER = 5
CHANGED_BANK = {0, 3}  # suppliers whose last invoice carries a new IBAN


def build(out: Path, seed: int) -> list[list[dict]]:
    rng = random.Random(seed + 101)
    fake = Faker("en_GB")
    Faker.seed(seed + 101)
    out.mkdir(parents=True, exist_ok=True)
    stream = []
    for s, label in enumerate(LABELS):
        name, iban = fake.company(), generator.iban(rng)
        invs = []
        for k in range(PER_SUPPLIER):
            inv = generator.make(fake, rng, 900 + s * 10 + k, "classic")
            inv.update(supplier_name=name, number_label=label, iban=iban, planted=None)
            if s in CHANGED_BANK and k == PER_SUPPLIER - 1:
                inv["iban"] = generator.iban(rng)
                inv["bank_changed"] = True
            p = out / f"{inv['id']}.pdf"
            generator.render(inv, p)
            invs.append({**inv, "file": p.name})
        stream.append(invs)
    return stream


def _clear(engine):
    with engine.begin() as c:
        c.execute(text("TRUNCATE documents, reconciliation_runs, failed_tasks, supplier_labels, "
                       "supplier_aliases, payment_batches CASCADE"))


def _pass(client, h, stream, folder: Path) -> dict:
    by_position = [{"right_first_time": 0, "n": 0} for _ in range(PER_SUPPLIER)]
    reviews = corrections = 0
    bank = {"planted": 0, "caught": 0, "genuine_with_history": 0, "false_alarms": 0}
    for invs in stream:
        for k, lab in enumerate(invs):
            with open(folder / lab["file"], "rb") as f:
                r = client.post("/api/v1/documents", files=[("files", (lab["file"], f))], headers=h)
            doc_id = r.json()[0]["document_id"]
            d = client.get(f"/api/v1/documents/{doc_id}", headers=h).json()
            inv = client.get(f"/api/v1/invoices/{d['invoices'][0]['id']}", headers=h).json()
            codes = {x["rule_code"] for x in inv["findings_list"]}
            right = inv["invoice_number"] == lab["invoice_number"]
            by_position[k]["n"] += 1
            by_position[k]["right_first_time"] += right
            if lab.get("bank_changed"):
                bank["planted"] += 1
                bank["caught"] += "BANK_CHANGED" in codes
                continue  # a payment hold: the reviewer does not approve it
            if k > 0:
                bank["genuine_with_history"] += 1
                bank["false_alarms"] += "BANK_CHANGED" in codes
            if inv["status"] == "needs_review":
                reviews += 1
            if not right:
                corrections += 1
                inv = client.patch(f"/api/v1/invoices/{inv['id']}", headers=h, json={
                    "version": inv["version"], "corrections": [
                        {"field": "invoice_number", "value": lab["invoice_number"], "reason": "eval reviewer"}]}).json()
            client.post(f"/api/v1/invoices/{d['invoices'][0]['id']}/approve", headers=h, json={})
    return {"by_position": by_position, "reviews": reviews, "corrections": corrections, "bank": bank}


def run(client, h, gen_dir: Path, seed: int) -> dict:
    from app.core.config import get_settings
    from app.db.session import engine

    folder = gen_dir / "learning"
    stream = build(folder, seed)
    s = get_settings()
    out = {"suppliers": len(stream), "invoices_each": PER_SUPPLIER, "labels": LABELS}
    for mode in ("off", "on"):
        _clear(engine)
        s.supplier_memory = mode == "on"
        out[mode] = _pass(client, h, stream, folder)
    s.supplier_memory = True
    _clear(engine)
    return out
