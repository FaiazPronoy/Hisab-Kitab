"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { useState } from "react";
import { api, type Doc } from "@/lib/api";
import { Card, Chip, Empty, ErrorNote, Loading, PageTitle } from "@/components/ui";

const nice = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replaceAll("_", " ");
const STATUSES = ["queued", "processing", "done", "needs_review", "completed_with_errors", "failed"];
const when = (s: string) => new Date(s).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const pages = (d: Doc) => `${d.pages_done}/${d.page_count}${d.pages_failed ? `, ${d.pages_failed} failed` : ""}`;

export default function Documents() {
  const [status, setStatus] = useState("");
  const q = useQuery({
    queryKey: ["docs", status],
    queryFn: () => api<{ items: Doc[] }>(`/documents?limit=200${status ? `&status=${status}` : ""}`),
    refetchInterval: 4000,
  });
  const m = useQuery({ queryKey: ["metrics"], queryFn: () => api<any>("/metrics/summary"), refetchInterval: 10000 });
  const counts: Record<string, number> = m.data?.documents || {};
  const all = Object.values(counts).reduce((a, b) => a + b, 0);
  const tabs = [["", "All", all] as const, ...STATUSES.filter((s) => counts[s]).map((s) => [s, nice(s), counts[s]] as const)];
  if (status && !counts[status]) tabs.push([status, nice(status), 0]);
  const items = q.data?.items || [];

  return (
    <>
      <PageTitle title="Documents" sub="Every uploaded file, newest first, with how far it got through the pipeline." />
      <div className="-mx-4 mb-4 overflow-x-auto px-4 sm:mx-0 sm:px-0" role="tablist" aria-label="Filter by status">
        <div className="flex w-max gap-1 rounded-lg bg-sunken p-1">
          {tabs.map(([v, label, n]) => (
            <button key={v || "all"} type="button" role="tab" aria-selected={status === v} onClick={() => setStatus(v)}
              className={clsx("flex h-8 items-center gap-2 rounded-md px-3 text-sm transition-colors max-sm:h-10",
                status === v ? "bg-surface font-medium text-ink shadow-[0_1px_2px_rgba(16,24,40,0.06)]" : "text-ink2 hover:text-ink")}>
              {label}{m.data && <span className="num text-xs text-muted">{n}</span>}
            </button>
          ))}
        </div>
      </div>

      {q.isLoading ? <Loading rows={6} /> : q.isError ? <ErrorNote retry={() => q.refetch()}>Could not load documents. {(q.error as Error).message}</ErrorNote>
        : !items.length ? <Empty action={<Link href="/" className="text-sm font-medium text-brand hover:underline">Upload files</Link>}>{status ? "No documents with this status." : "No documents yet."}</Empty> : (
        <Card>
          <table className="tbl hidden text-sm sm:table">
            <thead><tr><th>File</th><th>Type</th><th className="r">Pages</th><th>Status</th><th className="r">Uploaded</th></tr></thead>
            <tbody>
              {items.map((d) => (
                <tr key={d.id}>
                  <td className="max-w-[28rem]">
                    <Link href={`/documents/${d.id}`} className="block truncate font-medium text-ink hover:text-brand hover:underline" title={d.filename}>{d.filename}</Link>
                    {d.error_message && <div className="mt-0.5 text-xs text-bad">{d.error_message}</div>}
                  </td>
                  <td className="text-muted">{d.kind}</td>
                  <td className="r num">{pages(d)}</td>
                  <td><Chip value={d.status} /></td>
                  <td className="r whitespace-nowrap text-muted">{when(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="sm:hidden">
            {items.map((d) => (
              <li key={d.id} className="border-b border-rule last:border-0">
                <Link href={`/documents/${d.id}`} className="block px-4 py-3 active:bg-paper">
                  <span className="flex items-center gap-3">
                    <span className="min-w-0 flex-1 truncate font-medium">{d.filename}</span>
                    <Chip value={d.status} />
                  </span>
                  <span className="mt-1 block text-[13px] text-muted">{d.kind} · <span className="num">{pages(d)}</span> pages · {when(d.created_at)}</span>
                  {d.error_message && <span className="mt-0.5 block text-xs text-bad">{d.error_message}</span>}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
