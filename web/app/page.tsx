"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronRight, UploadCloud } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, eventsUrl, type Doc, type InvoiceSummary } from "@/lib/api";
import { Button, Chip, Panel, Spinner } from "@/components/ui";

type Row = { key: string; filename: string; id?: string; status: string; error?: string | null; doc?: Doc };
const STEPS = [
  { title: "Check", text: "Type, size, password and duplicates" },
  { title: "Read", text: "Text layer first, OCR for scans" },
  { title: "Validate", text: "Totals, tax, dates and duplicates" },
  { title: "Review", text: "Only doubtful invoices reach a person" },
];
const FINAL = ["done", "needs_review", "completed_with_errors", "failed", "rejected"];
const TYPES = ["PDF", "JPG", "PNG", "TIFF", "XLSX", "XLS", "CSV"];

function useDocProgress(row: Row, onDoc: (d: Doc) => void) {
  useEffect(() => {
    if (!row.id || FINAL.includes(row.status)) return;
    let stop = false;
    const pull = () => api<Doc>(`/documents/${row.id}`).then((d) => !stop && onDoc(d)).catch(() => {});
    pull();
    // SSE pushes page events; a slow poll covers dropped connections
    const es = new EventSource(eventsUrl(row.id));
    es.onmessage = () => pull();
    const t = setInterval(pull, 2000);
    return () => { stop = true; es.close(); clearInterval(t); };
  }, [row.id, row.status]); // eslint-disable-line react-hooks/exhaustive-deps
}

function PageGrid({ doc }: { doc: Doc }) {
  if (!doc.pages || doc.page_count < 2) return null;
  return (
    <div className="mt-2.5 flex flex-wrap gap-[3px]" aria-label="Page status">
      {doc.pages.map((p) => (
        <span key={p.page_no} title={`Page ${p.page_no}: ${p.status}${p.source ? ` (${p.source})` : ""}`}
          className={clsx("h-2.5 w-2.5 rounded-[2px]", p.status === "done" ? (p.source === "ocr" ? "bg-[#6b86ad]" : "bg-brand") : p.status === "failed" ? "bg-[#c4242a]" : "bg-rule")} />
      ))}
    </div>
  );
}

function QueueRow({ row, update }: { row: Row; update: (r: Partial<Row>) => void }) {
  useDocProgress(row, (d) => update({ status: d.status, doc: d, error: d.error_message }));
  const [retrying, setRetrying] = useState(false);
  const d = row.doc;
  const pct = d && d.page_count ? Math.round(((d.pages_done + d.pages_failed) / d.page_count) * 100) : 0;
  const busy = !FINAL.includes(row.status);
  const retry = async () => {
    setRetrying(true);
    try {
      await api(`/documents/${row.id}/reprocess`, { method: "POST", body: JSON.stringify({ scope: row.status === "failed" ? "all" : "failed_only" }) });
      update({ status: "processing", error: null });
    } catch (e: any) {
      update({ error: e.message });
    } finally {
      setRetrying(false);
    }
  };
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="min-w-0 flex-1 truncate font-medium" title={row.filename}>{row.filename}</span>
        {d && d.page_count > 0 && <span className="num text-xs text-muted">{d.pages_done}/{d.page_count} pages</span>}
        <span className="flex items-center gap-2">{busy && <Spinner />}<Chip value={row.status} /></span>
        {row.id && FINAL.includes(row.status) && row.status !== "rejected" && (
          <Link className="text-sm font-medium text-brand hover:underline" href={`/documents/${row.id}`}>Open</Link>
        )}
        {(row.status === "completed_with_errors" || row.status === "failed") && (
          <Button variant="ghost" onClick={retry} disabled={retrying}>{retrying && <Spinner />} Retry</Button>
        )}
      </div>
      {busy && d && d.page_count > 0 && (
        <div className="mt-2 h-1 rounded-full bg-rule" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={`${row.filename} progress`}>
          <div className="h-1 rounded-full bg-brand transition-[width]" style={{ width: `${pct}%` }} />
        </div>
      )}
      {row.error && <p className="mt-1 text-sm text-[#8a1c1f]">{row.error}</p>}
      {d && <PageGrid doc={d} />}
    </li>
  );
}

