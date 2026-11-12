"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Download } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useSession } from "@/components/Shell";
import { Button, Card, Empty, ErrorNote, Loading, PageTitle, Panel, Spinner, inputCls } from "@/components/ui";
import { api, raw } from "@/lib/api";
import { useLang } from "@/lib/i18n";

type Ready = { id: string; supplier_name: string | null; invoice_number: string | null; total: string | null; currency: string | null;
  due_date: string | null; account: string; iban: boolean; approved_by: string | null };

const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

async function download(id: string, filename: string) {
  const r = await raw(`/payments/batches/${id}/file`);
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function Payments() {
  const { t } = useLang();
  const session = useSession();
  const qc = useQueryClient();
  const ready = useQuery({ queryKey: ["pay-ready"], queryFn: () => api<Ready[]>("/payments/ready") });
  const batches = useQuery({ queryKey: ["pay-batches"], queryFn: () => api<any[]>("/payments/batches") });
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [format, setFormat] = useState("pain001");
  const [when, setWhen] = useState(today());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);

  const rows = ready.data || [];
  const chosen = rows.filter((r) => picked.has(r.id));
  const sums = useMemo(() => {
    const out: Record<string, number> = {};
    for (const r of chosen) if (r.currency && r.total) out[r.currency] = (out[r.currency] || 0) + Math.abs(Number(r.total));
    return out;
  }, [chosen]);
  const approver = session?.role === "approver";
  const blocked = format === "pain001" ? chosen.filter((r) => !r.iban) : chosen.filter((r) => !r.account);

  const toggle = (id: string) => setPicked((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const all = rows.length > 0 && chosen.length === rows.length;

  const create = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const b = await api<any>("/payments/batches", { method: "POST", body: JSON.stringify({ invoice_ids: chosen.map((r) => r.id), format, execution_date: when }) });
      setPicked(new Set());
      setMsg({ text: t(`${b.filename} is ready with ${b.invoice_count} ${b.invoice_count === 1 ? "payment" : "payments"}.`, `${b.filename} তৈরি, ${b.invoice_count}টি পেমেন্ট আছে।`) });
      try {
        await download(b.id, b.filename);
      } catch {
        setMsg({ text: t(`${b.filename} was made but did not download. Get it from the list below.`, `${b.filename} তৈরি হয়েছে কিন্তু ডাউনলোড হয়নি। নিচের তালিকা থেকে নিন।`), bad: true });
      }
    } catch (e: any) {
      setMsg({ text: e.message, bad: true });
    } finally {
      setBusy(false);
      qc.invalidateQueries({ queryKey: ["pay-ready"] });
      qc.invalidateQueries({ queryKey: ["pay-batches"] });
      qc.invalidateQueries({ queryKey: ["metrics"] });
    }
  };

  return (
    <>
      <PageTitle title={t("Payments", "পেমেন্ট")} sub={t("Approved invoices that are not paid yet. The earliest due date is first.", "অনুমোদিত কিন্তু এখনো পরিশোধ হয়নি এমন ইনভয়েস। যার তারিখ আগে, সেটা আগে।")} />
      {msg && <p className={`mb-4 rounded-lg border px-4 py-3 text-sm ${msg.bad ? "border-badline bg-badwash text-bad" : "border-line bg-goodwash text-good"}`} role="status">{msg.text}</p>}
      {ready.isLoading ? <Loading rows={5} /> : ready.isError ? <ErrorNote retry={() => ready.refetch()}>{t("Could not load the invoices.", "ইনভয়েস লোড হয়নি।")}</ErrorNote>
        : rows.length === 0 ? <Empty action={<Link href="/review" className="text-sm font-medium text-brand hover:underline">{t("Open the review list", "রিভিউ তালিকা খুলুন")}</Link>}>{t("No approved invoice is waiting to be paid.", "পরিশোধের অপেক্ষায় কোনো অনুমোদিত ইনভয়েস নেই।")}</Empty> : (
        <Card>
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={all} onChange={() => setPicked(all ? new Set() : new Set(rows.map((r) => r.id)))} className="h-4 w-4 accent-[var(--c-brand)]" />
              {chosen.length ? <span><span className="num">{chosen.length}</span> {t("selected", "টি বাছা")}</span> : <span className="text-muted">{t("Select all", "সব বাছুন")}</span>}
            </label>
            {Object.entries(sums).map(([c, v]) => <span key={c} className="num text-sm">{v.toFixed(2)} <span className="text-xs text-muted">{c}</span></span>)}
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <select value={format} onChange={(e) => setFormat(e.target.value)} aria-label={t("File type", "ফাইলের ধরন")} className={inputCls}>
                <option value="pain001">{t("Bank file, ISO 20022 (XML)", "ব্যাংক ফাইল, ISO 20022 (XML)")}</option>
                <option value="csv">{t("CSV for bank upload", "ব্যাংকে আপলোডের CSV")}</option>
              </select>
              <input type="date" value={when} min={today()} onChange={(e) => setWhen(e.target.value)} aria-label={t("Payment date", "পেমেন্টের তারিখ")} className={inputCls} />
              <Button onClick={create} disabled={!approver || busy || !chosen.length || blocked.length > 0}
                title={!approver ? t("Only an approver can make a payment file", "শুধু অনুমোদনকারী পেমেন্ট ফাইল বানাতে পারেন") : undefined}>
                {busy && <Spinner />} {t("Make payment file", "পেমেন্ট ফাইল বানান")}
              </Button>
            </div>
          </div>
          {(!approver || blocked.length > 0) && (
            <div className="border-b border-line px-4 py-2.5 text-sm">
              {!approver && <p className="text-muted">{t("You are signed in as a clerk. Only an approver can make payment files.", "আপনি ক্লার্ক হিসেবে আছেন। শুধু অনুমোদনকারী পেমেন্ট ফাইল বানাতে পারেন।")}</p>}
              {blocked.length > 0 && <p className="text-accent-ink">{format === "pain001"
                ? t(`${blocked.length} selected without an IBAN. Use CSV, or fix the account on the invoice.`, `${blocked.length}টিতে IBAN নেই। CSV ব্যবহার করুন, অথবা ইনভয়েসে অ্যাকাউন্ট ঠিক করুন।`)
                : t(`${blocked.length} selected without a bank account.`, `${blocked.length}টিতে ব্যাংক অ্যাকাউন্ট নেই।`)}</p>}
            </div>
          )}
          <ul className="md:hidden">
            {rows.map((r) => (
              <li key={r.id} className={clsx("flex items-start gap-3 border-b border-rule px-4 py-3 last:border-0", picked.has(r.id) && "bg-infowash")}>
                <input type="checkbox" checked={picked.has(r.id)} onChange={() => toggle(r.id)} aria-label={t(`Pay ${r.supplier_name} ${r.invoice_number}`, `${r.supplier_name} ${r.invoice_number} পরিশোধ`)} className="mt-1 h-5 w-5 accent-[var(--c-brand)]" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-3">
                    <Link href={`/invoices/${r.id}`} className="min-w-0 flex-1 truncate font-medium">{r.supplier_name || t("Unknown supplier", "অজানা সরবরাহকারী")}</Link>
                    <span className="num shrink-0">{r.total ?? "-"} <span className="text-xs text-muted">{r.currency}</span></span>
                  </span>
                  <span className="mt-0.5 block text-[13px] text-muted"><span className="num">{r.invoice_number || "-"}</span> · {t("due", "শেষ তারিখ")} <span className="num">{r.due_date || "-"}</span> · <span className="num">{r.account || t("no account", "অ্যাকাউন্ট নেই")}</span></span>
                </span>
              </li>
            ))}
          </ul>
          <div className="hidden overflow-x-auto md:block">
            <table className="tbl text-sm">
              <thead><tr><th className="w-10"><span className="sr-only">{t("Select", "বাছুন")}</span></th><th>{t("Supplier", "সরবরাহকারী")}</th><th>{t("Invoice", "ইনভয়েস")}</th><th>{t("Due", "শেষ তারিখ")}</th><th>{t("Account", "অ্যাকাউন্ট")}</th><th>{t("Approved by", "অনুমোদন করেছেন")}</th><th className="r">{t("Amount", "পরিমাণ")}</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={clsx(picked.has(r.id) && "[&>td]:bg-infowash")}>
                    <td><input type="checkbox" checked={picked.has(r.id)} onChange={() => toggle(r.id)} aria-label={t(`Pay ${r.supplier_name} ${r.invoice_number}`, `${r.supplier_name} ${r.invoice_number} পরিশোধ`)} className="h-4 w-4 accent-[var(--c-brand)]" /></td>
                    <td><Link href={`/invoices/${r.id}`} className="font-medium hover:text-brand hover:underline">{r.supplier_name || t("Unknown supplier", "অজানা সরবরাহকারী")}</Link></td>
                    <td className="num text-[13px]">{r.invoice_number || "-"}</td>
                    <td className="num whitespace-nowrap text-[13px]">{r.due_date || "-"}</td>
                    <td className="num text-[13px]">{r.account || <span className="font-sans text-accent-ink">{t("none", "নেই")}</span>}{r.account && !r.iban && <span className="ml-1 font-sans text-xs text-muted">{t("not IBAN", "IBAN নয়")}</span>}</td>
                    <td className="text-muted">{r.approved_by || "-"}</td>
                    <td className="r num whitespace-nowrap">{r.total ?? "-"} <span className="text-xs text-muted">{r.currency}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Panel title={t("Payment files", "পেমেন্ট ফাইল")} meta={batches.data?.length ? `${batches.data.length}` : undefined} className="mt-6">
        {!batches.data?.length ? <p className="px-4 py-4 text-sm text-muted">{t("No payment files yet.", "এখনো কোনো পেমেন্ট ফাইল নেই।")}</p> : (
          <ul>
            {batches.data.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-rule px-4 py-3 text-sm last:border-0">
                <span className="num min-w-0 flex-1 truncate">{b.filename}</span>
                <span className="text-muted">{t(`${b.invoice_count} ${b.invoice_count === 1 ? "payment" : "payments"}`, `${b.invoice_count}টি পেমেন্ট`)}</span>
                <span className="num">{Object.entries(b.totals).map(([c, v]) => `${v} ${c}`).join(", ")}</span>
                <span className="text-muted">{b.created_by}, {new Date(b.created_at).toLocaleString()}</span>
                <Button variant="ghost" onClick={() => download(b.id, b.filename)} aria-label={t(`Download ${b.filename}`, `${b.filename} ডাউনলোড`)}><Download size={15} aria-hidden /> {t("Download", "ডাউনলোড")}</Button>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}
