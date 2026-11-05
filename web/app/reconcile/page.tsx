"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, type Doc } from "@/lib/api";
import { Button, Card, Chip, Empty, PageTitle, Spinner } from "@/components/ui";

function Ref({ r }: { r: any }) {
  if (!r?.invoice_id) return null;
  return <Link className="text-brand underline" href={`/invoices/${r.invoice_id}`}>{r.sheet ? `${r.sheet} row ${r.row}` : `page ${r.page ?? 1}`}</Link>;
}

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

  const items = run ? [...run.items.filter((i: any) => i.category !== "matched"), ...run.items.filter((i: any) => i.category === "matched")] : [];
  return (
    <>
      <PageTitle title="Reconciliation" sub="Match an uploaded ledger or payment sheet against the extracted invoices." />
      <div className="mb-6 flex flex-wrap gap-2">
        <select value={ledger} onChange={(e) => setLedger(e.target.value)} aria-label="Ledger" className="rounded-md border border-line bg-white px-3 py-2 text-sm">
          <option value="">Choose a ledger spreadsheet</option>
          {(sheets.data?.items || []).map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
        </select>
        <Button onClick={go} disabled={!ledger || busy}>{busy && <Spinner />} Run</Button>
      </div>
      {err && <p className="text-sm text-red-700">{err}</p>}
      {!run ? <Empty>Pick a spreadsheet and run a reconciliation.</Empty> : (
        <>
          <div className="mb-4 flex flex-wrap gap-2">
            {Object.entries(run.summary).map(([k, v]) => (
              <span key={k} className="rounded-md border border-line bg-white px-3 py-1.5 text-sm">{k.replaceAll("_", " ")}: <b>{v as number}</b></span>
            ))}
          </div>
          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-paper text-left text-muted"><tr>
                <th className="px-4 py-2 font-medium">Result</th><th className="px-4 py-2 font-medium">Field</th><th className="px-4 py-2 font-medium">Invoice</th>
                <th className="px-4 py-2 font-medium">Ledger</th><th className="px-4 py-2 font-medium">Difference</th><th className="px-4 py-2 font-medium">Sources</th></tr></thead>
              <tbody className="divide-y divide-line">
                {items.map((i: any, k: number) => (
                  <tr key={k}>
                    <td className="px-4 py-2"><Chip value={i.category === "matched" ? "matched" : i.severity} /> {i.category.replaceAll("_", " ")}</td>
                    <td className="px-4 py-2">{i.field}</td>
                    <td className="px-4 py-2 tabular-nums">{i.left_value}</td>
                    <td className="px-4 py-2 tabular-nums">{i.right_value}</td>
                    <td className="px-4 py-2 tabular-nums">{i.delta}</td>
                    <td className="space-x-2 px-4 py-2"><Ref r={i.left_ref} /> <Ref r={i.right_ref} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </>
  );
}
