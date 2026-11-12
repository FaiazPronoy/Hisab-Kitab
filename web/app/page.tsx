"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronRight, UploadCloud } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, eventsUrl, type Doc, type InvoiceSummary } from "@/lib/api";
import { Button, Chip, Panel, Spinner } from "@/components/ui";
import { useLang } from "@/lib/i18n";

type Row = { key: string; filename: string; id?: string; status: string; error?: string | null; doc?: Doc };
const STEPS = [
  { title: ["1. Check the file", "১. ফাইল দেখা"], text: ["Type, size, password and copies", "ধরন, আকার, পাসওয়ার্ড আর কপি"] },
  { title: ["2. Read", "২. পড়া"], text: ["Text if the PDF has it, OCR for scans", "PDF-এ লেখা থাকলে সেটা, স্ক্যানে OCR"] },
  { title: ["3. Check the numbers", "৩. হিসাব যাচাই"], text: ["Totals, tax, dates and copies", "যোগফল, ট্যাক্স, তারিখ আর কপি"] },
  { title: ["4. Review", "৪. রিভিউ"], text: ["Only unclear invoices go to a person", "শুধু সন্দেহজনকগুলো মানুষের কাছে যায়"] },
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
          className={clsx("h-2.5 w-2.5 rounded-[2px]", p.status === "done" ? (p.source === "ocr" ? "bg-[#5fa39a]" : "bg-brand") : p.status === "failed" ? "bg-[#c4242a]" : "bg-rule")} />
      ))}
    </div>
  );
}

function QueueRow({ row, update }: { row: Row; update: (r: Partial<Row>) => void }) {
  const { t } = useLang();
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
        {d && d.page_count > 0 && <span className="num text-xs text-muted">{d.pages_done}/{d.page_count} {t("pages", "পাতা")}</span>}
        <span className="flex items-center gap-2">{busy && <Spinner />}<Chip value={row.status} /></span>
        {row.id && FINAL.includes(row.status) && row.status !== "rejected" && (
          <Link className="text-sm font-medium text-brand hover:underline" href={`/documents/${row.id}`}>{t("Open", "খুলুন")}</Link>
        )}
        {(row.status === "completed_with_errors" || row.status === "failed") && (
          <Button variant="ghost" onClick={retry} disabled={retrying}>{retrying && <Spinner />} {t("Try again", "আবার চেষ্টা")}</Button>
        )}
      </div>
      {busy && d && d.page_count > 0 && (
        <div className="mt-2 h-1 rounded-full bg-rule" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={`${row.filename} progress`}>
          <div className="h-1 rounded-full bg-brand transition-[width]" style={{ width: `${pct}%` }} />
        </div>
      )}
      {row.error && <p className="mt-1 text-sm text-bad">{row.error}</p>}
      {d && <PageGrid doc={d} />}
    </li>
  );
}

function Pulse() {
  const { t } = useLang();
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
    <div className="mb-6 overflow-hidden rounded-lg bg-deep text-white">
      <div className="grid gap-px bg-white/10 sm:grid-cols-3">
        <div className="bg-deep px-5 py-4">
          <p className="text-xs text-[#a6c6c1]">{t("Files read", "পড়া ফাইল")}</p>
          <p className="num mt-1 text-2xl">{nDoc}</p>
          <p className="mt-0.5 text-xs text-[#a6c6c1]">{t(`${nInv} invoices found in them`, `এগুলোতে ${nInv}টি ইনভয়েস`)}</p>
        </div>
        <div className="bg-deep px-5 py-4">
          <p className="text-xs text-[#a6c6c1]">{t("Passed all checks, no person needed", "সব যাচাই পাস, মানুষ লাগেনি")}</p>
          <p className="num mt-1 text-2xl">{auto} <span className="text-base text-[#a6c6c1]">({share}%)</span></p>
          <div className="mt-2 h-1.5 rounded-full bg-white/10"><div className="h-1.5 rounded-full bg-coral" style={{ width: `${share}%` }} /></div>
        </div>
        <Link href="/review" className="group bg-deep px-5 py-4 transition-colors hover:bg-[#0f4a4a]">
          <p className="text-xs text-[#a6c6c1]">{t("Waiting for a person", "মানুষের অপেক্ষায়")}</p>
          <p className="num mt-1 text-2xl text-coral">{m.data.needs_review}</p>
          <p className="mt-0.5 flex items-center gap-1 text-xs text-[#cde2de] group-hover:text-white">{t("Open the review list", "রিভিউ তালিকা খুলুন")} <ChevronRight size={14} aria-hidden /></p>
        </Link>
      </div>
    </div>
  );
}

