"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";
import { api, type Doc } from "@/lib/api";
import { Chip, Empty, ErrorNote, Loading, PageTitle, Panel, Spinner } from "@/components/ui";
import { useLang } from "@/lib/i18n";

const READ_BY: Record<string, [string, string]> = {
  text_layer: ["text in the PDF", "PDF-এর লেখা"], ocr: ["OCR", "OCR"], ocr_heavy: ["OCR, large scan", "OCR, বড় স্ক্যান"],
  vision: ["image model", "ছবি মডেল"], sheet: ["Excel", "Excel"],
};

export default function DocumentDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { t } = useLang();
  const doc = useQuery({ queryKey: ["doc", id], queryFn: () => api<Doc>(`/documents/${id}`), refetchInterval: 3000 });
  const qc = useQueryClient();
  const [roleBusy, setRoleBusy] = useState(false);
  const [roleErr, setRoleErr] = useState<string | null>(null);
  const switchRole = async (role: string) => {
    setRoleBusy(true);
    setRoleErr(null);
    try {
      await api(`/documents/${id}`, { method: "PATCH", body: JSON.stringify({ role }) });
      await qc.invalidateQueries({ queryKey: ["doc", id] });
      qc.invalidateQueries({ queryKey: ["metrics"] });
      qc.invalidateQueries({ queryKey: ["queue"] });
    } catch (e: any) {
      setRoleErr(e.message);
    } finally {
      setRoleBusy(false);
    }
  };
  const hist = useQuery({ queryKey: ["hist", id], queryFn: () => api<any[]>(`/documents/${id}/history`), refetchInterval: 5000 });
  const back = <Link href="/documents" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-ink"><ChevronLeft size={16} aria-hidden /> {t("Documents", "ডকুমেন্ট")}</Link>;
  if (doc.isLoading) return <>{back}<Loading rows={5} /></>;
  if (doc.isError && !doc.data) return <>{back}<ErrorNote retry={() => doc.refetch()}>{t("Could not load this file.", "ফাইলটি লোড হয়নি।")} {(doc.error as Error).message}</ErrorNote></>;
  const d = doc.data;
  if (!d) return <>{back}<Empty>{t("File not found.", "ফাইল পাওয়া যায়নি।")}</Empty></>;
  const unit = d.kind === "sheet" ? t("sheets", "শিট") : t("pages", "পাতা");
  const events = hist.data || [];

  return (
    <>
      {back}
      <PageTitle title={<span className="break-all">{d.filename}</span>}
        sub={<>{d.kind}, <span className="num">{d.page_count}</span> {unit}{d.pages_failed ? <>, <span className="num">{d.pages_failed}</span> {t("failed", "ব্যর্থ")}</> : null}. {t("Uploaded", "আপলোড")} {new Date(d.created_at).toLocaleString()}.</>}
        right={<>
          {d.kind === "sheet" && d.role && (
            <label className="flex items-center gap-2 text-sm text-muted">
              {t("This sheet is", "এই শিটটি")}
              <select value={d.role} disabled={roleBusy} onChange={(e) => switchRole(e.target.value)}
                className="h-8 rounded-md border border-control bg-surface px-2 text-sm text-ink disabled:opacity-50">
                <option value="invoices">{t("a list of invoices", "ইনভয়েসের তালিকা")}</option>
                <option value="ledger">{t("payment records (ledger)", "পেমেন্টের হিসাব (লেজার)")}</option>
                <option value="purchase_orders">{t("purchase orders", "ক্রয় আদেশ")}</option>
              </select>
              {roleBusy && <Spinner />}
            </label>
          )}
          <Chip value={d.status} />
        </>} />
      {roleErr && <div className="mb-4"><ErrorNote>{roleErr}</ErrorNote></div>}
      {d.error_message && <div className="mb-6"><ErrorNote><b className="font-semibold">{d.error_code}</b>: {d.error_message}</ErrorNote></div>}

      <Panel title={t("Invoices found", "পাওয়া ইনভয়েস")} meta={d.invoices?.length ? `${d.invoices.length}` : undefined} className="mb-6">
        {!d.invoices?.length ? <p className="px-4 py-4 text-sm text-muted">{["queued", "processing", "finalizing"].includes(d.status) ? t("Still reading this file.", "ফাইলটি এখনো পড়া হচ্ছে।") : t("No invoices found in this file.", "এই ফাইলে কোনো ইনভয়েস পাওয়া যায়নি।")}</p> : (
          <div className="overflow-x-auto">
            <table className="tbl text-sm">
              <thead><tr><th>{t("Supplier", "সরবরাহকারী")}</th><th>{t("Number", "নম্বর")}</th><th>{t("Date", "তারিখ")}</th><th className="r">{t("Total", "মোট")}</th><th>{t("Where", "কোথায়")}</th><th>{t("Status", "অবস্থা")}</th></tr></thead>
              <tbody>
                {d.invoices.map((i) => (
                  <tr key={i.id}>
                    <td><Link className="font-medium text-ink hover:text-brand hover:underline" href={`/invoices/${i.id}`}>{i.supplier_name || t("Unknown supplier", "অজানা সরবরাহকারী")}</Link></td>
                    <td className="num text-[13px]">{i.invoice_number || <span className="font-sans text-muted">{t("no number", "নম্বর নেই")}</span>}</td>
                    <td className="num whitespace-nowrap text-[13px]">{i.invoice_date || "-"}</td>
                    <td className="r num whitespace-nowrap">{i.total ?? "-"} <span className="text-xs text-muted">{i.currency}</span></td>
                    <td className="whitespace-nowrap text-muted">{i.sheet_name ? `${i.sheet_name}${i.row_index ? t(`, row ${i.row_index}`, `, সারি ${i.row_index}`) : ""}` : t(`page ${i.page_start}`, `পাতা ${i.page_start}`)}</td>
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
          <Panel title={t("Pages", "পাতা")} meta={t(`${d.pages_done} of ${d.page_count} read`, `${d.page_count}টির মধ্যে ${d.pages_done}টি পড়া`)}>
            <div className="flex flex-wrap gap-1 border-b border-rule px-4 py-3" aria-hidden>
              {d.pages.map((p) => (
                <span key={p.page_no} title={`Page ${p.page_no}: ${p.status}`}
                  className={clsx("h-3 w-3 rounded-[2px]", p.status === "done" ? (p.source === "text_layer" ? "bg-brand" : "bg-[#5fa39a]") : p.status === "failed" ? "bg-[#c4242a]" : "bg-rule")} />
              ))}
            </div>
            <div className="max-h-80 overflow-auto">
              <table className="tbl text-sm">
                <thead className="sticky top-0 bg-surface"><tr><th className="r">{t("Page", "পাতা")}</th><th>{t("Read by", "যেভাবে পড়া")}</th><th>{t("Why", "কেন")}</th><th className="r">{t("OCR score", "OCR স্কোর")}</th><th>{t("Status", "অবস্থা")}</th></tr></thead>
                <tbody>
                  {d.pages.map((p) => (
                    <tr key={p.page_no}>
                      <td className="r num">{p.page_no}</td>
                      <td className="whitespace-nowrap">{p.source ? (READ_BY[p.source] ? t(READ_BY[p.source][0], READ_BY[p.source][1]) : p.source.replaceAll("_", " ")) : "-"}</td>
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

        <Panel title={t("What happened", "কী কী হয়েছে")} meta={events.length ? t(`${events.length} steps`, `${events.length}টি ধাপ`) : undefined} className={clsx(!(d.pages && d.pages.length) && "lg:col-span-2")}>
          {hist.isError ? <p className="px-4 py-4 text-sm text-bad">{t("Could not load the history.", "ইতিহাস লোড হয়নি।")}</p> : !events.length ? <p className="px-4 py-4 text-sm text-muted">{t("Nothing yet.", "এখনো কিছু নেই।")}</p> : (
            <ol className="max-h-[22rem] overflow-auto px-4 py-2">
              {events.map((e, k) => (
                <li key={k} className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-3 border-b border-rule py-2 text-sm last:border-0">
                  <span className="num pt-px text-xs text-muted">{new Date(e.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}</span>
                  <span className="min-w-0">
                    <span className="font-medium">{e.stage}</span>{" "}
                    <span className={clsx(e.status === "failed" || e.status === "error" ? "text-bad" : "text-muted")}>{e.status}</span>
                    {(e.page_no || e.message || e.duration_ms) && (
                      <span className="block break-words text-[13px] text-muted">
                        {e.page_no ? t(`page ${e.page_no} `, `পাতা ${e.page_no} `) : ""}{e.message}{e.duration_ms ? <> <span className="num">({e.duration_ms} ms)</span></> : null}
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
