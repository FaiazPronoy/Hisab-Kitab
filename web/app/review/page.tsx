"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, type InvoiceSummary } from "@/lib/api";
import { Card, Chip, Empty, ErrorNote, Loading, PageTitle } from "@/components/ui";

const SEV = ["critical", "error", "warning"] as const;

function Findings({ i }: { i: InvoiceSummary }) {
  return (
    <span className="flex flex-wrap gap-1">
      {SEV.map((s) => (i.findings[s] ? <Chip key={s} value={`${i.findings[s]} ${s}`} /> : null))}
    </span>
  );
}

export default function ReviewQueue() {
  const q = useQuery({ queryKey: ["queue"], queryFn: () => api<InvoiceSummary[]>("/review-queue?limit=200"), refetchInterval: 5000 });
  const rows = q.data || [];
  return (
    <>
      <PageTitle title="Review queue"
        sub="Invoices with errors, missing key fields or more than one warning, most severe first."
        right={rows.length > 0 ? <Link href={`/invoices/${rows[0].id}`} className="inline-flex h-9 items-center rounded-md bg-brand px-3.5 text-sm font-medium text-white hover:bg-brand-dark max-sm:h-11">Start with the first</Link> : null} />
      {q.isLoading ? <Loading rows={6} /> : q.isError ? <ErrorNote retry={() => q.refetch()}>Could not load the review queue.</ErrorNote>
        : !rows.length ? <Empty>Nothing waiting for review. Every processed invoice passed its checks.</Empty> : (
        <Card>
          <div className="border-b border-line px-4 py-3 text-sm text-muted"><span className="num text-ink">{rows.length}</span> {rows.length === 1 ? "invoice" : "invoices"} waiting</div>
          <table className="tbl hidden text-sm md:table">
            <thead><tr><th>Supplier</th><th>Invoice</th><th className="r">Total</th><th>Findings</th><th>File</th></tr></thead>
            <tbody>
              {rows.map((i) => (
                <tr key={i.id}>
                  <td><Link href={`/invoices/${i.id}`} className="font-medium text-ink hover:text-brand hover:underline">{i.supplier_name || "Unknown supplier"}</Link></td>
                  <td className="num text-[13px]">{i.invoice_number || <span className="font-sans text-muted">no number</span>}</td>
                  <td className="r num whitespace-nowrap">{i.total ?? "-"} <span className="text-xs text-muted">{i.currency}</span></td>
                  <td><Findings i={i} /></td>
                  <td className="max-w-[16rem] truncate text-muted" title={i.filename}>{i.filename}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="md:hidden">
            {rows.map((i) => (
              <li key={i.id} className="border-b border-rule last:border-0">
                <Link href={`/invoices/${i.id}`} className="block px-4 py-3 active:bg-paper">
                  <span className="flex items-baseline gap-3">
                    <span className="min-w-0 flex-1 truncate font-medium">{i.supplier_name || "Unknown supplier"}</span>
                    <span className="num shrink-0">{i.total ?? "-"} <span className="text-xs text-muted">{i.currency}</span></span>
                  </span>
                  <span className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-muted">
                    <span className="num">{i.invoice_number || "no number"}</span><Findings i={i} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
