"use client";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { Button, Card, Chip, Empty, PageTitle, Spinner } from "@/components/ui";

type F = { q: string; mode: string; supplier: string; currency: string; status: string; date_from: string; date_to: string; min_total: string; max_total: string };

// ts_headline marks hits with <b>; everything else in the snippet is escaped
function Snippet({ text }: { text: string }) {
  const parts = text.split(/(<b>.*?<\/b>)/g);
  return <>{parts.map((p, i) => (p.startsWith("<b>") ? <mark key={i}>{p.slice(3, -4)}</mark> : <span key={i}>{p}</span>))}</>;
}

export default function Search() {
  const [f, setF] = useState<F>({ q: "", mode: "hybrid", supplier: "", currency: "", status: "", date_from: "", date_to: "", min_total: "", max_total: "" });
  const [res, setRes] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    setErr(null);
    const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v) as [string, string][]);
    try { setRes(await api(`/search?${p}`)); } catch (x: any) { setErr(x.message); } finally { setBusy(false); }
  };

  const inp = (k: keyof F, ph: string, type = "text") => (
    <input type={type} placeholder={ph} aria-label={ph} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })}
      className="rounded-md border border-line bg-white px-3 py-2 text-sm" />
  );

  return (
    <>
      <PageTitle title="Search" sub="Keyword search with filters, semantic search over invoice summaries, or both fused by rank." />
      <form onSubmit={run} className="mb-6 space-y-3">
        <div className="flex flex-wrap gap-2">
          <input autoFocus value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} aria-label="Query"
            placeholder="INV-1042, a supplier name, or office furniture in March"
            className="min-w-72 flex-1 rounded-md border border-line bg-white px-3 py-2 text-sm" />
          <div className="flex overflow-hidden rounded-md border border-line bg-white text-sm" role="group" aria-label="Mode">
            {["keyword", "semantic", "hybrid"].map((m) => (
              <button type="button" key={m} onClick={() => setF({ ...f, mode: m })} className={`px-3 py-2 ${f.mode === m ? "bg-brand text-white" : ""}`}>{m}</button>
            ))}
          </div>
          <Button type="submit" disabled={busy}>{busy && <Spinner />} Search</Button>
        </div>
        <div className="flex flex-wrap gap-2">
          {inp("supplier", "Supplier")}{inp("currency", "Currency")}
          <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} aria-label="Status" className="rounded-md border border-line bg-white px-3 py-2 text-sm">
            <option value="">Any status</option>
            {["auto_validated", "needs_review", "approved"].map((s) => <option key={s} value={s}>{s.replaceAll("_", " ")}</option>)}
          </select>
          {inp("date_from", "From", "date")}{inp("date_to", "To", "date")}{inp("min_total", "Min total")}{inp("max_total", "Max total")}
        </div>
      </form>
      {err && <p className="text-sm text-red-700">{err}</p>}
      {res && (res.results.length === 0 ? <Empty>No matches.</Empty> : (
        <Card className="divide-y divide-line">
          {res.results.map((r: any) => (
            <Link key={r.id} href={`/invoices/${r.id}`} className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-paper">
              <span className="font-medium text-brand">{r.invoice_number || "(no number)"}</span>
              <span>{r.supplier_name}</span>
              <span className="text-muted">{r.invoice_date}</span>
              <span className="ml-auto tabular-nums">{r.total} {r.currency}</span>
              <Chip value={r.status} />
              <span className="w-full text-xs text-muted">
                matched by {r.matched_by.join(" and ")}{r.snippet && <>: <Snippet text={r.snippet} /></>}
              </span>
            </Link>
          ))}
        </Card>
      ))}
    </>
  );
}