function Pulse() {
  const m = useQuery({ queryKey: ["metrics"], queryFn: () => api<any>("/metrics/summary"), refetchInterval: 10000 });
  if (!m.data) return null;
  const invs: Record<string, number> = m.data.invoices || {};
  const docs: Record<string, number> = m.data.documents || {};
  const nInv = Object.values(invs).reduce((a, b) => a + b, 0);
  const nDoc = Object.values(docs).reduce((a, b) => a + b, 0);
  if (!nDoc) return null;
  const auto = invs.auto_validated || 0;
  const share = nInv ? Math.round((auto / nInv) * 100) : 0;
  return (
    <div className="mb-6 overflow-hidden rounded-lg bg-navy text-white">
      <div className="grid gap-px bg-white/10 sm:grid-cols-3">
        <div className="bg-navy px-5 py-4">
          <p className="text-xs text-[#9fb2cf]">Documents read</p>
          <p className="num mt-1 text-2xl">{nDoc}</p>
          <p className="mt-0.5 text-xs text-[#9fb2cf]">{nInv} invoices found in them</p>
        </div>
        <div className="bg-navy px-5 py-4">
          <p className="text-xs text-[#9fb2cf]">Passed every check on their own</p>
          <p className="num mt-1 text-2xl">{auto} <span className="text-base text-[#9fb2cf]">({share}%)</span></p>
          <div className="mt-2 h-1.5 rounded-full bg-white/10"><div className="h-1.5 rounded-full bg-amber" style={{ width: `${share}%` }} /></div>
        </div>
        <Link href="/review" className="group bg-navy px-5 py-4 transition-colors hover:bg-[#152c4f]">
          <p className="text-xs text-[#9fb2cf]">Waiting for a person</p>
          <p className="num mt-1 text-2xl text-amber">{m.data.needs_review}</p>
          <p className="mt-0.5 flex items-center gap-1 text-xs text-[#c3cfe2] group-hover:text-white">Open the review queue <ChevronRight size={14} aria-hidden /></p>
        </Link>
      </div>
    </div>
  );
}

