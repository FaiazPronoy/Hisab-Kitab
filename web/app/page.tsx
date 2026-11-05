"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, eventsUrl, type Doc } from "@/lib/api";
import { Button, Card, Chip, Empty, PageTitle, Spinner } from "@/components/ui";

type Row = { key: string; filename: string; id?: string; status: string; error?: string | null; doc?: Doc };
const FINAL = ["done", "needs_review", "completed_with_errors", "failed", "rejected"];

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
    <div className="mt-3 flex flex-wrap gap-0.5" aria-label="Page status">
      {doc.pages.map((p) => (
        <span key={p.page_no} title={`Page ${p.page_no}: ${p.status}${p.source ? ` (${p.source})` : ""}`}
          className={`h-2.5 w-2.5 rounded-sm ${p.status === "done" ? (p.source === "ocr" ? "bg-blue-500" : "bg-green-500") : p.status === "failed" ? "bg-red-500" : "bg-slate-200"}`} />
      ))}
    </div>
  );
}

function QueueRow({ row, update }: { row: Row; update: (r: Partial<Row>) => void }) {
  useDocProgress(row, (d) => update({ status: d.status, doc: d, error: d.error_message }));
  const d = row.doc;
  const pct = d && d.page_count ? Math.round(((d.pages_done + d.pages_failed) / d.page_count) * 100) : 0;
  const busy = !FINAL.includes(row.status);
  const retry = async () => {
    await api(`/documents/${row.id}/reprocess`, { method: "POST", body: JSON.stringify({ scope: row.status === "failed" ? "all" : "failed_only" }) });
    update({ status: "processing" });
  };
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className="min-w-0 flex-1 truncate font-medium">{row.filename}</span>
        {busy && <Spinner />}
        <Chip value={row.status} />
        {d && d.page_count > 0 && <span className="text-xs tabular-nums text-muted">{d.pages_done}/{d.page_count} pages</span>}
        {row.id && FINAL.includes(row.status) && row.status !== "rejected" && (
          <Link className="text-sm text-brand underline" href={`/documents/${row.id}`}>Open</Link>
        )}
        {(row.status === "completed_with_errors" || row.status === "failed") && <Button variant="ghost" onClick={retry}>Retry</Button>}
      </div>
      {busy && d && d.page_count > 0 && (
        <div className="mt-2 h-1.5 rounded-full bg-paper"><div className="h-1.5 rounded-full bg-brand transition-all" style={{ width: `${pct}%` }} /></div>
      )}
      {row.error && <p className="mt-1 text-sm text-red-700">{row.error}</p>}
      {d && <PageGrid doc={d} />}
    </li>
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
        key: `${Date.now()}-${i}`, filename: x.filename, id: x.document_id, status: x.duplicate_of ? x.status : x.status,
        error: x.error_message || (x.duplicate_of ? "Already uploaded; showing the existing document." : null),
      })), ...r]);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      <PageTitle title="Upload documents" sub="PDF, JPG, PNG, TIFF, XLSX, XLS and CSV. Each file is checked, read and validated in the background." />
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}
        className={`rounded-lg border-2 border-dashed p-10 text-center transition ${drag ? "border-brand bg-blue-50" : "border-line bg-white"}`}
      >
        <p className="text-ink">Drop files here</p>
        <p className="mt-1 text-sm text-muted">or</p>
        <Button className="mt-3" onClick={() => input.current?.click()} disabled={sending}>
          {sending && <Spinner />} Choose files
        </Button>
        <input ref={input} type="file" multiple hidden accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.xlsx,.xls,.csv"
          onChange={(e) => e.target.files && send(e.target.files)} />
      </div>
      {err && <p className="mt-3 text-sm text-red-700">{err}</p>}
      <h2 className="mb-2 mt-8 text-sm font-semibold uppercase tracking-wide text-muted">This session</h2>
      {rows.length === 0 ? <Empty>Nothing uploaded yet. Run <code>make seed</code> to load the demo batch.</Empty> : (
        <Card><ul className="divide-y divide-line">
          {rows.map((r) => <QueueRow key={r.key} row={r} update={(u) => setRows((all) => all.map((x) => (x.key === r.key ? { ...x, ...u } : x)))} />)}
        </ul></Card>
      )}
    </>
  );
}
