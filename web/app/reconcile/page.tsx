"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, type Doc } from "@/lib/api";
import { Button, Card, Chip, Empty, ErrorNote, PageTitle, Spinner, inputCls } from "@/components/ui";
import { useLang } from "@/lib/i18n";

function Ref({ r }: { r: any }) {
  const { t } = useLang();
  if (!r?.invoice_id) return null;
  return <Link className="whitespace-nowrap text-brand hover:underline" href={`/invoices/${r.invoice_id}`}>{r.sheet ? t(`${r.sheet} row ${r.row}`, `${r.sheet} সারি ${r.row}`) : t(`page ${r.page ?? 1}`, `পাতা ${r.page ?? 1}`)}</Link>;
}

const CATEGORY: Record<string, [string, string]> = {
  matched: ["Matched", "মিলেছে"], amount_mismatch: ["Wrong amount", "পরিমাণ মেলেনি"], missing_in_ledger: ["Not in the ledger", "লেজারে নেই"],
  missing_in_invoices: ["No invoice for this row", "এই সারির ইনভয়েস নেই"], ambiguous: ["More than one match", "একাধিক মিল"],
  date_mismatch: ["Different date", "তারিখ আলাদা"], supplier_mismatch: ["Different supplier", "সরবরাহকারী আলাদা"],
  duplicate_in_ledger: ["Twice in the ledger", "লেজারে দুবার"], matched_without_number: ["Matched without a number", "নম্বর ছাড়া মিলেছে"],
};
const money = (v: any) => (v == null ? "-" : /^-?\d+\.\d+$/.test(String(v)) ? Number(v).toFixed(2) : String(v));
const COLS: Record<number, string> = { 1: "sm:grid-cols-1", 2: "sm:grid-cols-2", 3: "sm:grid-cols-3", 4: "sm:grid-cols-4", 5: "sm:grid-cols-5", 6: "sm:grid-cols-6" };

