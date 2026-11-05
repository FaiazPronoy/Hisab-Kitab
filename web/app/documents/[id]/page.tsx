"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";
import { api, type Doc } from "@/lib/api";
import { Card, Chip, Empty, PageTitle, Spinner } from "@/components/ui";

export default function DocumentDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const doc = useQuery({ queryKey: ["doc", id], queryFn: () => api<Doc>(`/documents/${id}`), refetchInterval: 3000 });
  const hist = useQuery({ queryKey: ["hist", id], queryFn: () => api<any[]>(`/documents/${id}/history`) });
  if (doc.isLoading) return <Spinner />;
  const d = doc.data;
  if (!d) return <Empty>Document not found.</Empty>;
  return (
    <>
      <PageTitle title={d.filename} sub={`${d.kind}, ${d.page_count} ${d.kind === "sheet" ? "sheets" : "pages"}`} right={<Chip value={d.status} />} />
      {d.error_message && <Card className="mb-6 border-red-200 bg-red-50 p-4 text-sm text-red-800"><b>{d.error_code}</b>: {d.error_message}</Card>}
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Invoices found</h2>
      {!d.invoices?.length ? <Empty>No invoices extracted.</Empty> : (
        <Card className="mb-8 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-paper text-left text-muted"><tr>
              <th className="px-4 py-2 font-medium">Number</th><th className="px-4 py-2 font-medium">Supplier</th><th className="px-4 py-2 font-medium">Date</th>
              <th className="px-4 py-2 text-right font-medium">Total</th><th className="px-4 py-2 font-medium">Where</th><th className="px-4 py-2 font-medium">Status</th></tr></thead>
            <tbody className="divide-y divide-line">
              {d.invoices.map((i) => (
                <tr key={i.id} className="hover:bg-paper">
                  <td className="px-4 py-2"><Link className="text-brand underline" href={`/invoices/${i.id}`}>{i.invoice_number || "(no number)"}</Link></td>
                  <td className="px-4 py-2">{i.supplier_name}</td><td className="px-4 py-2">{i.invoice_date}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{i.total} {i.currency}</td>
                  <td className="px-4 py-2 text-muted">{i.sheet_name ? `${i.sheet_name}${i.row_index ? `, row ${i.row_index}` : ""}` : `page ${i.page_start}`}</td>
                  <td className="px-4 py-2"><Chip value={i.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {d.pages && d.pages.length > 0 && (
        <>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Pages</h2>
          <Card className="mb-8 max-h-80 overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-paper text-left text-muted"><tr><th className="px-4 py-2 font-medium">Page</th><th className="px-4 py-2 font-medium">Read by</th>
                <th className="px-4 py-2 font-medium">Why</th><th className="px-4 py-2 font-medium">OCR confidence</th><th className="px-4 py-2 font-medium">Status</th></tr></thead>
              <tbody className="divide-y divide-line">
                {d.pages.map((p) => (
                  <tr key={p.page_no}><td className="px-4 py-1.5 tabular-nums">{p.page_no}</td><td className="px-4 py-1.5">{p.source?.replace("_", " ")}</td>
                    <td className="px-4 py-1.5 text-muted">{p.reason}</td><td className="px-4 py-1.5 tabular-nums">{p.ocr_conf != null ? p.ocr_conf.toFixed(2) : ""}</td>
                    <td className="px-4 py-1.5"><Chip value={p.status} /></td></tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Processing history</h2>
      <Card className="max-h-72 overflow-auto p-4 text-sm">
        <ol className="space-y-1">
          {(hist.data || []).map((e, k) => (
            <li key={k} className="flex gap-3"><span className="w-40 shrink-0 text-muted">{new Date(e.at).toLocaleTimeString()}</span>
              <span className="w-20 shrink-0">{e.stage}</span><span className="w-24 shrink-0">{e.status}</span>
              <span className="text-muted">{e.page_no ? `page ${e.page_no} ` : ""}{e.message}{e.duration_ms ? ` (${e.duration_ms} ms)` : ""}</span></li>
          ))}
        </ol>
      </Card>
    </>
  );
}
