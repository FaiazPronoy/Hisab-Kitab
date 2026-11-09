"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, type Doc } from "@/lib/api";
import { Button, Card, Chip, Empty, ErrorNote, PageTitle, Spinner, inputCls } from "@/components/ui";

function Ref({ r }: { r: any }) {
  if (!r?.invoice_id) return null;
  return <Link className="whitespace-nowrap text-brand hover:underline" href={`/invoices/${r.invoice_id}`}>{r.sheet ? `${r.sheet} row ${r.row}` : `page ${r.page ?? 1}`}</Link>;
}

const label = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replaceAll("_", " ");
const money = (v: any) => (v == null ? "-" : /^-?\d+\.\d+$/.test(String(v)) ? Number(v).toFixed(2) : String(v));
const COLS: Record<number, string> = { 1: "sm:grid-cols-1", 2: "sm:grid-cols-2", 3: "sm:grid-cols-3", 4: "sm:grid-cols-4", 5: "sm:grid-cols-5", 6: "sm:grid-cols-6" };

export default function Reconcile() {
  const sheets = useQuery({ queryKey: ["sheets"], queryFn: () => api<{ items: Doc[] }>("/documents?kind=sheet&limit=100") });
  const [ledger, setLedger] = useState("");
  const [run, setRun] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const go = async () => {
    setBusy(true);
    setErr(null);
    try { setRun(await api("/reconciliations", { method: "POST", body: JSON.stringify({ kind: "ledger", ledger_document_id: ledger }) })); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  const items: any[] = run ? [...run.items.filter((i: any) => i.category !== "matched"), ...run.items.filter((i: any) => i.category === "matched")] : [];
  const summary = run ? (Object.entries(run.summary) as [string, number][]) : [];
  const open = items.filter((i) => i.category !== "matched").length;
  const options = sheets.data?.items || [];

  return (
    <>
      <PageTitle title="Reconciliation" sub="Match an uploaded ledger or payment sheet against the extracted invoices." />
      <Card className="mb-6 flex flex-wrap items-center gap-3 p-3">
        <label htmlFor="ledger" className="pl-1 text-sm text-muted">Ledger</label>
        <select id="ledger" value={ledger} onChange={(e) => setLedger(e.target.value)} className={`${inputCls} min-w-0 flex-1 sm:max-w-sm`} disabled={sheets.isLoading}>
          <option value="">{sheets.isLoading ? "Loading spreadsheets…" : options.length ? "Choose a ledger spreadsheet" : "No spreadsheets uploaded"}</option>
          {options.map((d) => <option key={d.id} value={d.id}>{d.filename}{d.role === "ledger" ? " (payment ledger)" : d.role === "invoices" ? " (invoice list)" : ""}</option>)}
        </select>
        <Button onClick={go} disabled={!ledger || busy} className="max-sm:w-full">{busy && <Spinner />} {busy ? "Matching…" : "Run reconciliation"}</Button>
      </Card>
      {err && <div className="mb-4"><ErrorNote>{err}</ErrorNote></div>}
      {sheets.isError && <div className="mb-4"><ErrorNote retry={() => sheets.refetch()}>Could not load the spreadsheets.</ErrorNote></div>}

      {!run ? (
        <Empty action={options.length ? null : <Link href="/" className="text-sm font-medium text-brand hover:underline">Upload a ledger</Link>}>
          {options.length ? "Pick a spreadsheet and run a reconciliation. Mismatches are listed first." : "Upload a ledger spreadsheet (XLSX, XLS or CSV) to reconcile it."}
        </Empty>
      ) : (
        <>
          <p className="mb-3 text-sm text-muted">
            {open === 0 ? "Every ledger row matched an invoice." : <><span className="num font-medium text-accent-ink">{open}</span> {open === 1 ? "row needs" : "rows need"} a look, listed first.</>}
          </p>
          <dl className={`mb-6 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line ${COLS[Math.min(summary.length, 6)] || "sm:grid-cols-3"}`}>
            {summary.map(([k, v]) => (
              <div key={k} className="bg-surface px-4 py-3">
                <dt className="truncate text-xs text-muted">{label(k)}</dt>
                <dd className={`num mt-0.5 text-xl ${v && k !== "matched" && !k.includes("total") ? "text-accent-ink" : "text-ink"}`}>{v}</dd>
              </div>
            ))}
            {summary.length % 2 === 1 && <div className="bg-surface sm:hidden" aria-hidden />}
          </dl>
          <Card>
            <div className="overflow-x-auto">
              <table className="tbl hidden text-sm md:table">
                <thead><tr><th>Result</th><th>Field</th><th className="r">Invoice</th><th className="r">Ledger</th><th className="r">Difference</th><th>Sources</th></tr></thead>
                <tbody>
                  {items.map((i, k) => (
                    <tr key={k}>
                      <td><span className="flex flex-wrap items-center gap-2"><Chip value={i.category === "matched" ? "matched" : i.severity} /><span className="text-ink2">{label(i.category)}</span></span></td>
                      <td className="text-muted">{i.field ? i.field.replaceAll("_", " ") : "-"}</td>
                      <td className="r num">{money(i.left_value)}</td>
                      <td className="r num">{money(i.right_value)}</td>
                      <td className={`r num ${i.delta && Number(i.delta) !== 0 ? "text-accent-ink" : "text-muted"}`}>{money(i.delta)}</td>
                      <td><span className="flex flex-wrap gap-x-3"><Ref r={i.left_ref} /><Ref r={i.right_ref} /></span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="md:hidden">
              {items.map((i, k) => (
                <li key={k} className="border-b border-rule px-4 py-3 last:border-0">
                  <div className="flex items-center gap-2">
                    <Chip value={i.category === "matched" ? "matched" : i.severity} />
                    <span className="min-w-0 flex-1 truncate">{label(i.category)}</span>
                    {i.delta && <span className="num text-sm text-accent-ink">{money(i.delta)}</span>}
                  </div>
                  <div className="mt-1 text-[13px] text-muted">
                    {i.field ? `${i.field.replaceAll("_", " ")}: ` : ""}<span className="num">{money(i.left_value)}</span> against <span className="num">{money(i.right_value)}</span>
                  </div>
                  <div className="mt-1 flex gap-3 text-[13px]"><Ref r={i.left_ref} /><Ref r={i.right_ref} /></div>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </>
  );
}
