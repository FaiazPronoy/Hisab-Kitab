"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Chip, ErrorNote, Loading, PageTitle, Panel } from "@/components/ui";
import { api, imageUrl } from "@/lib/api";
import { fieldLabel, useLang } from "@/lib/i18n";

const ROWS = ["invoice_number", "supplier_name", "customer_name", "invoice_date", "due_date", "po_number", "currency",
  "subtotal", "tax", "total", "bank_account"];
const val = (inv: any, k: string) => (k === "bank_account" ? inv.bank_account : inv.fields?.[k]?.value ?? inv[k]) ?? null;
const MONO = new Set(["invoice_number", "invoice_date", "due_date", "po_number", "currency", "subtotal", "tax", "total", "bank_account"]);
const same = (a: any, b: any) => (a == null && b == null) || (a != null && b != null && String(a).toLowerCase() === String(b).toLowerCase());

function Side({ inv }: { inv: any }) {
  const { t } = useLang();
  return (
    <div className="min-w-0">
      <Link href={`/invoices/${inv.id}`} className="font-medium hover:text-brand hover:underline">{inv.filename}</Link>
      <span className="ml-2 align-middle"><Chip value={inv.status} /></span>
      {inv.page_start ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={imageUrl(inv.document_id, inv.page_start)} alt={`First page of ${inv.filename}`} className="mt-3 w-full rounded border border-control bg-white" loading="lazy" />
      ) : <p className="mt-3 rounded bg-sunken px-3 py-6 text-sm text-muted">{inv.sheet_name ? t(`Sheet ${inv.sheet_name}, row ${inv.row_index}`, `শিট ${inv.sheet_name}, সারি ${inv.row_index}`) : t("No page image", "পাতার ছবি নেই")}</p>}
    </div>
  );
}

function View() {
  const { t, lang } = useLang();
  const label = (k: string) => fieldLabel(k, lang);
  const sp = useSearchParams();
  const left = sp.get("left"), right = sp.get("right");
  const q = useQuery({ queryKey: ["compare", left, right], enabled: !!left && !!right,
    queryFn: () => api<any>(`/compare?left=${left}&right=${right}`) });
  const back = <Link href={left ? `/invoices/${left}` : "/review"} className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-ink"><ChevronLeft size={16} aria-hidden /> {t("Back to the invoice", "ইনভয়েসে ফিরুন")}</Link>;
  if (!left || !right) return <>{back}<ErrorNote>{t("Two invoices are needed.", "দুটি ইনভয়েস লাগবে।")}</ErrorNote></>;
  if (q.isLoading) return <>{back}<Loading rows={8} /></>;
  if (q.isError || !q.data) return <>{back}<ErrorNote retry={() => q.refetch()}>{t("Could not load the invoices.", "ইনভয়েস লোড হয়নি।")}</ErrorNote></>;
  const { left: a, right: b, items } = q.data;
  const diffs = ROWS.filter((k) => !same(val(a, k), val(b, k)));
  const lineDiffs = items.filter((i: any) => i.category.startsWith("line_"));

  return (
    <>
      {back}
      <PageTitle title={t("Compare two invoices", "দুটি ইনভয়েস তুলনা")}
        sub={diffs.length === 0 && lineDiffs.length === 0 ? t("Everything is the same. It is very likely the same invoice sent twice.", "সব একই। সম্ভবত একই ইনভয়েস দুবার পাঠানো হয়েছে।")
          : t(`${diffs.length} ${diffs.length === 1 ? "field is" : "fields are"} different${lineDiffs.length ? `, and ${lineDiffs.length} ${lineDiffs.length === 1 ? "line" : "lines"}` : ""}. They are marked below.`,
              `${diffs.length}টি ঘর আলাদা${lineDiffs.length ? `, আর ${lineDiffs.length}টি লাইন` : ""}। নিচে চিহ্নিত করা আছে।`)} />
      <Panel title={t("Fields", "ঘর")}>
        <div className="overflow-x-auto">
          <table className="tbl text-sm">
            <thead><tr><th>{t("Field", "ঘর")}</th><th>{a.filename}</th><th>{b.filename}</th></tr></thead>
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
        <Panel title={t("Lines that are different", "যে লাইনগুলো আলাদা")} className="mt-6">
          <ul>{lineDiffs.map((i: any, k: number) => (
            <li key={k} className="flex flex-wrap gap-x-3 border-b border-rule px-4 py-2.5 text-sm last:border-0">
              <Chip value={i.severity} /><span>{i.category.replaceAll("_", " ")}</span>
              <span className="num text-muted">{i.left_value ?? "-"} {t("vs", "বনাম")} {i.right_value ?? "-"}</span>
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
