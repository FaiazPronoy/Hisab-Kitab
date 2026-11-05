"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, PageTitle, Spinner } from "@/components/ui";

const pct = (v: number | null) => (v == null ? "n/a" : `${(v * 100).toFixed(1)}%`);

export default function Metrics() {
  const q = useQuery({ queryKey: ["metrics"], queryFn: () => api<any>("/metrics/summary"), refetchInterval: 5000 });
  if (q.isLoading || !q.data) return <Spinner />;
  const m = q.data;
  const tiles: [string, string | number][] = [
    ["Success rate", pct(m.success_rate)], ["Failure rate", pct(m.failure_rate)], ["Completed with errors", pct(m.completed_with_errors_rate)],
    ["Needs review", m.needs_review], ["LLM calls", m.llm.calls], ["LLM cost", `$${m.llm.cost_usd}`],
  ];
  return (
    <>
      <PageTitle title="Metrics" sub="Live counts from this database. The offline evaluation is in EVALUATION.md." />
      <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {tiles.map(([k, v]) => (
          <Card key={k} className="p-4"><div className="text-xs text-muted">{k}</div><div className="mt-1 text-xl font-semibold tabular-nums">{v}</div></Card>
        ))}
      </div>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Time per page</h2>
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-paper text-left text-muted"><tr>
            <th className="px-4 py-2 font-medium">Read by</th><th className="px-4 py-2 font-medium">Pages</th>
            <th className="px-4 py-2 font-medium">p50</th><th className="px-4 py-2 font-medium">p95</th></tr></thead>
          <tbody className="divide-y divide-line">
            {Object.entries(m.page_timing_ms).map(([k, v]: [string, any]) => (
              <tr key={k}><td className="px-4 py-2">{k.replace("_", " ")}</td><td className="px-4 py-2 tabular-nums">{v.n}</td>
                <td className="px-4 py-2 tabular-nums">{Math.round(v.p50)} ms</td><td className="px-4 py-2 tabular-nums">{Math.round(v.p95)} ms</td></tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}
