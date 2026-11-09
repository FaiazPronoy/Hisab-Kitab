"use client";
import clsx from "clsx";
import { Search as SearchIcon, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { Button, Card, Chip, Empty, ErrorNote, PageTitle, Spinner, inputCls } from "@/components/ui";

type F = { q: string; mode: string; supplier: string; currency: string; status: string; date_from: string; date_to: string; min_total: string; max_total: string };
const BLANK: F = { q: "", mode: "hybrid", supplier: "", currency: "", status: "", date_from: "", date_to: "", min_total: "", max_total: "" };
const MODES = [
  { id: "keyword", hint: "Exact words and numbers" },
  { id: "semantic", hint: "Meaning, over invoice summaries" },
  { id: "hybrid", hint: "Both, fused by rank" },
];

// ts_headline marks hits with <b>; everything else in the snippet is escaped
function Snippet({ text }: { text: string }) {
  const parts = text.split(/(<b>.*?<\/b>)/g);
  return <>{parts.map((p, i) => (p.startsWith("<b>") ? <mark key={i}>{p.slice(3, -4)}</mark> : <span key={i}>{p}</span>))}</>;
}

export default function Search() {
  const [f, setF] = useState<F>(BLANK);
  const [res, setRes] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [more, setMore] = useState(false);

  const run = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    setErr(null);
    const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v.trim()) as [string, string][]);
    try { setRes(await api(`/search?${p}`)); } catch (x: any) { setErr(x.message); } finally { setBusy(false); }
  };

  const inp = (k: keyof F, label: string, type = "text", extra = "") => (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      <input type={type} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} className={clsx(inputCls, "w-full", extra)}
        inputMode={k.endsWith("_total") ? "decimal" : undefined} />
    </label>
  );
  const active = Object.entries(f).filter(([k, v]) => !["q", "mode"].includes(k) && v).length;

  return (
    <>
      <PageTitle title="Search" sub="Keyword search with filters, semantic search over invoice summaries, or both fused by rank." />
      <form onSubmit={run} className="mb-6">
        <Card className="p-3">
          <div className="flex flex-wrap gap-2">
            <div className="relative min-w-0 flex-[1_1_18rem]">
              <SearchIcon size={16} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-faint" aria-hidden />
              <input autoFocus value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} aria-label="Query" type="search" spellCheck={false} autoComplete="off"
                placeholder="INV-1042, a supplier name, or office furniture in March" className={clsx(inputCls, "w-full pl-9")} />
            </div>
            <div className="flex rounded-md bg-[#e7eaef] p-0.5 text-sm max-sm:w-full" role="group" aria-label="Mode">
              {MODES.map((m) => (
                <button type="button" key={m.id} title={m.hint} aria-pressed={f.mode === m.id} onClick={() => setF({ ...f, mode: m.id })}
                  className={clsx("h-8 flex-1 rounded px-3 capitalize transition-colors max-sm:h-10", f.mode === m.id ? "bg-white font-medium text-ink shadow-[0_1px_2px_rgba(16,24,40,0.06)]" : "text-[#3c4350] hover:text-ink")}>
                  {m.id}
                </button>
              ))}
            </div>
            <Button variant="ghost" onClick={() => setMore((v) => !v)} aria-expanded={more} aria-controls="filters">
              <SlidersHorizontal size={15} aria-hidden /> Filters{active ? <span className="num text-xs text-accent-ink">{active}</span> : null}
            </Button>
            <Button type="submit" disabled={busy} className="max-sm:flex-1">{busy && <Spinner />} Search</Button>
          </div>
          {more && (
            <div id="filters" className="mt-3 grid grid-cols-2 gap-3 border-t border-rule pt-3 sm:grid-cols-3 lg:grid-cols-4">
              {inp("supplier", "Supplier")}{inp("currency", "Currency")}
              <label className="flex flex-col gap-1 text-xs text-muted">
                Status
                <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} className={clsx(inputCls, "w-full")}>
                  <option value="">Any status</option>
                  {["auto_validated", "needs_review", "approved"].map((s) => <option key={s} value={s}>{s.replaceAll("_", " ")}</option>)}
                </select>
              </label>
              {inp("date_from", "Dated from", "date")}{inp("date_to", "Dated to", "date")}
              {inp("min_total", "Total at least")}{inp("max_total", "Total at most")}
              <div className="flex items-end">
                <button type="button" onClick={() => setF({ ...BLANK, q: f.q, mode: f.mode })} className="h-9 text-sm text-brand hover:underline disabled:text-faint" disabled={!active}>Clear filters</button>
              </div>
            </div>
          )}
        </Card>
      </form>

      {err && <div className="mb-4"><ErrorNote>{err}</ErrorNote></div>}
      {!res ? (
        <Empty>Search by invoice number, supplier or what was bought. Semantic and hybrid modes also match meaning, not only words.</Empty>
      ) : res.results.length === 0 ? <Empty>No matches. Try another mode or fewer filters.</Empty> : (
        <Card>
          <div className="border-b border-line px-4 py-3 text-sm text-muted"><span className="num text-ink">{res.results.length}</span> {res.results.length === 1 ? "result" : "results"}, {f.mode}</div>
          <ul>
            {res.results.map((r: any) => (
              <li key={r.id} className="border-b border-rule last:border-0">
                <Link href={`/invoices/${r.id}`} className="block px-4 py-3 hover:bg-paper">
                  <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="font-medium text-ink">{r.supplier_name || "Unknown supplier"}</span>
                    <span className="num text-[13px] text-muted">{r.invoice_number || "no number"}</span>
                    <span className="num text-[13px] text-muted">{r.invoice_date}</span>
                    <span className="num ml-auto">{r.total ?? "-"} <span className="text-xs text-muted">{r.currency}</span></span>
                    <Chip value={r.status} />
                  </span>
                  <span className="mt-1.5 block text-[13px] leading-5 text-muted">
                    {r.filename && <span className="text-ink">{r.filename}{r.where ? `, ${r.where}` : ""} · </span>}
                    Matched by {r.matched_by.join(" and ")}{r.snippet && <>: <Snippet text={r.snippet} /></>}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
