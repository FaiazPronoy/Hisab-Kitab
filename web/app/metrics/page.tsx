"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "@/lib/api";
import { ErrorNote, Figures, Loading, PageTitle, Panel } from "@/components/ui";
import { statusLabel, useLang } from "@/lib/i18n";

const pct = (v: number | null | undefined) => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
const DOC_ORDER = ["done", "needs_review", "completed_with_errors", "failed", "rejected", "processing", "finalizing", "queued"];
const INV_ORDER = ["auto_validated", "needs_review", "approved"];
const READ_BY: Record<string, [string, string]> = {
  text_layer: ["Text in the PDF", "PDF-এর লেখা"], ocr: ["OCR (scans)", "OCR (স্ক্যান)"], ocr_heavy: ["OCR, large scans", "OCR, বড় স্ক্যান"],
  vision: ["Image model", "ছবি মডেল"], sheet: ["Excel", "Excel"],
};

function Bars({ data, order, signal }: { data: Record<string, number>; order: string[]; signal: Record<string, "warn" | "bad"> }) {
  const { t, lang } = useLang();
  const keys = [...order.filter((k) => k in data), ...Object.keys(data).filter((k) => !order.includes(k))];
  const max = Math.max(1, ...keys.map((k) => data[k]));
  if (!keys.length) return <p className="px-4 py-4 text-sm text-muted">{t("Nothing read yet.", "এখনো কিছু পড়া হয়নি।")}</p>;
  return (
    <ul className="space-y-3 px-4 py-4">
      {keys.map((k) => (
        <li key={k} className="grid grid-cols-[8.5rem_minmax(0,1fr)_3rem] items-center gap-3 text-sm max-sm:grid-cols-[7rem_minmax(0,1fr)_2.5rem]">
          <span className="truncate text-ink2 first-letter:uppercase">{statusLabel(k, lang)}</span>
          <span className="h-2 rounded-sm bg-rule">
            <span className={clsx("block h-2 rounded-sm", signal[k] === "bad" ? "bg-[#c4242a]" : signal[k] === "warn" ? "bg-accent" : "bg-brand")}
              style={{ width: `${Math.max(data[k] ? 2 : 0, (data[k] / max) * 100)}%` }} />
          </span>
          <span className="num text-right">{data[k]}</span>
        </li>
      ))}
    </ul>
  );
}

export default function Metrics() {
  const { t } = useLang();
  const q = useQuery({ queryKey: ["metrics"], queryFn: () => api<any>("/metrics/summary"), refetchInterval: 5000 });
  const head = <PageTitle title={t("Numbers", "পরিসংখ্যান")} sub={t("Live counts from this system. The full test results are in EVALUATION.md.", "এই সিস্টেমের এখনকার হিসাব। পুরো পরীক্ষার ফল EVALUATION.md-এ।")} />;
  if (q.isLoading) return <>{head}<Loading rows={3} /></>;
  if (q.isError || !q.data) return <>{head}<ErrorNote retry={() => q.refetch()}>{t("Could not load the numbers.", "পরিসংখ্যান লোড হয়নি।")}</ErrorNote></>;
  const m = q.data;
  const docs: Record<string, number> = m.documents || {};
  const invs: Record<string, number> = m.invoices || {};
  const nDocs = Object.values(docs).reduce((a, b) => a + b, 0);
  const nInv = Object.values(invs).reduce((a, b) => a + b, 0);
  const timing = Object.entries(m.page_timing_ms || {}) as [string, { n: number; p50: number; p95: number }][];
  const slowest = Math.max(1, ...timing.map(([, v]) => v.p95));

  return (
    <>
      {head}
      <Figures items={[
        { label: t("Files", "ফাইল"), value: nDocs, note: t(`${nInv} invoices found`, `${nInv}টি ইনভয়েস পাওয়া গেছে`) },
        { label: t("Read without errors", "ঠিকমতো পড়া"), value: pct(m.success_rate), note: t("done or sent to review", "সম্পন্ন বা রিভিউতে") },
        { label: t("Failed", "ব্যর্থ"), value: pct(m.failure_rate), note: t(`${docs.failed || 0} failed, ${docs.completed_with_errors || 0} partly read`, `${docs.failed || 0}টি ব্যর্থ, ${docs.completed_with_errors || 0}টি আংশিক`) },
        { label: t("To review", "রিভিউ বাকি"), value: m.needs_review, note: t("invoices", "ইনভয়েস") },
        { label: t("Approved, not paid", "অনুমোদিত, পরিশোধ বাকি"), value: m.approved_unpaid ?? 0, note: t("invoices", "ইনভয়েস") },
        { label: t("AI cost", "AI খরচ"), value: `$${Number(m.llm.cost_usd).toFixed(2)}`, note: t(`${m.llm.calls} calls`, `${m.llm.calls}টি কল`) },
      ]} />

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Panel title={t("Files by status", "অবস্থা অনুযায়ী ফাইল")} meta={t(`${nDocs} in all`, `মোট ${nDocs}`)}>
          <Bars data={docs} order={DOC_ORDER} signal={{ needs_review: "warn", completed_with_errors: "warn", failed: "bad", rejected: "bad" }} />
        </Panel>
        <Panel title={t("Invoices by status", "অবস্থা অনুযায়ী ইনভয়েস")} meta={t(`${nInv} in all`, `মোট ${nInv}`)}>
          <Bars data={invs} order={INV_ORDER} signal={{ needs_review: "warn" }} />
        </Panel>
      </div>

      <Panel title={t("Time to read one page", "এক পাতা পড়ার সময়")} meta={t("half of the pages took less than the middle value", "অর্ধেক পাতা মাঝের মানের চেয়ে কম সময় নিয়েছে")} className="mt-6">
        {timing.length === 0 ? <p className="px-4 py-4 text-sm text-muted">{t("No pages read yet.", "এখনো কোনো পাতা পড়া হয়নি।")}</p> : (
          <div className="overflow-x-auto">
            <table className="tbl text-sm">
              <thead><tr><th>{t("How it was read", "কীভাবে পড়া")}</th><th className="r">{t("Pages", "পাতা")}</th><th className="r">{t("Middle (p50)", "মাঝের (p50)")}</th><th className="r">{t("Slow (p95)", "ধীর (p95)")}</th><th className="w-[40%] max-sm:hidden">{t("Slow time, compared", "ধীর সময়, তুলনা")}</th></tr></thead>
              <tbody>
                {timing.map(([k, v]) => (
                  <tr key={k}>
                    <td>{READ_BY[k] ? t(READ_BY[k][0], READ_BY[k][1]) : k.replaceAll("_", " ")}</td>
                    <td className="r num">{v.n}</td>
                    <td className="r num whitespace-nowrap">{Math.round(v.p50).toLocaleString()} <span className="text-xs text-muted">ms</span></td>
                    <td className="r num whitespace-nowrap">{Math.round(v.p95).toLocaleString()} <span className="text-xs text-muted">ms</span></td>
                    <td className="max-sm:hidden"><span className="block h-2 rounded-sm bg-rule"><span className="block h-2 rounded-sm bg-brand" style={{ width: `${(v.p95 / slowest) * 100}%` }} /></span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}
