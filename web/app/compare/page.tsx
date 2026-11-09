"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Chip, ErrorNote, Loading, PageTitle, Panel } from "@/components/ui";
import { api, imageUrl } from "@/lib/api";

const ROWS = ["invoice_number", "supplier_name", "customer_name", "invoice_date", "due_date", "po_number", "currency",
  "subtotal", "tax", "total", "bank_account"];
const label = (k: string) => (k === "po_number" ? "PO number" : k.charAt(0).toUpperCase() + k.slice(1).replaceAll("_", " "));
const val = (inv: any, k: string) => (k === "bank_account" ? inv.bank_account : inv.fields?.[k]?.value ?? inv[k]) ?? null;
const MONO = new Set(["invoice_number", "invoice_date", "due_date", "po_number", "currency", "subtotal", "tax", "total", "bank_account"]);
const same = (a: any, b: any) => (a == null && b == null) || (a != null && b != null && String(a).toLowerCase() === String(b).toLowerCase());

function Side({ inv }: { inv: any }) {
  return (
    <div className="min-w-0">
      <Link href={`/invoices/${inv.id}`} className="font-medium hover:text-brand hover:underline">{inv.filename}</Link>
      <span className="ml-2 align-middle"><Chip value={inv.status} /></span>
      {inv.page_start ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={imageUrl(inv.document_id, inv.page_start)} alt={`First page of ${inv.filename}`} className="mt-3 w-full rounded border border-control bg-white" loading="lazy" />
      ) : <p className="mt-3 rounded bg-sunken px-3 py-6 text-sm text-muted">{inv.sheet_name ? `Sheet ${inv.sheet_name}, row ${inv.row_index}` : "No page image"}</p>}
    </div>
  );
}

function View() {
  const sp = useSearchParams();
  const left = sp.get("left"), right = sp.get("right");
  const q = useQuery({ queryKey: ["compare", left, right], enabled: !!left && !!right,
    queryFn: () => api<any>(`/compare?left=${left}&right=${right}`) });
  const back = <Link href={left ? `/invoices/${left}` : "/review"} className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-ink"><ChevronLeft size={16} aria-hidden /> Back to the invoice</Link>;
  if (!left || !right) return <>{back}<ErrorNote>Two invoices are needed to compare.</ErrorNote></>;
  if (q.isLoading) return <>{back}<Loading rows={8} /></>;
  if (q.isError || !q.data) return <>{back}<ErrorNote retry={() => q.refetch()}>Could not load the two invoices.</ErrorNote></>;
  const { left: a, right: b, items } = q.data;
  const diffs = ROWS.filter((k) => !same(val(a, k), val(b, k)));
  const lineDiffs = items.filter((i: any) => i.category.startsWith("line_"));

  return (
    <>
      {back}
      <PageTitle title="Compare two invoices"
        sub={diffs.length === 0 && lineDiffs.length === 0 ? "Every field and line matches. This is very likely the same invoice sent twice."
          : `${diffs.length} ${diffs.length === 1 ? "field differs" : "fields differ"}${lineDiffs.length ? ` and ${lineDiffs.length} line ${lineDiffs.length === 1 ? "item differs" : "items differ"}` : ""}.`} />
      <Panel title="Fields">
        <div className="overflow-x-auto">
          <table className="tbl text-sm">
            <thead><tr><th>Field</th><th>{a.filename}</th><th>{b.filename}</th></tr></thead>
            <tbody>
              {ROWS.map((k) => {
                const x = val(a, k), y = val(b, k), d = !same(x, y);
                return (
                  <tr key={k} className={clsx(d && "[&>td]:bg-warnwash")}>
                    <td className="text-muted">{label(k)}</td>
                    <td className={clsx(MONO.has(k) && "num text-[13px]", d && "font-medium")}>{x ?? <span className="font-sans text-faint">-</span>}</td>
                    <td className={clsx(MONO.has(k) && "num text-[13px]", d && "font-medium")}>{y ?? <span className="font-sans text-faint">-</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      {lineDiffs.length > 0 && (
        <Panel title="Line items that differ" className="mt-6">
          <ul>{lineDiffs.map((i: any, k: number) => (
            <li key={k} className="flex flex-wrap gap-x-3 border-b border-rule px-4 py-2.5 text-sm last:border-0">
              <Chip value={i.severity} /><span>{i.category.replaceAll("_", " ")}</span>
              <span className="num text-muted">{i.left_value ?? "-"} against {i.right_value ?? "-"}</span>
            </li>
          ))}</ul>
        </Panel>
      )}
      <div className="mt-6 grid gap-6 md:grid-cols-2"><Side inv={a} /><Side inv={b} /></div>
    </>
  );
}

export default function Compare() {
  return <Suspense><View /></Suspense>;
}
