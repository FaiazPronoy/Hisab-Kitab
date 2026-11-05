"""Turns API results plus ground truth into metrics. Every number carries its n."""
import statistics
from decimal import Decimal

import numpy as np
from rapidfuzz import fuzz
from scipy.optimize import linear_sum_assignment

from app.pipeline.extract.normalize import norm_invoice_number

FIELDS = ["invoice_number", "invoice_date", "supplier_name", "customer_name", "currency", "subtotal", "tax", "total"]
KEY = ["invoice_number", "invoice_date", "supplier_name", "currency", "total"]
AMOUNT = {"subtotal", "tax", "total"}
EXPECT_RULE = {"wrong_total": "TOTAL_MATH", "missing_tax": "OPT_MISSING", "missing_number": "REQ_MISSING",
               "duplicate": "DUP_INVOICE", "near_duplicate": "DUP_SUSPECTED", "conflict": "DUP_CONFLICT"}


def truth_value(lab: dict, f: str):
    if f in (lab.get("hide") or []):
        return None
    if f == "total":
        return lab.get("printed_total") or lab.get("total")
    return lab.get(f)


def same(f: str, pred, true) -> bool:
    if pred is None or true is None:
        return False
    if f in AMOUNT:
        return abs(Decimal(str(pred)) - Decimal(str(true))) <= Decimal("0.01")
    if f == "invoice_number":
        return norm_invoice_number(pred) == norm_invoice_number(true)
    if f in ("supplier_name", "customer_name"):
        return fuzz.ratio(str(pred).lower(), str(true).lower()) >= 90
    return str(pred) == str(true)


def pct(a, b):
    return round(a / b, 4) if b else None


def prf(tp, fp, fn):
    p, r = pct(tp, tp + fp), pct(tp, tp + fn)
    f1 = round(2 * p * r / (p + r), 4) if p and r else 0.0
    return {"precision": p, "recall": r, "f1": f1, "n_true": tp + fn}


def items_score(pred: list[dict], true: list[dict]) -> tuple[int, int, int, int, int]:
    """Hungarian match on description + amount. Returns tp, fp, fn, cells_ok, cells."""
    if not pred or not true:
        return 0, len(pred), len(true), 0, 0
    cost = np.ones((len(pred), len(true)))
    for i, p in enumerate(pred):
        for j, t in enumerate(true):
            d = fuzz.token_sort_ratio(p.get("description") or "", t["description"]) / 100
            a = 1.0 if p.get("amount") and abs(Decimal(p["amount"]) - Decimal(t["amount"])) <= Decimal("0.01") else 0.0
            cost[i, j] = 1 - (0.6 * d + 0.4 * a)
    rows, cols = linear_sum_assignment(cost)
    tp, cells_ok, cells = 0, 0, 0
    for i, j in zip(rows, cols):
        if cost[i, j] > 0.45:
            continue
        tp += 1
        for k in ("quantity", "unit_price", "amount"):
            cells += 1
            pv, tv = pred[i].get(k), true[j][k]
            cells_ok += bool(pv) and abs(Decimal(pv) - Decimal(tv)) <= Decimal("0.01")
    return tp, len(pred) - tp, len(true) - tp, cells_ok, cells


def score_extraction(rows: list[tuple[dict, dict | None]]) -> dict:
    counts = {f: {"tp": 0, "fp": 0, "fn": 0, "halluc": 0, "abstain": 0, "null_true": 0} for f in FIELDS}
    all_key, it = 0, [0, 0, 0, 0, 0]
    for lab, inv in rows:
        flds = (inv or {}).get("fields", {})
        ok_all = True
        for f in FIELDS:
            tv = truth_value(lab, f)
            pv = (flds.get(f) or {}).get("value")
            c = counts[f]
            if tv is None:
                c["null_true"] += 1
                if pv is not None:
                    c["halluc"] += 1
                    c["fp"] += 1
                continue
            if pv is None:
                c["fn"] += 1
                c["abstain"] += 1
            elif same(f, pv, tv):
                c["tp"] += 1
            else:
                c["fp"] += 1
                c["fn"] += 1
            if f in KEY and not same(f, pv, tv):
                ok_all = False
        all_key += ok_all
        r = items_score((inv or {}).get("line_items", []), lab.get("line_items", []))
        it = [a + b for a, b in zip(it, r)]
    per = {f: {**prf(c["tp"], c["fp"], c["fn"]), "hallucinations": c["halluc"], "abstentions": c["abstain"],
               "n_null_truth": c["null_true"]} for f, c in counts.items()}
    macro = round(statistics.mean(v["f1"] for v in per.values()), 4)
    nonnull_pred = sum(c["tp"] + c["fp"] for c in counts.values())
    return {"n": len(rows), "per_field": per, "macro_f1": macro,
            "hallucination_rate": pct(sum(c["halluc"] for c in counts.values()), sum(c["null_true"] for c in counts.values())),
            "wrong_value_rate": pct(sum(c["fp"] for c in counts.values()), nonnull_pred),
            "all_key_fields_correct": pct(all_key, len(rows)),
            "line_items": {**prf(it[0], it[1], it[2]), "cell_accuracy": pct(it[3], it[4])}}


