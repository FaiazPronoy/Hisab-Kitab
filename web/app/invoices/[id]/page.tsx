"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronLeft, ChevronRight, History } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useMemo, useState } from "react";
import { api, imageUrl, type Field, type Finding } from "@/lib/api";
import { Button, Chip, Confidence, Empty, ErrorNote, Loading, Spinner } from "@/components/ui";

const ORDER = ["invoice_number", "invoice_date", "due_date", "supplier_name", "customer_name", "po_number",
  "currency", "subtotal", "discount", "shipping", "tax", "total"];
const SEV_ORDER = ["critical", "error", "warning", "info"];
const MONEY = ["subtotal", "discount", "shipping", "tax", "total"];
const LABEL: Record<string, string> = { po_number: "PO number" };
const label = (k: string) => LABEL[k] || k.charAt(0).toUpperCase() + k.slice(1).replaceAll("_", " ");

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
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => { if (inv && page == null) setPage(inv.page_start || 1); }, [inv, page]);
  useEffect(() => { setEdits({}); setFindings(null); setFocus(null); setPage(null); setMsg(null); }, [id]);

  const fields: Record<string, Field> = inv?.fields || {};
  const boxes = useMemo(() => {
    const out: { key: string; bbox: number[] }[] = [];
    for (const [k, f] of Object.entries(fields)) if (f.bbox && f.page === page) out.push({ key: k, bbox: f.bbox });
    if (inv?.bank_evidence?.bbox && inv.bank_evidence.page === page) out.push({ key: "bank_account", bbox: inv.bank_evidence.bbox });
    (inv?.line_items || []).forEach((li: any, i: number) => {
      if (li.evidence?.bbox && li.evidence.page === page) out.push({ key: `line_items[${i}]`, bbox: li.evidence.bbox });
    });
    return out;
  }, [fields, inv, page]);

  const dirty = Object.keys(edits).length > 0;

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const save = async () => {
    const corrections = Object.entries(edits).map(([field, value]) => ({ field, value: value === "" ? null : value, reason: "review" }));
    if (!corrections.length || saving) return;
    setSaving(true);
    setMsg(null);
    try {
      const r = await api<any>(`/invoices/${id}`, { method: "PATCH", body: JSON.stringify({ corrections, version: inv.version }) });
      setFindings(r.findings);
      setEdits({});
      await qc.invalidateQueries({ queryKey: ["inv", id] });
      const learned = (r.learned || []).length ? ` Remembered for this supplier: ${r.learned.join("; ")}.` : "";
      setMsg({ text: (r.status === "auto_validated" ? "Saved. All checks pass." : "Saved. Some checks still need attention.") + learned });
    } catch (e: any) {
      setMsg({ text: e.message, bad: true });
    } finally {
      setSaving(false);
    }
  };

  const approve = async () => {
    if (dirty || saving) return;
    setSaving(true);
    setMsg(null);
    try {
      const r = await api<any>(`/invoices/${id}/approve`, { method: "POST", body: JSON.stringify({ version: inv.version }) });
      qc.invalidateQueries({ queryKey: ["queue"] });
      qc.invalidateQueries({ queryKey: ["metrics"] });
      if (r.next_invoice_id) router.push(`/invoices/${r.next_invoice_id}`);
      else { await qc.invalidateQueries({ queryKey: ["inv", id] }); setMsg({ text: "Approved. The review queue is empty." }); }
    } catch (e: any) {
      setMsg({ text: e.message, bad: true });
    } finally {
      setSaving(false);
    }
  };

  const next = async () => {
    try {
      const queue = await api<any[]>("/review-queue?limit=50");
      const nxt = queue.find((x) => x.id !== id);
      if (nxt) router.push(`/invoices/${nxt.id}`);
      else setMsg({ text: "No other invoice is waiting for review." });
    } catch (e: any) {
      setMsg({ text: e.message, bad: true });
    }
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

  const back = <Link href="/review" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-ink"><ChevronLeft size={16} aria-hidden /> Review queue</Link>;
  if (q.isLoading) return <>{back}<Loading rows={8} /></>;
  if (q.isError && !inv) return <>{back}<ErrorNote retry={() => q.refetch()}>Could not load this invoice. {(q.error as Error).message}</ErrorNote></>;
  if (!inv) return <>{back}<Empty>Invoice not found.</Empty></>;

  const shown: Finding[] = (findings ?? inv.findings_list).slice().sort((a: Finding, b: Finding) => SEV_ORDER.indexOf(a.severity) - SEV_ORDER.indexOf(b.severity));
  const pages: number[] = inv.page_start ? Array.from({ length: inv.page_end - inv.page_start + 1 }, (_, i) => inv.page_start + i) : [];
  const pick = (key: string, f?: Field) => { setFocus(key); if (f?.page) setPage(f.page); };

  return (
    <>
      {back}
      <div className="mb-5 flex flex-wrap items-start gap-x-4 gap-y-3">
        <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
          <h1 className="text-[22px] leading-7 font-semibold tracking-[-0.01em] sm:text-2xl">{inv.supplier_name || "Unknown supplier"}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
            <span className="num text-ink">{inv.invoice_number || "no number"}</span>
            {inv.total && <>· <span className="num text-ink">{inv.total}</span> {inv.currency}</>}
            <span>· {inv.filename || "document"}{pages.length ? `, page ${pages[0]}${pages.length > 1 ? `-${pages[pages.length - 1]}` : ""}` : ""}</span>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Chip value={inv.status} />
          <Button variant="ghost" onClick={() => setShowHistory((v) => !v)} aria-expanded={showHistory}><History size={15} aria-hidden /> History <span className="num text-xs text-muted">{inv.corrections.length}</span></Button>
          <Button variant="ghost" onClick={next} title="Alt + Right arrow">Next <ChevronRight size={15} aria-hidden /></Button>
        </div>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        <section aria-label="Document page" className="lg:sticky lg:top-6">
          <div className="rounded-lg border border-line bg-sunken p-2 sm:p-3">
            <div className="mb-2 flex flex-wrap items-center gap-1.5 text-sm">
              {pages.length > 0 ? pages.map((n) => (
                <button key={n} type="button" onClick={() => setPage(n)} aria-pressed={n === page}
                  className={clsx("num h-8 min-w-10 rounded px-2 text-[13px] transition-colors max-sm:h-10", n === page ? "bg-brand-dark text-white" : "bg-surface text-ink hover:bg-paper")}>p{n}</button>
              )) : <span className="px-1 text-muted">From sheet {inv.sheet_name}{inv.row_index ? `, row ${inv.row_index}` : ""}</span>}
              {boxes.length > 0 && <span className="ml-auto px-1 text-xs text-muted">{boxes.length} values found on this page</span>}
            </div>
            {page && pages.length > 0 ? (
              <div className="relative overflow-hidden rounded border border-control bg-surface">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={imageUrl(inv.document_id, page)} alt={`Page ${page} of ${inv.filename || "the document"}`} className="block w-full" />
                <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="pointer-events-none absolute inset-0 h-full w-full">
                  {boxes.map((b) => (
                    <rect key={b.key} x={b.bbox[0] - 0.004} y={b.bbox[1] - 0.003} width={b.bbox[2] - b.bbox[0] + 0.008} height={b.bbox[3] - b.bbox[1] + 0.006}
                      className="pointer-events-auto cursor-pointer" onMouseEnter={() => setFocus(b.key)}
                      fill={focus === b.key ? "rgba(217,119,6,0.22)" : "rgba(26,54,93,0.06)"} stroke={focus === b.key ? "#d97706" : "rgba(26,54,93,0.4)"} strokeWidth={focus === b.key ? 0.003 : 0.0015} />
                  ))}
                </svg>
              </div>
            ) : <p className="rounded bg-surface px-4 py-6 text-sm text-muted">Spreadsheet rows have no page image. The values below come straight from the cells.</p>}
          </div>
        </section>

        <section aria-label="Extracted values" className="min-w-0">
          {inv.payment_batch_id && <p className="mb-3 rounded-md border border-line bg-infowash px-3 py-2 text-sm text-ink2">This invoice is in a payment file and can no longer be changed.</p>}
          {inv.approved_by && inv.status === "approved" && <p className="mb-3 rounded-md border border-line bg-goodwash px-3 py-2 text-sm text-good">Approved by {inv.approved_by}{inv.approved_at ? `, ${new Date(inv.approved_at).toLocaleString()}` : ""}.</p>}
          {inv.document_role === "ledger" && <p className="mb-3 rounded-md border border-line bg-plainwash px-3 py-2 text-sm text-ink2">A row of a payment ledger. It is used for reconciliation and is never approved.</p>}
          {inv.document_role === "purchase_orders" && <p className="mb-3 rounded-md border border-line bg-plainwash px-3 py-2 text-sm text-ink2">A purchase order. Invoices that cite it are checked against its supplier and amount.</p>}
          {inv.flags?.includes("memory_used") && <p className="mb-3 rounded-md border border-line bg-infowash px-3 py-2 text-sm text-ink2">Some values were found with labels learned from earlier corrections for this supplier. They are marked &ldquo;learned&rdquo;.</p>}
          {inv.flags?.includes("vision_used") && <p className="mb-3 rounded-md border border-warnline bg-warnwash px-3 py-2 text-sm text-accent-ink">Some values were read from the page image. They have no box to highlight.</p>}

          <div className="mb-4 rounded-lg border border-line bg-surface">
            <h2 className="flex items-center gap-2 border-b border-line px-4 py-3 text-[15px] font-semibold">
              Checks {shown.length > 0 && <span className="num text-xs font-normal text-muted">{shown.length} {shown.length === 1 ? "finding" : "findings"}</span>}
            </h2>
            {shown.length > 0 ? (
              <ul>
                {shown.map((f, k) => {
                  const hard = f.severity === "critical" || f.severity === "error";
                  return (
                    <li key={k} className="flex items-start border-b border-rule last:border-0">
                      <button type="button" disabled={!f.field} onClick={() => f.field && pick(f.field, fields[f.field])}
                        className={clsx("flex min-w-0 flex-1 gap-3 px-4 py-2.5 text-left text-sm enabled:hover:bg-paper", f.field && focus === f.field && "bg-paper")}>
                        <span className={clsx("mt-1.5 h-2 w-2 shrink-0 rounded-full", hard ? "bg-[#c4242a]" : f.severity === "warning" ? "bg-accent" : "bg-[#8a919c]")} aria-label={f.severity} />
                        <span className="min-w-0">
                          <span className="num mr-2 text-xs text-muted">{f.rule_code}</span>
                          <span className="text-ink">{f.message}</span>
                          {f.expected && f.actual && <span className="block text-[13px] text-muted">Expected <span className="num text-ink">{f.expected}</span>, found <span className="num text-ink">{f.actual}</span>.</span>}
                          {!f.expected && f.actual && <span className="block text-[13px] text-muted">Value: <span className="num text-ink">{f.actual}</span>.</span>}
                        </span>
                      </button>
                      {f.rule_code.startsWith("DUP_") && f.related_invoice_id && (
                        <Link href={`/compare?left=${id}&right=${f.related_invoice_id}`} className="mt-2 mr-3 shrink-0 rounded-md border border-control px-2.5 py-1 text-xs font-medium hover:bg-paper">Compare</Link>
                      )}
                    </li>
                  );
                })}
              </ul>
            ) : <p className="flex items-center gap-2 px-4 py-3 text-sm text-good"><span className="h-2 w-2 rounded-full bg-[#1f8a4c]" aria-hidden />All checks pass.</p>}
          </div>

          <div className="rounded-lg border border-line bg-surface">
            <h2 className="border-b border-line px-4 py-3 text-[15px] font-semibold">Fields</h2>
            <div className={clsx("grid grid-cols-1 gap-x-3 gap-y-1 border-b border-rule px-4 py-2.5 sm:grid-cols-[8.5rem_minmax(0,1fr)]", focus === "bank_account" && "bg-warnwash")}>
              <label htmlFor="f-bank_account" className="text-[13px] text-muted sm:pt-2">Pay to account</label>
              <div className="min-w-0">
                <input id="f-bank_account" value={edits.bank_account ?? inv.bank_account ?? ""} spellCheck={false} autoComplete="off"
                  onFocus={() => { setFocus("bank_account"); if (inv.bank_evidence?.page) setPage(inv.bank_evidence.page); }}
                  onChange={(e) => setEdits({ ...edits, bank_account: e.target.value })} placeholder="Not on document"
                  className={clsx("num h-9 w-full min-w-0 rounded-md border bg-surface px-2.5 text-sm placeholder:font-sans placeholder:text-faint focus:outline-none focus:ring-2 max-sm:h-11",
                    edits.bank_account !== undefined ? "border-accent focus:ring-accent/20" : "border-control focus:border-brand focus:ring-brand/15")} />
                {inv.bank_evidence?.quote && <p className="mt-1 truncate text-xs text-muted">&ldquo;{inv.bank_evidence.quote}&rdquo; <span className="num">{inv.bank_evidence.line_id}</span></p>}
              </div>
            </div>
            {ORDER.map((k) => {
              const f = fields[k];
              if (!f) return null;
              const val = edits[k] ?? f.value ?? "";
              return (
                <div key={k} className={clsx("grid grid-cols-1 gap-x-3 gap-y-1 border-b border-rule px-4 py-2.5 last:border-0 sm:grid-cols-[8.5rem_minmax(0,1fr)]", focus === k && "bg-warnwash")}>
                  <label htmlFor={`f-${k}`} className="text-[13px] text-muted sm:pt-2">{label(k)}</label>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <input id={`f-${k}`} value={val} onFocus={() => pick(k, f)} onChange={(e) => setEdits({ ...edits, [k]: e.target.value })}
                        placeholder={f.null_reason ? "Not on document" : ""} spellCheck={false} autoComplete="off" inputMode={MONEY.includes(k) ? "decimal" : undefined}
                        className={clsx("h-9 w-full min-w-0 rounded-md border bg-surface px-2.5 text-sm placeholder:text-faint focus:outline-none focus:ring-2 max-sm:h-11",
                          MONEY.includes(k) && "num text-right placeholder:font-sans placeholder:tracking-normal",
                          edits[k] !== undefined ? "border-accent focus:ring-accent/20" : "border-control focus:border-brand focus:ring-brand/15")} />
                      <Confidence c={f.confidence} reason={f.value ? null : f.null_reason} source={f.source} />
                    </div>
                    {f.quote && <p className="mt-1 truncate text-xs text-muted" title={f.quote}>&ldquo;{f.quote}&rdquo;{f.line_id && <span className="num"> {f.line_id}</span>}{!f.bbox && f.source === "vision" && ", no box available"}</p>}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-4 rounded-lg border border-line bg-surface">
            <h2 className="flex items-center gap-2 border-b border-line px-4 py-3 text-[15px] font-semibold">
              Line items <span className="num text-xs font-normal text-muted">{inv.line_items.length}</span>
            </h2>
            {inv.line_items.length === 0 ? <p className="px-4 py-3 text-sm text-muted">No line items.</p> : (
              <div className="overflow-x-auto">
                <table className="tbl min-w-[30rem] text-sm">
                  <thead><tr><th>Description</th><th className="r w-20">Qty</th><th className="r w-28">Unit</th><th className="r w-28">Amount</th></tr></thead>
                  <tbody>
                    {inv.line_items.map((li: any, i: number) => (
                      <tr key={i} className={clsx(focus === `line_items[${i}]` && "[&>td]:bg-warnwash")}>
                        {(["description", "quantity", "unit_price", "amount"] as const).map((c) => {
                          const key = `line_items[${li.idx}].${c}`;
                          return (
                            <td key={c} className="!px-2 !py-1">
                              <input aria-label={`${c.replace("_", " ")} line ${i + 1}`} value={edits[key] ?? li[c] ?? ""} onFocus={() => setFocus(`line_items[${i}]`)}
                                onChange={(e) => setEdits({ ...edits, [key]: e.target.value })}
                                className={clsx("h-8 w-full rounded border px-1.5 focus:border-brand focus:outline-none", c !== "description" && "num text-right",
                                  !li.evidence?.verified && "text-accent-ink",
                                  edits[key] !== undefined ? "border-accent" : "border-transparent hover:border-line")} />
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="sticky bottom-0 z-10 -mx-4 mt-4 flex flex-wrap items-center gap-2 border-t border-line bg-surface px-4 py-3 shadow-[0_-6px_16px_rgba(16,24,40,0.06)] sm:bottom-3 sm:mx-0 sm:rounded-lg sm:border sm:shadow-[0_8px_24px_rgba(16,24,40,0.12)]">
            <Button onClick={save} disabled={saving || !dirty} title="Ctrl + S">{saving && dirty && <Spinner />} Save corrections</Button>
            <Button variant="ghost" onClick={approve} disabled={saving || dirty} title="Ctrl + Enter">{saving && !dirty && <Spinner />} Approve</Button>
            <span className="hidden text-xs text-muted xl:inline">Ctrl + S saves, Ctrl + Enter approves</span>
            {msg && <span className={clsx("w-full text-sm sm:w-auto", msg.bad ? "text-bad" : "text-muted")} role="status">{msg.text}</span>}
          </div>

          {showHistory && (
            <div className="mt-4 rounded-lg border border-line bg-surface">
              <h3 className="border-b border-line px-4 py-3 text-[15px] font-semibold">Correction history</h3>
              {inv.corrections.length === 0 ? <p className="px-4 py-3 text-sm text-muted">No corrections yet.</p> : (
                <ol>{inv.corrections.map((c: any, k: number) => (
                  <li key={k} className="border-b border-rule px-4 py-2.5 text-sm last:border-0">
                    <span className="text-muted">{label(c.field)}</span>{" "}
                    <s className="num text-muted">{c.old_value ?? "empty"}</s> to <b className="num font-medium">{c.new_value ?? "empty"}</b>
                    <span className="block text-xs text-muted">{c.corrected_by}, {new Date(c.created_at).toLocaleString()}</span>
                  </li>
                ))}</ol>
              )}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
