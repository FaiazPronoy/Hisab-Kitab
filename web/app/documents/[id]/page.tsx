"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { use } from "react";
import { api, type Doc } from "@/lib/api";
import { Chip, Empty, ErrorNote, Loading, PageTitle, Panel } from "@/components/ui";

const READ_BY: Record<string, string> = { text_layer: "text layer", ocr: "OCR", ocr_heavy: "OCR, heavy", vision: "vision model" };

export default function DocumentDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const doc = useQuery({ queryKey: ["doc", id], queryFn: () => api<Doc>(`/documents/${id}`), refetchInterval: 3000 });
  const hist = useQuery({ queryKey: ["hist", id], queryFn: () => api<any[]>(`/documents/${id}/history`), refetchInterval: 5000 });
  const back = <Link href="/documents" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-ink"><ChevronLeft size={16} aria-hidden /> Documents</Link>;
  if (doc.isLoading) return <>{back}<Loading rows={5} /></>;
  if (doc.isError && !doc.data) return <>{back}<ErrorNote retry={() => doc.refetch()}>Could not load this document. {(doc.error as Error).message}</ErrorNote></>;
  const d = doc.data;
  if (!d) return <>{back}<Empty>Document not found.</Empty></>;
  const unit = d.kind === "sheet" ? "sheets" : "pages";
  const events = hist.data || [];

  return (
    <>
      {back}
      <PageTitle title={<span className="break-all">{d.filename}</span>}
        sub={<>{d.kind}, <span className="num">{d.page_count}</span> {unit}{d.pages_failed ? <>, <span className="num">{d.pages_failed}</span> failed</> : null}. Uploaded {new Date(d.created_at).toLocaleString()}.</>}
        right={<Chip value={d.status} />} />
      {d.error_message && <div className="mb-6"><ErrorNote><b className="font-semibold">{d.error_code}</b>: {d.error_message}</ErrorNote></div>}

      <Panel title="Invoices found" meta={d.invoices?.length ? `${d.invoices.length}` : undefined} className="mb-6">
        {!d.invoices?.length ? <p className="px-4 py-4 text-sm text-muted">{["queued", "processing", "finalizing"].includes(d.status) ? "Still reading this file." : "No invoices extracted."}</p> : (
          <div className="overflow-x-auto">
            <table className="tbl text-sm">
              <thead><tr><th>Supplier</th><th>Number</th><th>Date</th><th className="r">Total</th><th>Where</th><th>Status</th></tr></thead>
              <tbody>
                {d.invoices.map((i) => (
                  <tr key={i.id}>
                    <td><Link className="font-medium text-ink hover:text-brand hover:underline" href={`/invoices/${i.id}`}>{i.supplier_name || "Unknown supplier"}</Link></td>
                    <td className="num text-[13px]">{i.invoice_number || <span className="font-sans text-muted">no number</span>}</td>
                    <td className="num whitespace-nowrap text-[13px]">{i.invoice_date || "-"}</td>
                    <td className="r num whitespace-nowrap">{i.total ?? "-"} <span className="text-xs text-muted">{i.currency}</span></td>
                    <td className="whitespace-nowrap text-muted">{i.sheet_name ? `${i.sheet_name}${i.row_index ? `, row ${i.row_index}` : ""}` : `page ${i.page_start}`}</td>
                    <td><Chip value={i.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {d.pages && d.pages.length > 0 ? (
          <Panel title="Pages" meta={`${d.pages_done} of ${d.page_count} read`}>
            <div className="flex flex-wrap gap-1 border-b border-rule px-4 py-3" aria-hidden>
              {d.pages.map((p) => (
                <span key={p.page_no} title={`Page ${p.page_no}: ${p.status}`}
                  className={clsx("h-3 w-3 rounded-[2px]", p.status === "done" ? (p.source === "text_layer" ? "bg-brand" : "bg-[#6b86ad]") : p.status === "failed" ? "bg-[#c4242a]" : "bg-rule")} />
              ))}
            </div>
            <div className="max-h-80 overflow-auto">
              <table className="tbl text-sm">
                <thead className="sticky top-0 bg-white"><tr><th className="r">Page</th><th>Read by</th><th>Why</th><th className="r">OCR conf.</th><th>Status</th></tr></thead>
                <tbody>
                  {d.pages.map((p) => (
                    <tr key={p.page_no}>
                      <td className="r num">{p.page_no}</td>
                      <td className="whitespace-nowrap">{p.source ? READ_BY[p.source] || p.source.replaceAll("_", " ") : "-"}</td>
                      <td className="text-muted">{p.reason || "-"}</td>
                      <td className="r num">{p.ocr_conf != null ? p.ocr_conf.toFixed(2) : "-"}</td>
                      <td><Chip value={p.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        ) : <div className="hidden lg:block" />}

        <Panel title="Processing history" meta={events.length ? `${events.length} events` : undefined} className={clsx(!(d.pages && d.pages.length) && "lg:col-span-2")}>
          {hist.isError ? <p className="px-4 py-4 text-sm text-[#8a1c1f]">Could not load the history.</p> : !events.length ? <p className="px-4 py-4 text-sm text-muted">No events yet.</p> : (
            <ol className="max-h-[22rem] overflow-auto px-4 py-2">
              {events.map((e, k) => (
                <li key={k} className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-3 border-b border-rule py-2 text-sm last:border-0">
                  <span className="num pt-px text-xs text-muted">{new Date(e.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}</span>
                  <span className="min-w-0">
                    <span className="font-medium">{e.stage}</span>{" "}
                    <span className={clsx(e.status === "failed" || e.status === "error" ? "text-[#8a1c1f]" : "text-muted")}>{e.status}</span>
                    {(e.page_no || e.message || e.duration_ms) && (
                      <span className="block break-words text-[13px] text-muted">
                        {e.page_no ? `page ${e.page_no} ` : ""}{e.message}{e.duration_ms ? <> <span className="num">({e.duration_ms} ms)</span></> : null}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Panel>
      </div>
    </>
  );
}
