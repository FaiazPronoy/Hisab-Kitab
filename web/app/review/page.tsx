"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, type InvoiceSummary } from "@/lib/api";
import { Card, Chip, Empty, PageTitle, Spinner } from "@/components/ui";

export default function ReviewQueue() {
  const q = useQuery({ queryKey: ["queue"], queryFn: () => api<InvoiceSummary[]>("/review-queue?limit=200"), refetchInterval: 5000 });
  return (
    <>
      <PageTitle title="Review queue" sub="Invoices with errors, missing key fields or more than one warning, most severe first." />
      {q.isLoading ? <Spinner /> : !q.data?.length ? <Empty>Nothing waiting for review.</Empty> : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-paper text-left text-muted"><tr>
              <th className="px-4 py-2 font-medium">Invoice</th><th className="px-4 py-2 font-medium">Supplier</th>
              <th className="px-4 py-2 text-right font-medium">Total</th><th className="px-4 py-2 font-medium">Findings</th>
              <th className="px-4 py-2 font-medium">File</th></tr></thead>
            <tbody className="divide-y divide-line">
              {q.data.map((i) => (
                <tr key={i.id} className="hover:bg-paper">
                  <td className="px-4 py-2"><Link href={`/invoices/${i.id}`} className="text-brand underline">{i.invoice_number || "(no number)"}</Link></td>
                  <td className="px-4 py-2">{i.supplier_name}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{i.total} {i.currency}</td>
                  <td className="space-x-1 px-4 py-2">
                    {(["critical", "error", "warning"] as const).map((s) => (i.findings[s] ? <Chip key={s} value={`${i.findings[s]} ${s}`} className="ml-1" /> : null))}
                  </td>
                  <td className="px-4 py-2 text-muted">{i.filename}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