def score(results: list[dict], recon: dict, ledger: dict, metrics: dict) -> dict:
    pdf_rows, scan_rows, multi, zoo = [], {"clean": [], "medium": [], "heavy": []}, [], []
    validation = {k: {"n": 0, "caught": 0} for k in EXPECT_RULE}
    routing = {"wrong": 0, "wrong_to_review": 0, "auto_accepted_wrong": 0, "clean": 0, "clean_flagged": 0}
    by_id = {}
    for r in results:
        lab = r["label"]
        if r["kind"] == "zoo":
            got = "rejected" if r["upload"]["code"] in (413, 422) else (r["document"] or {}).get("status")
            zoo.append({"file": lab["file"], "expect": lab["expect"], "got": got,
                        "error_code": (r["document"] or {}).get("error_code") or _err(r), "ok": got == lab["expect"]})
            continue
        if r["kind"] in ("ledger", "dev"):
            continue
        if lab.get("multi"):
            multi.append({"true": len(lab["invoices"]), "pred": len(r["invoices"])})
            continue
        inv = r["invoices"][0] if r["invoices"] else None
        (pdf_rows if r["kind"] == "pdf" else scan_rows[lab["tier"]]).append((lab, inv))
        if r["kind"] == "pdf":
            by_id[lab["id"]] = (lab, inv)
    for lab, inv in by_id.values():
        codes = {x["rule_code"] for x in (inv or {}).get("findings_list", [])}
        if lab.get("planted"):
            v = validation[lab["planted"]]
            v["n"] += 1
            want = EXPECT_RULE[lab["planted"]]
            v["caught"] += want in codes and (inv or {}).get("status") == "needs_review"
        wrong = any(not same(f, ((inv or {}).get("fields", {}).get(f) or {}).get("value"), truth_value(lab, f))
                    for f in KEY if truth_value(lab, f) is not None)
        if wrong or lab.get("planted"):
            routing["wrong"] += 1
            if (inv or {}).get("status") == "needs_review":
                routing["wrong_to_review"] += 1
            elif inv:
                routing["auto_accepted_wrong"] += 1
        else:
            routing["clean"] += 1
            routing["clean_flagged"] += (inv or {}).get("status") == "needs_review"

    rec_items = recon.get("items", [])
    rec = {}
    def num(i):
        ref = i["left_ref"] if i["category"] == "missing_in_ledger" else (i["right_ref"] or i["left_ref"])
        return norm_invoice_number((ref or {}).get("invoice_number"))

    for cat, nums in ledger["planted"].items():
        found = {num(i) for i in rec_items if i["category"] == cat}
        hit = sum(norm_invoice_number(n) in found for n in nums)
        rec[cat] = {"n": len(nums), "found": hit, "recall": pct(hit, len(nums))}
    flagged_total = sum(1 for i in rec_items if i["category"] != "matched")
    rec["precision_overall"] = pct(sum(v["found"] for v in rec.values() if isinstance(v, dict)), flagged_total)

    times = [r["secs"] for r in results if r["kind"] in ("pdf", "scan", "dev") and r["document"]]
    docs = [r["document"] for r in results if r["kind"] in ("pdf", "scan", "dev") and r["document"]]
    statuses = [d["status"] for d in docs]
    extraction = score_extraction(pdf_rows)
    scans = {t: score_extraction(rows) for t, rows in scan_rows.items() if rows}
    seg_ok = sum(m["true"] == m["pred"] for m in multi)
    out = {
        "extraction_digital": extraction,
        "extraction_scans": scans,
        "validation": {k: {**v, "recall": pct(v["caught"], v["n"])} for k, v in validation.items()},
        "routing": {**routing, "routing_recall": pct(routing["wrong_to_review"], routing["wrong"]),
                    "false_review_rate": pct(routing["clean_flagged"], routing["clean"])},
        "segmentation": {"files": len(multi), "exact": seg_ok, "accuracy": pct(seg_ok, len(multi)),
                         "over": sum(m["pred"] > m["true"] for m in multi), "under": sum(m["pred"] < m["true"] for m in multi)},
        "reconciliation": rec,
        "failure_zoo": zoo,
        "reliability": {"documents": len(docs), "success_rate": pct(sum(s in ("done", "needs_review") for s in statuses), len(docs)),
                        "completed_with_errors": statuses.count("completed_with_errors"), "failed": statuses.count("failed")},
        "performance": {"doc_seconds_p50": _q(times, 0.5), "doc_seconds_p95": _q(times, 0.95),
                        "page_timing_ms": metrics.get("page_timing_ms")},
        "cost": metrics.get("llm"),
    }
    out["headline"] = {
        "digital_macro_f1": extraction["macro_f1"], "digital_all_key_fields_correct": extraction["all_key_fields_correct"],
        "hallucination_rate": extraction["hallucination_rate"], "routing_recall": out["routing"]["routing_recall"],
        "segmentation_accuracy": out["segmentation"]["accuracy"], "success_rate": out["reliability"]["success_rate"],
        "zoo_handled": f"{sum(z['ok'] for z in zoo)}/{len(zoo)}",
    }
    return out


def _err(r):
    b = r["upload"]["body"]
    if isinstance(b, dict):
        return (b.get("detail") or {}).get("error_code") if isinstance(b.get("detail"), dict) else None
    return b[0].get("error_code") if b else None


def _q(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 3)
