"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, type Doc } from "@/lib/api";
import { Card, Chip, Empty, PageTitle, Spinner } from "@/components/ui";

const STATUSES = ["", "queued", "processing", "done", "needs_review", "completed_with_errors", "failed"];

export default function Documents() {
  const [status, setStatus] = useState("");
  const q = useQuery({
    queryKey: ["docs", status],
    queryFn: () => api<{ items: Doc[] }>(`/documents?limit=200${status ? `&status=${status}` : ""}`),
    refetchInterval: 4000,
  });
  return (
    <>
      <PageTitle title="Documents" right={
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-md border border-line bg-white px-3 py-2 text-sm">
          {STATUSES.map((s) => <option key={s} value={s}>{s ? s.replaceAll("_", " ") : "All statuses"}</option>)}
        </select>} />
      {q.isLoading ? <Spinner /> : !q.data?.items.length ? <Empty>No documents yet.</Empty> : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-paper text-left text-muted">
              <tr><th className="px-4 py-2 font-medium">File</th><th className="px-4 py-2 font-medium">Type</th><th className="px-4 py-2 font-medium">Pages</th>
                <th className="px-4 py-2 font-medium">Status</th><th className="px-4 py-2 font-medium">Uploaded</th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {q.data.items.map((d) => (
                <tr key={d.id} className="hover:bg-paper">
                  <td className="px-4 py-2"><Link href={`/documents/${d.id}`} className="text-brand underline">{d.filename}</Link>
                    {d.error_message && <div className="text-xs text-red-700">{d.error_message}</div>}</td>
                  <td className="px-4 py-2">{d.kind}</td>
                  <td className="px-4 py-2 tabular-nums">{d.pages_done}/{d.page_count}{d.pages_failed ? `, ${d.pages_failed} failed` : ""}</td>
                  <td className="px-4 py-2"><Chip value={d.status} /></td>
                  <td className="px-4 py-2 text-muted">{new Date(d.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