function Waiting() {
  const { t } = useLang();
  const q = useQuery({ queryKey: ["queue"], queryFn: () => api<InvoiceSummary[]>("/review-queue?limit=200"), refetchInterval: 5000 });
  const rows = q.data || [];
  return (
    <Panel title={t("To review", "রিভিউ বাকি")} meta={q.data ? t(`${rows.length} ${rows.length === 1 ? "invoice" : "invoices"}`, `${rows.length}টি ইনভয়েস`) : undefined}
      right={rows.length > 0 ? <Link href="/review" className="text-sm font-medium text-brand hover:underline">{t("See all", "সব দেখুন")}</Link> : null}>
      {q.isLoading ? <p className="px-4 py-4 text-sm text-muted">{t("Loading…", "লোড হচ্ছে…")}</p>
        : q.isError ? <p className="px-4 py-4 text-sm text-bad">{t("Could not load the list.", "তালিকা লোড হয়নি।")} <button type="button" className="underline" onClick={() => q.refetch()}>{t("Try again", "আবার চেষ্টা")}</button></p>
        : rows.length === 0 ? <p className="px-4 py-4 text-sm text-muted">{t("Nothing to review. Every invoice passed its checks.", "রিভিউ বাকি নেই। সব ইনভয়েস যাচাই পাস করেছে।")}</p> : (
        <ul>
          {rows.slice(0, 6).map((i) => {
            const bad = (i.findings.critical || 0) + (i.findings.error || 0);
            const warn = i.findings.warning || 0;
            return (
              <li key={i.id} className="border-b border-rule last:border-0">
                <Link href={`/invoices/${i.id}`} className="group flex items-center gap-3 px-4 py-2.5 hover:bg-paper">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-ink">{i.supplier_name || t("Unknown supplier", "অজানা সরবরাহকারী")}</span>
                    <span className="block truncate text-xs text-muted">
                      <span className="num">{i.invoice_number || t("no number", "নম্বর নেই")}</span>
                      {bad ? t(` · ${bad} ${bad === 1 ? "error" : "errors"}`, ` · ${bad}টি ত্রুটি`) : ""}{warn ? t(` · ${warn} ${warn === 1 ? "warning" : "warnings"}`, ` · ${warn}টি সতর্কতা`) : ""}
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
  const { t } = useLang();
  const [rows, setRows] = useState<Row[]>([]);
  const [drag, setDrag] = useState(false);
  const [sending, setSending] = useState(false);
  const [role, setRole] = useState("auto");
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const send = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length) return;
    setSending(true);
    setErr(null);
    const form = new FormData();
    list.forEach((f) => form.append("files", f));
    form.append("role", role);
    try {
      const res = await api<any[]>("/documents", { method: "POST", body: form });
      setRows((r) => [...res.map((x, i) => ({
        key: `${Date.now()}-${i}`, filename: x.filename, id: x.document_id, status: x.status,
        error: x.error_message || (x.duplicate_of ? t("Already uploaded. Showing the earlier copy.", "আগেই আপলোড করা। আগের কপি দেখানো হচ্ছে।") : null),
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
        <h1 className="text-[22px] leading-7 font-semibold tracking-[-0.01em] sm:text-2xl">{t("Upload invoices", "ইনভয়েস আপলোড")}</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">{t("Add your files. We read and check them, and show the progress here.", "ফাইল দিন। আমরা পড়ে যাচাই করি, আর অগ্রগতি এখানে দেখাই।")}</p>
      </div>

      <Pulse />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-6">
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDrag(false); }}
            onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}
            className={clsx("rounded-lg border bg-surface transition-colors", drag ? "border-accent ring-4 ring-accent/15" : "border-line")}
          >
            <div className={clsx("m-2 flex flex-col items-start gap-5 rounded-md border border-dashed px-5 py-7 sm:flex-row sm:items-center sm:px-7 sm:py-9",
              drag ? "border-accent bg-warnwash" : "border-control bg-paper")}>
              <UploadCloud size={28} strokeWidth={1.5} className={drag ? "text-accent" : "text-brand"} aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="text-base font-semibold text-ink">{drag ? t("Drop the files here", "এখানে ছেড়ে দিন") : t("Drag invoices, scans or Excel files here", "ইনভয়েস, স্ক্যান বা Excel ফাইল এখানে টেনে আনুন")}</p>
                <p className="mt-1 text-sm text-muted">{t("You can add many files at once. Big PDFs are read page by page.", "একসাথে অনেক ফাইল দিতে পারেন। বড় PDF পাতা ধরে পড়া হয়।")}</p>
                <p className="mt-3 text-xs text-muted" id="types">{t("File types", "ফাইলের ধরন")}: {TYPES.join(", ")}</p>
                <label className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
                  {t("Excel files are", "Excel ফাইলগুলো")}
                  <select value={role} onChange={(e) => setRole(e.target.value)} className="h-8 rounded-md border border-control bg-surface px-2 text-xs text-ink max-sm:h-10">
                    <option value="auto">{t("found out from the headers", "হেডার দেখে বোঝা হবে")}</option>
                    <option value="invoices">{t("lists of invoices", "ইনভয়েসের তালিকা")}</option>
                    <option value="ledger">{t("payment records (ledger)", "পেমেন্টের হিসাব (লেজার)")}</option>
                    <option value="purchase_orders">{t("purchase orders", "ক্রয় আদেশ")}</option>
                  </select>
                </label>
              </div>
              <Button onClick={() => input.current?.click()} disabled={sending} aria-describedby="types">
                {sending && <Spinner />} {sending ? t("Uploading…", "আপলোড হচ্ছে…") : t("Choose files", "ফাইল বাছুন")}
              </Button>
              <input ref={input} type="file" multiple hidden accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.xlsx,.xls,.csv"
                onChange={(e) => e.target.files && send(e.target.files)} />
            </div>
            <ol className="grid grid-cols-2 gap-px overflow-hidden rounded-b-lg border-t border-line bg-line sm:grid-cols-4" aria-label={t("What happens to each file", "প্রতিটি ফাইলের কী হয়")}>
              {STEPS.map((s) => (
                <li key={s.title[0]} className="bg-surface px-4 py-3">
                  <span className="block text-sm font-medium text-ink">{t(s.title[0], s.title[1])}</span>
                  <span className="block text-xs leading-[18px] text-muted">{t(s.text[0], s.text[1])}</span>
                </li>
              ))}
            </ol>
          </div>

          {err && <p className="text-sm text-bad" role="alert">{err}</p>}

          <Panel title={t("Uploaded now", "এখন আপলোড করা")} meta={rows.length ? t(`${rows.length} ${rows.length === 1 ? "file" : "files"}`, `${rows.length}টি ফাইল`) : undefined}>
            {rows.length === 0 ? (
              <p className="px-4 py-4 text-sm text-muted">{t("No files yet. Choose some above, or open Documents to see the demo files.", "এখনো কোনো ফাইল নেই। উপরে বেছে নিন, অথবা ডকুমেন্টে ডেমো ফাইল দেখুন।")}</p>
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
