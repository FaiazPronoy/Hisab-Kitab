"use client";
import clsx from "clsx";
import { Search as SearchIcon, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { Button, Card, Chip, Empty, ErrorNote, PageTitle, Spinner, inputCls } from "@/components/ui";
import { useLang } from "@/lib/i18n";

type F = { q: string; mode: string; supplier: string; currency: string; status: string; date_from: string; date_to: string; min_total: string; max_total: string };
const BLANK: F = { q: "", mode: "hybrid", supplier: "", currency: "", status: "", date_from: "", date_to: "", min_total: "", max_total: "" };
const MODES = [
  { id: "keyword", label: ["Words", "শব্দ"], hint: ["The exact words and numbers", "হুবহু শব্দ আর সংখ্যা"] },
  { id: "semantic", label: ["Meaning", "অর্থ"], hint: ["Similar meaning, not only the same words", "একই অর্থ, শুধু একই শব্দ নয়"] },
  { id: "hybrid", label: ["Both", "দুটোই"], hint: ["Words and meaning together", "শব্দ আর অর্থ একসাথে"] },
];

// ts_headline marks hits with <b>; everything else in the snippet is escaped
function Snippet({ text }: { text: string }) {
  const parts = text.split(/(<b>.*?<\/b>)/g);
  return <>{parts.map((p, i) => (p.startsWith("<b>") ? <mark key={i}>{p.slice(3, -4)}</mark> : <span key={i}>{p}</span>))}</>;
}

export default function Search() {
  const { t } = useLang();
  const [f, setF] = useState<F>(BLANK);
  const [res, setRes] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [more, setMore] = useState(false);

  const run = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    setErr(null);
    const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v.trim()) as [string, string][]);
    try { setRes(await api(`/search?${p}`)); } catch (x: any) { setErr(x.message); } finally { setBusy(false); }
  };

  const inp = (k: keyof F, label: string, type = "text", extra = "") => (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      <input type={type} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} className={clsx(inputCls, "w-full", extra)}
        inputMode={k.endsWith("_total") ? "decimal" : undefined} />
    </label>
  );
  const active = Object.entries(f).filter(([k, v]) => !["q", "mode"].includes(k) && v).length;

  return (
    <>
      <PageTitle title={t("Search", "খুঁজুন")} sub={t("Find invoices by number, supplier or what was bought.", "নম্বর, সরবরাহকারী বা কী কেনা হয়েছে দিয়ে ইনভয়েস খুঁজুন।")} />
      <form onSubmit={run} className="mb-6">
        <Card className="p-3">
          <div className="flex flex-wrap gap-2">
            <div className="relative min-w-0 flex-[1_1_18rem]">
              <SearchIcon size={16} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-faint" aria-hidden />
              <input autoFocus value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} aria-label={t("Search for", "যা খুঁজবেন")} type="search" spellCheck={false} autoComplete="off"
                placeholder={t("INV-1042, a supplier, or office chairs", "INV-1042, সরবরাহকারী, বা অফিস চেয়ার")} className={clsx(inputCls, "w-full pl-9")} />
            </div>
            <div className="flex rounded-md bg-sunken p-0.5 text-sm max-sm:w-full" role="group" aria-label={t("Search by", "যেভাবে খুঁজবেন")}>
              {MODES.map((m) => (
                <button type="button" key={m.id} title={t(m.hint[0], m.hint[1])} aria-pressed={f.mode === m.id} onClick={() => setF({ ...f, mode: m.id })}
                  className={clsx("h-8 flex-1 rounded px-3 transition-colors max-sm:h-10", f.mode === m.id ? "bg-surface font-medium text-ink shadow-[0_1px_2px_rgba(16,24,40,0.06)]" : "text-ink2 hover:text-ink")}>
                  {t(m.label[0], m.label[1])}
                </button>
              ))}
            </div>
            <Button variant="ghost" onClick={() => setMore((v) => !v)} aria-expanded={more} aria-controls="filters">
              <SlidersHorizontal size={15} aria-hidden /> Filters{active ? <span className="num text-xs text-accent-ink">{active}</span> : null}
            </Button>
            <Button type="submit" disabled={busy} className="max-sm:flex-1">{busy && <Spinner />} Search</Button>
          </div>
          {more && (
            <div id="filters" className="mt-3 grid grid-cols-2 gap-3 border-t border-rule pt-3 sm:grid-cols-3 lg:grid-cols-4">
              {inp("supplier", t("Supplier", "সরবরাহকারী"))}{inp("currency", t("Currency", "মুদ্রা"))}
              <label className="flex flex-col gap-1 text-xs text-muted">
                Status
                <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} className={clsx(inputCls, "w-full")}>
                  <option value="">{t("Any status", "যেকোনো অবস্থা")}</option>
                  {["auto_validated", "needs_review", "approved"].map((s) => <option key={s} value={s}>{s.replaceAll("_", " ")}</option>)}
                </select>
              </label>
              {inp("date_from", t("Date from", "তারিখ থেকে"), "date")}{inp("date_to", t("Date to", "তারিখ পর্যন্ত"), "date")}
              {inp("min_total", t("Total at least", "মোট কমপক্ষে"))}{inp("max_total", t("Total at most", "মোট সর্বোচ্চ"))}
              <div className="flex items-end">
                <button type="button" onClick={() => setF({ ...BLANK, q: f.q, mode: f.mode })} className="h-9 text-sm text-brand hover:underline disabled:text-faint" disabled={!active}>Clear filters</button>
              </div>
            </div>
          )}
        </Card>
      </form>

      {err && <div className="mb-4"><ErrorNote>{err}</ErrorNote></div>}
      {!res ? (
        <Empty>{t("Type a number, a supplier or what was bought, then press Search.", "নম্বর, সরবরাহকারী বা কী কেনা হয়েছে লিখে খুঁজুন চাপুন।")}</Empty>
      ) : res.results.length === 0 ? <Empty>{t("Nothing found. Try Meaning or fewer filters.", "কিছু পাওয়া যায়নি। অর্থ দিয়ে বা কম ফিল্টারে চেষ্টা করুন।")}</Empty> : (
        <Card>
          <div className="border-b border-line px-4 py-3 text-sm text-muted"><span className="num text-ink">{res.results.length}</span> {t(res.results.length === 1 ? "result" : "results", "টি ফল")}</div>
          <ul>
            {res.results.map((r: any) => (
              <li key={r.id} className="border-b border-rule last:border-0">
                <Link href={`/invoices/${r.id}`} className="block px-4 py-3 hover:bg-paper">
                  <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="font-medium text-ink">{r.supplier_name || t("Unknown supplier", "অজানা সরবরাহকারী")}</span>
                    <span className="num text-[13px] text-muted">{r.invoice_number || t("no number", "নম্বর নেই")}</span>
                    <span className="num text-[13px] text-muted">{r.invoice_date}</span>
                    <span className="num ml-auto">{r.total ?? "-"} <span className="text-xs text-muted">{r.currency}</span></span>
                    <Chip value={r.status} />
                  </span>
                  <span className="mt-1.5 block text-[13px] leading-5 text-muted">
                    {r.filename && <span className="text-ink">{r.filename}{r.where ? `, ${r.where}` : ""} · </span>}
                    {t("Found by", "যেভাবে পাওয়া")} {r.matched_by.map((x: string) => (x === "keyword" ? t("words", "শব্দ") : x === "semantic" ? t("meaning", "অর্থ") : x)).join(t(" and ", " ও "))}{r.snippet && <>: <Snippet text={r.snippet} /></>}
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
