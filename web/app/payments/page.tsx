"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Download } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useSession } from "@/components/Shell";
import { Button, Card, Empty, ErrorNote, Loading, PageTitle, Panel, Spinner, inputCls } from "@/components/ui";
import { api, raw } from "@/lib/api";

type Ready = { id: string; supplier_name: string | null; invoice_number: string | null; total: string | null; currency: string | null;
  due_date: string | null; account: string; iban: boolean; approved_by: string | null };

const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

async function download(id: string, filename: string) {
  const r = await raw(`/payments/batches/${id}/file`);
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function Payments() {
  const session = useSession();
  const qc = useQueryClient();
  const ready = useQuery({ queryKey: ["pay-ready"], queryFn: () => api<Ready[]>("/payments/ready") });
  const batches = useQuery({ queryKey: ["pay-batches"], queryFn: () => api<any[]>("/payments/batches") });
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [format, setFormat] = useState("pain001");
  const [when, setWhen] = useState(today());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);

  const rows = ready.data || [];
  const chosen = rows.filter((r) => picked.has(r.id));
  const sums = useMemo(() => {
    const out: Record<string, number> = {};
    for (const r of chosen) if (r.currency && r.total) out[r.currency] = (out[r.currency] || 0) + Math.abs(Number(r.total));
    return out;
  }, [chosen]);
  const approver = session?.role === "approver";
  const blocked = format === "pain001" ? chosen.filter((r) => !r.iban) : chosen.filter((r) => !r.account);

  const toggle = (id: string) => setPicked((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const all = rows.length > 0 && chosen.length === rows.length;

  const create = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const b = await api<any>("/payments/batches", { method: "POST", body: JSON.stringify({ invoice_ids: chosen.map((r) => r.id), format, execution_date: when }) });
      setPicked(new Set());
      setMsg({ text: `${b.filename} created with ${b.invoice_count} ${b.invoice_count === 1 ? "payment" : "payments"}.` });
      try {
        await download(b.id, b.filename);
      } catch {
        setMsg({ text: `${b.filename} was created but did not download. Download it from the list below.`, bad: true });
      }
    } catch (e: any) {
      setMsg({ text: e.message, bad: true });
    } finally {
      setBusy(false);
      qc.invalidateQueries({ queryKey: ["pay-ready"] });
      qc.invalidateQueries({ queryKey: ["pay-batches"] });
      qc.invalidateQueries({ queryKey: ["metrics"] });
    }
  };

  return (
    <>
      <PageTitle title="Payments" sub="Approved invoices waiting to be paid, earliest due first. A payment file locks its invoices so nothing is paid twice." />
      {msg && <p className={`mb-4 rounded-lg border px-4 py-3 text-sm ${msg.bad ? "border-badline bg-badwash text-bad" : "border-line bg-goodwash text-good"}`} role="status">{msg.text}</p>}
      {ready.isLoading ? <Loading rows={5} /> : ready.isError ? <ErrorNote retry={() => ready.refetch()}>Could not load approved invoices.</ErrorNote>
        : rows.length === 0 ? <Empty action={<Link href="/review" className="text-sm font-medium text-brand hover:underline">Open the review queue</Link>}>Nothing approved is waiting for payment.</Empty> : (
        <Card>
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={all} onChange={() => setPicked(all ? new Set() : new Set(rows.map((r) => r.id)))} className="h-4 w-4 accent-[var(--c-brand)]" />
              {chosen.length ? <span><span className="num">{chosen.length}</span> selected</span> : <span className="text-muted">Select all</span>}
            </label>
            {Object.entries(sums).map(([c, v]) => <span key={c} className="num text-sm">{v.toFixed(2)} <span className="text-xs text-muted">{c}</span></span>)}
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <select value={format} onChange={(e) => setFormat(e.target.value)} aria-label="File format" className={inputCls}>
                <option value="pain001">ISO 20022 pain.001 (XML)</option>
                <option value="csv">CSV for bank upload</option>
              </select>
              <input type="date" value={when} min={today()} onChange={(e) => setWhen(e.target.value)} aria-label="Payment date" className={inputCls} />
              <Button onClick={create} disabled={!approver || busy || !chosen.length || blocked.length > 0}
                title={!approver ? "Only an approver can create a payment file" : undefined}>
                {busy && <Spinner />} Create payment file
              </Button>
            </div>
          </div>
          {(!approver || blocked.length > 0) && (
            <div className="border-b border-line px-4 py-2.5 text-sm">
              {!approver && <p className="text-muted">You are signed in as a clerk. An approver creates payment files.</p>}
              {blocked.length > 0 && <p className="text-accent-ink">{blocked.length} selected {blocked.length === 1 ? "invoice has" : "invoices have"} {format === "pain001" ? "no IBAN; use the CSV format or fix the account on the invoice" : "no bank account"}.</p>}
            </div>
          )}
          <ul className="md:hidden">
            {rows.map((r) => (
              <li key={r.id} className={clsx("flex items-start gap-3 border-b border-rule px-4 py-3 last:border-0", picked.has(r.id) && "bg-infowash")}>
                <input type="checkbox" checked={picked.has(r.id)} onChange={() => toggle(r.id)} aria-label={`Pay ${r.supplier_name} ${r.invoice_number}`} className="mt-1 h-5 w-5 accent-[var(--c-brand)]" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-3">
                    <Link href={`/invoices/${r.id}`} className="min-w-0 flex-1 truncate font-medium">{r.supplier_name || "Unknown supplier"}</Link>
                    <span className="num shrink-0">{r.total ?? "-"} <span className="text-xs text-muted">{r.currency}</span></span>
                  </span>
                  <span className="mt-0.5 block text-[13px] text-muted"><span className="num">{r.invoice_number || "-"}</span> · due <span className="num">{r.due_date || "-"}</span> · <span className="num">{r.account || "no account"}</span></span>
                </span>
              </li>
            ))}
          </ul>
          <div className="hidden overflow-x-auto md:block">
            <table className="tbl text-sm">
              <thead><tr><th className="w-10"><span className="sr-only">Select</span></th><th>Supplier</th><th>Invoice</th><th>Due</th><th>Account</th><th>Approved by</th><th className="r">Amount</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={clsx(picked.has(r.id) && "[&>td]:bg-infowash")}>
                    <td><input type="checkbox" checked={picked.has(r.id)} onChange={() => toggle(r.id)} aria-label={`Pay ${r.supplier_name} ${r.invoice_number}`} className="h-4 w-4 accent-[var(--c-brand)]" /></td>
                    <td><Link href={`/invoices/${r.id}`} className="font-medium hover:text-brand hover:underline">{r.supplier_name || "Unknown supplier"}</Link></td>
                    <td className="num text-[13px]">{r.invoice_number || "-"}</td>
                    <td className="num whitespace-nowrap text-[13px]">{r.due_date || "-"}</td>
                    <td className="num text-[13px]">{r.account || <span className="font-sans text-accent-ink">none</span>}{r.account && !r.iban && <span className="ml-1 font-sans text-xs text-muted">not IBAN</span>}</td>
                    <td className="text-muted">{r.approved_by || "-"}</td>
                    <td className="r num whitespace-nowrap">{r.total ?? "-"} <span className="text-xs text-muted">{r.currency}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Panel title="Payment files" meta={batches.data?.length ? `${batches.data.length}` : undefined} className="mt-6">
        {!batches.data?.length ? <p className="px-4 py-4 text-sm text-muted">No payment files yet.</p> : (
          <ul>
            {batches.data.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-rule px-4 py-3 text-sm last:border-0">
                <span className="num min-w-0 flex-1 truncate">{b.filename}</span>
                <span className="text-muted">{b.invoice_count} {b.invoice_count === 1 ? "payment" : "payments"}</span>
                <span className="num">{Object.entries(b.totals).map(([c, v]) => `${v} ${c}`).join(", ")}</span>
                <span className="text-muted">{b.created_by}, {new Date(b.created_at).toLocaleString()}</span>
                <Button variant="ghost" onClick={() => download(b.id, b.filename)} aria-label={`Download ${b.filename}`}><Download size={15} aria-hidden /> Download</Button>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}