export default function Reconcile() {
  const { t } = useLang();
  const label = (s: string) => (CATEGORY[s] ? t(CATEGORY[s][0], CATEGORY[s][1]) : s.replaceAll("_", " "));
  const sheets = useQuery({ queryKey: ["sheets"], queryFn: () => api<{ items: Doc[] }>("/documents?kind=sheet&limit=100") });
  const [ledger, setLedger] = useState("");
  const [run, setRun] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const go = async () => {
    setBusy(true);
    setErr(null);
    try { setRun(await api("/reconciliations", { method: "POST", body: JSON.stringify({ kind: "ledger", ledger_document_id: ledger }) })); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  const items: any[] = run ? [...run.items.filter((i: any) => i.category !== "matched"), ...run.items.filter((i: any) => i.category === "matched")] : [];
  const summary = run ? (Object.entries(run.summary) as [string, number][]) : [];
  const open = items.filter((i) => i.category !== "matched").length;
  const options = sheets.data?.items || [];

  return (
    <>
      <PageTitle title={t("Match ledger", "লেজার মেলান")} sub={t("Check your payment records against the invoices we read.", "আপনার পেমেন্টের হিসাব পড়া ইনভয়েসের সাথে মিলিয়ে দেখুন।")} />
      <Card className="mb-6 flex flex-wrap items-center gap-3 p-3">
        <label htmlFor="ledger" className="pl-1 text-sm text-muted">{t("Ledger", "লেজার")}</label>
        <select id="ledger" value={ledger} onChange={(e) => setLedger(e.target.value)} className={`${inputCls} min-w-0 flex-1 sm:max-w-sm`} disabled={sheets.isLoading}>
          <option value="">{sheets.isLoading ? t("Loading…", "লোড হচ্ছে…") : options.length ? t("Choose a ledger file", "লেজার ফাইল বাছুন") : t("No Excel files uploaded", "কোনো Excel ফাইল আপলোড হয়নি")}</option>
          {options.map((d) => <option key={d.id} value={d.id}>{d.filename}{d.role === "ledger" ? " (payment ledger)" : d.role === "invoices" ? " (invoice list)" : d.role === "purchase_orders" ? " (purchase orders)" : ""}</option>)}
        </select>
        <Button onClick={go} disabled={!ledger || busy} className="max-sm:w-full">{busy && <Spinner />} {busy ? t("Matching…", "মেলানো হচ্ছে…") : t("Match now", "এখন মেলান")}</Button>
      </Card>
      {err && <div className="mb-4"><ErrorNote>{err}</ErrorNote></div>}
      {sheets.isError && <div className="mb-4"><ErrorNote retry={() => sheets.refetch()}>{t("Could not load the files.", "ফাইল লোড হয়নি।")}</ErrorNote></div>}

      {!run ? (
        <Empty action={options.length ? null : <Link href="/" className="text-sm font-medium text-brand hover:underline">{t("Upload a ledger", "লেজার আপলোড")}</Link>}>
          {options.length ? t("Choose a ledger file and press Match now. Problems are shown first.", "লেজার ফাইল বেছে এখন মেলান চাপুন। সমস্যাগুলো আগে দেখাবে।") : t("Upload a ledger (XLSX, XLS or CSV) first.", "আগে একটি লেজার (XLSX, XLS বা CSV) আপলোড করুন।")}
        </Empty>
      ) : (
        <>
          <p className="mb-3 text-sm text-muted">
            {open === 0 ? t("Every ledger row matched an invoice.", "লেজারের প্রতিটি সারি একটি ইনভয়েসের সাথে মিলেছে।") : <><span className="num font-medium text-accent-ink">{open}</span> {t(open === 1 ? "row needs a look. Shown first." : "rows need a look. Shown first.", "টি সারি দেখা দরকার। এগুলো আগে দেখানো হলো।")}</>}
          </p>
          <dl className={`mb-6 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line ${COLS[Math.min(summary.length, 6)] || "sm:grid-cols-3"}`}>
            {summary.map(([k, v]) => (
              <div key={k} className="bg-surface px-4 py-3">
                <dt className="truncate text-xs text-muted">{label(k)}</dt>
                <dd className={`num mt-0.5 text-xl ${v && k !== "matched" && !k.includes("total") ? "text-accent-ink" : "text-ink"}`}>{v}</dd>
              </div>
            ))}
            {summary.length % 2 === 1 && <div className="bg-surface sm:hidden" aria-hidden />}
          </dl>
          <Card>
            <div className="overflow-x-auto">
              <table className="tbl hidden text-sm md:table">
                <thead><tr><th>{t("Result", "ফল")}</th><th>{t("Field", "ঘর")}</th><th className="r">{t("Invoice", "ইনভয়েস")}</th><th className="r">{t("Ledger", "লেজার")}</th><th className="r">{t("Difference", "পার্থক্য")}</th><th>{t("Where", "কোথায়")}</th></tr></thead>
                <tbody>
                  {items.map((i, k) => (
                    <tr key={k}>
                      <td><span className="flex flex-wrap items-center gap-2"><Chip value={i.category === "matched" ? "matched" : i.severity} /><span className="text-ink2">{label(i.category)}</span></span></td>
                      <td className="text-muted">{i.field ? i.field.replaceAll("_", " ") : "-"}</td>
                      <td className="r num">{money(i.left_value)}</td>
                      <td className="r num">{money(i.right_value)}</td>
                      <td className={`r num ${i.delta && Number(i.delta) !== 0 ? "text-accent-ink" : "text-muted"}`}>{money(i.delta)}</td>
                      <td><span className="flex flex-wrap gap-x-3"><Ref r={i.left_ref} /><Ref r={i.right_ref} /></span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="md:hidden">
              {items.map((i, k) => (
                <li key={k} className="border-b border-rule px-4 py-3 last:border-0">
                  <div className="flex items-center gap-2">
                    <Chip value={i.category === "matched" ? "matched" : i.severity} />
                    <span className="min-w-0 flex-1 truncate">{label(i.category)}</span>
                    {i.delta && <span className="num text-sm text-accent-ink">{money(i.delta)}</span>}
                  </div>
                  <div className="mt-1 text-[13px] text-muted">
                    {i.field ? `${i.field.replaceAll("_", " ")}: ` : ""}<span className="num">{money(i.left_value)}</span> {t("vs", "বনাম")} <span className="num">{money(i.right_value)}</span>
                  </div>
                  <div className="mt-1 flex gap-3 text-[13px]"><Ref r={i.left_ref} /><Ref r={i.right_ref} /></div>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </>
  );
}
