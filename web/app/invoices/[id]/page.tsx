"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { useRouter } from "next/navigation";
import { use, useEffect, useMemo, useState } from "react";
import { api, imageUrl, type Field, type Finding } from "@/lib/api";
import { Button, Card, Chip, Confidence, Empty, Spinner } from "@/components/ui";

const ORDER = ["invoice_number", "invoice_date", "due_date", "supplier_name", "customer_name", "po_number",
  "currency", "subtotal", "discount", "shipping", "tax", "total"];
const SEV_ORDER = ["critical", "error", "warning", "info"];

export default function Review({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["inv", id], queryFn: () => api<any>(`/invoices/${id}`) });
  const inv = q.data;
  const [page, setPage] = useState<number | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => { if (inv && page == null) setPage(inv.page_start || 1); }, [inv, page]);
  useEffect(() => { setEdits({}); setFindings(null); setFocus(null); setPage(null); }, [id]);

  const fields: Record<string, Field> = inv?.fields || {};
  const boxes = useMemo(() => {
    const out: { key: string; bbox: number[] }[] = [];
    for (const [k, f] of Object.entries(fields)) if (f.bbox && f.page === page) out.push({ key: k, bbox: f.bbox });
    (inv?.line_items || []).forEach((li: any, i: number) => {
      if (li.evidence?.bbox && li.evidence.page === page) {
        out.push({ key: `line_items[${i}]`, bbox: li.evidence.bbox });
      }
    });
    return out;
  }, [fields, inv, page]);

  const save = async () => {
    const corrections = Object.entries(edits).map(([field, value]) => ({ field, value: value === "" ? null : value, reason: "review" }));
    if (!corrections.length) return;
    setSaving(true);
    setMsg(null);
    try {
      const r = await api<any>(`/invoices/${id}`, { method: "PATCH", body: JSON.stringify({ corrections, version: inv.version }) });
      setFindings(r.findings);
      setEdits({});
      await qc.invalidateQueries({ queryKey: ["inv", id] });
      setMsg(r.status === "auto_validated" ? "Saved. All checks pass." : "Saved. Some checks still need attention.");
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setSaving(false);
    }
  };

  const approve = async () => {
    const r = await api<any>(`/invoices/${id}/approve`, { method: "POST" });
    if (r.next_invoice_id) router.push(`/invoices/${r.next_invoice_id}`);
    else { await qc.invalidateQueries({ queryKey: ["inv", id] }); setMsg("Approved. The review queue is empty."); }
  };

  const next = async () => {
    const queue = await api<any[]>("/review-queue?limit=50");
    const nxt = queue.find((x) => x.id !== id);
    if (nxt) router.push(`/invoices/${nxt.id}`);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); }
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); approve(); }
      if (e.altKey && e.key === "ArrowRight") { e.preventDefault(); next(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (q.isLoading) return <Spinner />;
  if (!inv) return <Empty>Invoice not found.</Empty>;
  const shown: Finding[] = (findings ?? inv.findings_list).slice().sort((a: Finding, b: Finding) => SEV_ORDER.indexOf(a.severity) - SEV_ORDER.indexOf(b.severity));
  const pages = inv.page_start ? Array.from({ length: inv.page_end - inv.page_start + 1 }, (_, i) => inv.page_start + i) : [];
  const pick = (key: string, f?: Field) => { setFocus(key); if (f?.page) setPage(f.page); };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <section>
        <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
          {pages.length > 0 ? pages.map((n) => (
            <button key={n} onClick={() => setPage(n)} className={clsx("rounded px-2 py-1", n === page ? "bg-brand text-white" : "bg-white border border-line")}>p{n}</button>
          )) : <span className="text-muted">From sheet {inv.sheet_name}{inv.row_index ? `, row ${inv.row_index}` : ""}</span>}
        </div>
        {page && pages.length > 0 ? (
          <Card className="relative overflow-hidden">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={imageUrl(inv.document_id, page)} alt={`Page ${page}`} className="block w-full" />
            <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="pointer-events-none absolute inset-0 h-full w-full">
              {boxes.map((b) => (
                <rect key={b.key} x={b.bbox[0] - 0.004} y={b.bbox[1] - 0.003} width={b.bbox[2] - b.bbox[0] + 0.008} height={b.bbox[3] - b.bbox[1] + 0.006}
                  className="pointer-events-auto cursor-pointer" onMouseEnter={() => setFocus(b.key)}
                  fill={focus === b.key ? "rgba(217,119,6,0.28)" : "rgba(26,54,93,0.08)"} stroke={focus === b.key ? "#d97706" : "rgba(26,54,93,0.35)"} strokeWidth={0.002} />
              ))}
            </svg>
          </Card>
        ) : <Empty>No page image for spreadsheet rows.</Empty>}
      </section>

      <section>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <h1 className="mr-auto text-xl font-semibold">{inv.invoice_number || "Invoice"} <span className="font-normal text-muted">{inv.supplier_name}</span></h1>
          <Chip value={inv.status} />
          <Button variant="ghost" onClick={() => setShowHistory((v) => !v)}>History ({inv.corrections.length})</Button>
          <Button variant="ghost" onClick={next} title="Alt + Right arrow">Next</Button>
        </div>
        {inv.flags?.includes("vision_used") && <p className="mb-3 rounded-md bg-amber-50 p-2 text-sm text-amber-900">Some values were read from the page image. They have no box to highlight.</p>}
        {shown.length > 0 ? (
          <ul className="mb-4 space-y-1.5">
            {shown.map((f, k) => (
              <li key={k} className={clsx("rounded-md border px-3 py-2 text-sm", f.severity === "critical" || f.severity === "error" ? "border-red-200 bg-red-50" : f.severity === "warning" ? "border-amber-200 bg-amber-50" : "border-line bg-white")}>
                <button className="text-left" onClick={() => f.field && pick(f.field, fields[f.field])}>
                  <b className="mr-2">{f.rule_code}</b>{f.message}
                  {f.expected && f.actual && <span className="text-muted"> Expected {f.expected}, found {f.actual}.</span>}
                  {!f.expected && f.actual && <span className="text-muted"> Value: {f.actual}.</span>}
                </button>
              </li>
            ))}
          </ul>
        ) : <p className="mb-4 rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-900">All checks pass.</p>}

        <Card className="divide-y divide-line">
          {ORDER.map((k) => {
            const f = fields[k];
            if (!f) return null;
            const val = edits[k] ?? f.value ?? "";
            return (
              <div key={k} className={clsx("grid grid-cols-[9rem_1fr] gap-x-3 px-4 py-2.5", focus === k && "bg-amber-50")} onClick={() => pick(k, f)}>
                <label htmlFor={`f-${k}`} className="pt-1.5 text-sm text-muted">{k.replaceAll("_", " ")}</label>
                <div>
                  <div className="flex items-center gap-2">
                    <input id={`f-${k}`} value={val} onFocus={() => pick(k, f)} onChange={(e) => setEdits({ ...edits, [k]: e.target.value })}
                      placeholder={f.null_reason ? "Not on document" : ""}
                      className={clsx("w-full rounded-md border px-2 py-1.5 text-sm", edits[k] !== undefined ? "border-accent" : "border-line")} />
                    <Confidence c={f.confidence} reason={f.value ? null : f.null_reason} source={f.source} />
                  </div>
                  {f.quote && <p className="mt-1 truncate text-xs text-muted" title={f.quote}>&ldquo;{f.quote}&rdquo; {f.line_id && <span>({f.line_id})</span>}{!f.bbox && f.source === "vision" && " no box available"}</p>}
                </div>
              </div>
            );
          })}
        </Card>

        <h2 className="mb-2 mt-6 text-sm font-semibold uppercase tracking-wide text-muted">Line items</h2>
        {inv.line_items.length === 0 ? <Empty>No line items.</Empty> : (
          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-paper text-left text-muted"><tr><th className="px-3 py-2 font-medium">Description</th><th className="px-3 py-2 font-medium">Qty</th>
                <th className="px-3 py-2 font-medium">Unit</th><th className="px-3 py-2 font-medium">Amount</th></tr></thead>
              <tbody className="divide-y divide-line">
                {inv.line_items.map((li: any, i: number) => (
                  <tr key={i} className={clsx(focus === `line_items[${i}]` && "bg-amber-50", !li.evidence?.verified && "text-amber-800")}>
                    {(["description", "quantity", "unit_price", "amount"] as const).map((c) => {
                      const key = `line_items[${li.idx}].${c}`;
                      return (
                        <td key={c} className="px-2 py-1">
                          <input aria-label={`${c} line ${i + 1}`} value={edits[key] ?? li[c] ?? ""} onFocus={() => setFocus(`line_items[${i}]`)}
                            onChange={(e) => setEdits({ ...edits, [key]: e.target.value })}
                            className={clsx("w-full rounded border px-1.5 py-1", c !== "description" && "text-right tabular-nums", edits[key] !== undefined ? "border-accent" : "border-transparent hover:border-line")} />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}

        <div className="sticky bottom-0 mt-6 flex flex-wrap items-center gap-2 border-t border-line bg-[#f8fafc] py-3">
          <Button onClick={save} disabled={saving || !Object.keys(edits).length} title="Ctrl + S">{saving && <Spinner />} Save corrections</Button>
          <Button variant="ghost" onClick={approve} disabled={saving || Object.keys(edits).length > 0} title="Ctrl + Enter">Approve</Button>
          {msg && <span className="text-sm text-muted">{msg}</span>}
        </div>

        {showHistory && (
          <Card className="mt-4 p-4 text-sm">
            <h3 className="mb-2 font-semibold">Correction history</h3>
            {inv.corrections.length === 0 ? <p className="text-muted">No corrections yet.</p> : (
              <ol className="space-y-1">{inv.corrections.map((c: any, k: number) => (
                <li key={k}><span className="text-muted">{new Date(c.created_at).toLocaleString()}</span> {c.field}: <s>{c.old_value ?? "empty"}</s> to <b>{c.new_value ?? "empty"}</b> by {c.corrected_by}</li>
              ))}</ol>
            )}
          </Card>
        )}
      </section>
    </div>
  );
}