function Waiting() {
  const q = useQuery({ queryKey: ["queue"], queryFn: () => api<InvoiceSummary[]>("/review-queue?limit=200"), refetchInterval: 5000 });
  const rows = q.data || [];
  return (
    <Panel title="Waiting for review" meta={q.data ? `${rows.length} ${rows.length === 1 ? "invoice" : "invoices"}` : undefined}
      right={rows.length > 0 ? <Link href="/review" className="text-sm font-medium text-brand hover:underline">View all</Link> : null}>
      {q.isLoading ? <p className="px-4 py-4 text-sm text-muted">Loading the queue…</p>
        : q.isError ? <p className="px-4 py-4 text-sm text-[#8a1c1f]">Could not load the queue. <button type="button" className="underline" onClick={() => q.refetch()}>Retry</button></p>
        : rows.length === 0 ? <p className="px-4 py-4 text-sm text-muted">Nothing waiting. Every processed invoice passed its checks.</p> : (
        <ul>
          {rows.slice(0, 6).map((i) => {
            const bad = (i.findings.critical || 0) + (i.findings.error || 0);
            const warn = i.findings.warning || 0;
            return (
              <li key={i.id} className="border-b border-rule last:border-0">
                <Link href={`/invoices/${i.id}`} className="group flex items-center gap-3 px-4 py-2.5 hover:bg-paper">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-ink">{i.supplier_name || "Unknown supplier"}</span>
                    <span className="block truncate text-xs text-muted">
                      <span className="num">{i.invoice_number || "no number"}</span>
                      {bad ? ` · ${bad} ${bad === 1 ? "error" : "errors"}` : ""}{warn ? ` · ${warn} ${warn === 1 ? "warning" : "warnings"}` : ""}
                    </span>
                  </span>
                  <span className="num shrink-0 text-right text-sm">{i.total ?? "-"} <span className="text-xs text-muted">{i.currency}</span></span>
                  <ChevronRight size={16} className="shrink-0 text-faint group-hover:text-ink" aria-hidden />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

export default function UploadPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [drag, setDrag] = useState(false);
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const send = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length) return;
    setSending(true);
    setErr(null);
    const form = new FormData();
    list.forEach((f) => form.append("files", f));
    try {
      const res = await api<any[]>("/documents", { method: "POST", body: form });
      setRows((r) => [...res.map((x, i) => ({
        key: `${Date.now()}-${i}`, filename: x.filename, id: x.document_id, status: x.status,
        error: x.error_message || (x.duplicate_of ? "Already uploaded; showing the existing document." : null),
      })), ...r]);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSending(false);
      if (input.current) input.current.value = "";
    }
  };

  return (
    <>
      <div className="mb-6">
        <h1 className="text-[22px] leading-7 font-semibold tracking-[-0.01em] sm:text-2xl">Upload documents</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">Each file is checked, read and validated in the background. Progress shows here page by page.</p>
      </div>

      <Pulse />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-6">
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDrag(false); }}
            onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}
            className={clsx("rounded-lg border bg-white transition-colors", drag ? "border-accent ring-4 ring-accent/15" : "border-line")}
          >
            <div className={clsx("m-2 flex flex-col items-start gap-5 rounded-md border border-dashed px-5 py-7 sm:flex-row sm:items-center sm:px-7 sm:py-9",
              drag ? "border-accent bg-[#fffaf2]" : "border-control bg-paper")}>
              <UploadCloud size={28} strokeWidth={1.5} className={drag ? "text-accent" : "text-brand"} aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="text-base font-semibold text-ink">{drag ? "Drop to upload" : "Drop invoices, scans or spreadsheets here"}</p>
                <p className="mt-1 text-sm text-muted">Several files at once is fine. Large PDFs are split into pages and read in parallel.</p>
                <p className="mt-3 text-xs text-muted" id="types">Accepts {TYPES.join(", ")}</p>
              </div>
              <Button onClick={() => input.current?.click()} disabled={sending} aria-describedby="types">
                {sending && <Spinner />} {sending ? "Uploading…" : "Choose files"}
              </Button>
              <input ref={input} type="file" multiple hidden accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.xlsx,.xls,.csv"
                onChange={(e) => e.target.files && send(e.target.files)} />
            </div>
            <ol className="grid grid-cols-2 gap-px overflow-hidden rounded-b-lg border-t border-line bg-line sm:grid-cols-4" aria-label="What happens to each file">
              {STEPS.map((s) => (
                <li key={s.title} className="bg-white px-4 py-3">
                  <span className="block text-sm font-medium text-ink">{s.title}</span>
                  <span className="block text-xs leading-[18px] text-muted">{s.text}</span>
                </li>
              ))}
            </ol>
          </div>

          {err && <p className="text-sm text-[#8a1c1f]" role="alert">{err}</p>}

          <Panel title="This session" meta={rows.length ? `${rows.length} ${rows.length === 1 ? "file" : "files"}` : undefined}>
            {rows.length === 0 ? (
              <p className="px-4 py-4 text-sm text-muted">Nothing uploaded in this session yet. Run <code className="num rounded bg-rule px-1 text-[13px]">make seed</code> to load the demo batch.</p>
            ) : (
              <ul className="divide-y divide-rule">
                {rows.map((r) => <QueueRow key={r.key} row={r} update={(u) => setRows((all) => all.map((x) => (x.key === r.key ? { ...x, ...u } : x)))} />)}
              </ul>
            )}
          </Panel>
        </div>

        <Waiting />
      </div>
    </>
  );
}
