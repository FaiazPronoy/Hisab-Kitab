"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "@/lib/api";
import { ErrorNote, Figures, Loading, PageTitle, Panel } from "@/components/ui";

const pct = (v: number | null | undefined) => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
const DOC_ORDER = ["done", "needs_review", "completed_with_errors", "failed", "rejected", "processing", "finalizing", "queued"];
const INV_ORDER = ["auto_validated", "needs_review", "approved"];
const READ_BY: Record<string, string> = { text_layer: "Text layer", ocr: "OCR", ocr_heavy: "OCR, heavy", vision: "Vision model" };

function Bars({ data, order, signal }: { data: Record<string, number>; order: string[]; signal: Record<string, "warn" | "bad"> }) {
  const keys = [...order.filter((k) => k in data), ...Object.keys(data).filter((k) => !order.includes(k))];
  const max = Math.max(1, ...keys.map((k) => data[k]));
  if (!keys.length) return <p className="px-4 py-4 text-sm text-muted">Nothing processed yet.</p>;
  return (
    <ul className="space-y-3 px-4 py-4">
      {keys.map((k) => (
        <li key={k} className="grid grid-cols-[8.5rem_minmax(0,1fr)_3rem] items-center gap-3 text-sm max-sm:grid-cols-[7rem_minmax(0,1fr)_2.5rem]">
          <span className="truncate text-ink2">{k.charAt(0).toUpperCase() + k.slice(1).replaceAll("_", " ")}</span>
          <span className="h-2 rounded-sm bg-rule">
            <span className={clsx("block h-2 rounded-sm", signal[k] === "bad" ? "bg-[#c4242a]" : signal[k] === "warn" ? "bg-accent" : "bg-brand")}
              style={{ width: `${Math.max(data[k] ? 2 : 0, (data[k] / max) * 100)}%` }} />
          </span>
          <span className="num text-right">{data[k]}</span>
        </li>
      ))}
    </ul>
  );
}

export default function Metrics() {
  const q = useQuery({ queryKey: ["metrics"], queryFn: () => api<any>("/metrics/summary"), refetchInterval: 5000 });
  const head = <PageTitle title="Metrics" sub="Live counts from this database. The offline evaluation is in EVALUATION.md." />;
  if (q.isLoading) return <>{head}<Loading rows={3} /></>;
  if (q.isError || !q.data) return <>{head}<ErrorNote retry={() => q.refetch()}>Could not load metrics.</ErrorNote></>;
  const m = q.data;
  const docs: Record<string, number> = m.documents || {};
  const invs: Record<string, number> = m.invoices || {};
  const nDocs = Object.values(docs).reduce((a, b) => a + b, 0);
  const nInv = Object.values(invs).reduce((a, b) => a + b, 0);
  const timing = Object.entries(m.page_timing_ms || {}) as [string, { n: number; p50: number; p95: number }][];
  const slowest = Math.max(1, ...timing.map(([, v]) => v.p95));

  return (
    <>
      {head}
      <Figures items={[
        { label: "Documents", value: nDocs, note: `${nInv} invoices found` },
        { label: "Processed cleanly", value: pct(m.success_rate), note: "done or sent to review" },
        { label: "Failed", value: pct(m.failure_rate), note: `${docs.failed || 0} failed, ${docs.completed_with_errors || 0} partly read` },
        { label: "Waiting for review", value: m.needs_review, note: "invoices" },
        { label: "Approved, not paid", value: m.approved_unpaid ?? 0, note: m.ledger_rows || m.po_rows ? `${m.ledger_rows || 0} ledger rows, ${m.po_rows || 0} purchase orders kept apart` : "invoices" },
        { label: "LLM cost", value: `$${Number(m.llm.cost_usd).toFixed(2)}`, note: `${m.llm.calls} calls, ${Number(m.llm.tokens).toLocaleString()} tokens` },
      ]} />

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Panel title="Documents by status" meta={`${nDocs} total`}>
          <Bars data={docs} order={DOC_ORDER} signal={{ needs_review: "warn", completed_with_errors: "warn", failed: "bad", rejected: "bad" }} />
        </Panel>
        <Panel title="Invoices by status" meta={`${nInv} total`}>
          <Bars data={invs} order={INV_ORDER} signal={{ needs_review: "warn" }} />
        </Panel>
      </div>

      <Panel title="Time per page" meta="pages read successfully" className="mt-6">
        {timing.length === 0 ? <p className="px-4 py-4 text-sm text-muted">No pages timed yet.</p> : (
          <div className="overflow-x-auto">
            <table className="tbl text-sm">
              <thead><tr><th>Read by</th><th className="r">Pages</th><th className="r">p50</th><th className="r">p95</th><th className="w-[40%] max-sm:hidden">p95 against the slowest source</th></tr></thead>
              <tbody>
                {timing.map(([k, v]) => (
                  <tr key={k}>
                    <td>{READ_BY[k] || k.replaceAll("_", " ")}</td>
                    <td className="r num">{v.n}</td>
                    <td className="r num whitespace-nowrap">{Math.round(v.p50).toLocaleString()} <span className="text-xs text-muted">ms</span></td>
                    <td className="r num whitespace-nowrap">{Math.round(v.p95).toLocaleString()} <span className="text-xs text-muted">ms</span></td>
                    <td className="max-sm:hidden"><span className="block h-2 rounded-sm bg-rule"><span className="block h-2 rounded-sm bg-brand" style={{ width: `${(v.p95 / slowest) * 100}%` }} /></span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}
