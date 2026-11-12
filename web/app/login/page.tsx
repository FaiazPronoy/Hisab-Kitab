"use client";
import { Check, FileSearch, Languages, Moon, ShieldCheck, Sun, UserCheck, UserRound } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { Mark } from "@/components/Nav";
import { Button, Spinner, inputCls } from "@/components/ui";
import { api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { setSession, toggleTheme } from "@/lib/session";

const DEMO = process.env.NEXT_PUBLIC_DEMO_LOGINS !== "0";

function Toggles() {
  const { t, lang, setLang } = useLang();
  const [dark, setDark] = useState(false);
  useEffect(() => setDark(document.documentElement.classList.contains("dark")), []);
  const btn = "flex h-9 items-center gap-1.5 rounded-md border border-control bg-surface px-3 text-sm text-ink2 hover:bg-paper max-sm:h-11";
  return (
    <div className="flex gap-2">
      <button type="button" className={btn} onClick={() => setDark(toggleTheme())}>
        {dark ? <Sun size={15} aria-hidden /> : <Moon size={15} aria-hidden />} {dark ? t("Light", "লাইট") : t("Dark", "ডার্ক")}
      </button>
      <button type="button" className={btn} onClick={() => setLang(lang === "bn" ? "en" : "bn")}>
        <Languages size={15} aria-hidden /> {lang === "bn" ? "English" : "বাংলা"}
      </button>
    </div>
  );
}

// a small picture of what the app does: values read from an invoice, each one checked
function Preview() {
  const { t } = useLang();
  const rows: [string, string, string][] = [
    [t("Supplier", "সরবরাহকারী"), "Collins, Brown and Smart", "P1:L1"],
    [t("Invoice no.", "ইনভয়েস নং"), "INV-56200", "P1:L2"],
    [t("Total", "মোট"), "18,321.96 EUR", "P1:L17"],
  ];
  const checks = [t("Total adds up", "যোগফল মিলেছে"), t("Not a copy", "কপি নয়"), t("Same bank account", "একই ব্যাংক অ্যাকাউন্ট")];
  return (
    <div className="w-full max-w-md rounded-xl bg-white p-5 text-[#132221] shadow-[0_20px_50px_rgba(0,0,0,0.25)]">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold">{t("Invoice read", "ইনভয়েস পড়া হয়েছে")}</span>
        <span className="rounded bg-[#ddf0ec] px-2 py-0.5 text-xs font-medium text-[#0f766e]">{t("passed checks", "যাচাই পাস")}</span>
      </div>
      <dl className="mt-4 space-y-2">
        {rows.map(([k, v, line]) => (
          <div key={k} className="flex items-center gap-3 rounded-md border border-[#dbe5e3] px-3 py-2">
            <dt className="w-24 shrink-0 text-xs text-[#4e605d]">{k}</dt>
            <dd className="min-w-0 flex-1 truncate text-sm font-medium">{v}</dd>
            <span className="num shrink-0 rounded bg-[#ffe7e2] px-1.5 text-[11px] text-[#b4402c]" title={t("Line on the page", "পাতার লাইন")}>{line}</span>
          </div>
        ))}
      </dl>
      <ul className="mt-4 flex flex-wrap gap-2">
        {checks.map((c) => (
          <li key={c} className="flex items-center gap-1 rounded-full bg-[#f1f6f5] px-2.5 py-1 text-xs text-[#364846]">
            <Check size={13} className="text-[#0f766e]" aria-hidden /> {c}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Form() {
  const router = useRouter();
  const { t } = useLang();
  const next = useSearchParams().get("next") || "/";
  const [user, setUser] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const go = async (e?: FormEvent, u = user, p = pw) => {
    e?.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api<any>("/auth/login", { method: "POST", body: JSON.stringify({ username: u, password: p }) });
      setSession({ token: r.token, ...r.user, approval_limit: r.approval_limit });
      // only a path on this site: no //host, no backslash that a browser reads as /
      router.replace(next.startsWith("/") && !next.startsWith("//") && !next.includes("\\") ? next : "/");
    } catch (x: any) {
      setErr(x.message === "Wrong username or password." ? t("Wrong username or password.", "ইউজারনেম বা পাসওয়ার্ড ভুল।") : x.message);
    } finally {
      setBusy(false);
    }
  };

  const features = [
    { icon: FileSearch, text: t("Reads PDFs, scans, photos and Excel files.", "PDF, স্ক্যান, ছবি আর Excel ফাইল পড়ে।") },
    { icon: ShieldCheck, text: t("Finds wrong totals, copies and changed bank details.", "ভুল যোগফল, কপি আর বদলানো ব্যাংক তথ্য ধরে।") },
    { icon: UserCheck, text: t("Sends only the unclear invoices to a person.", "শুধু সন্দেহজনক ইনভয়েস মানুষের কাছে পাঠায়।") },
  ];

  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      <section className="relative hidden overflow-hidden bg-deep px-12 py-10 text-white lg:flex lg:flex-col">
        <div className="pointer-events-none absolute -top-32 -right-32 h-96 w-96 rounded-full bg-[#0f766e] opacity-40 blur-3xl" aria-hidden />
        <div className="pointer-events-none absolute -bottom-40 -left-24 h-96 w-96 rounded-full bg-[#ff6f59] opacity-15 blur-3xl" aria-hidden />
        <div className="relative flex items-center gap-3"><Mark size={36} /><span className="text-lg font-semibold">Hisab Kitab</span></div>
        <div className="relative my-auto max-w-lg py-10">
          <h2 className="text-[34px] leading-[42px] font-semibold tracking-[-0.01em]">{t("Read invoices. Check them. Pay them.", "ইনভয়েস পড়ুন। যাচাই করুন। পেমেন্ট দিন।")}</h2>
          <p className="mt-3 text-[16px] leading-7 text-[#cde2de]">
            {t("Hisab Kitab reads your invoices, checks every number and pays only what is right.",
              "হিসাব কিতাব আপনার ইনভয়েস পড়ে, প্রতিটি সংখ্যা যাচাই করে, আর শুধু সঠিকগুলোই পেমেন্ট করে।")}
          </p>
          <ul className="mt-7 space-y-3">
            {features.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3 text-[15px] text-[#e6f0ee]">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-white/10"><Icon size={16} aria-hidden /></span>
                {text}
              </li>
            ))}
          </ul>
          <div className="mt-9"><Preview /></div>
        </div>
      </section>

      <section className="flex flex-col bg-ground px-4 py-6 sm:px-8">
        <div className="flex items-center justify-between lg:justify-end">
          <div className="flex items-center gap-2.5 lg:hidden"><Mark size={30} /><span className="font-semibold">Hisab Kitab</span></div>
          <Toggles />
        </div>
        <div className="mx-auto my-auto w-full max-w-sm py-10">
          <h1 className="text-[28px] leading-9 font-semibold tracking-[-0.01em]">{t("Sign in", "সাইন ইন")}</h1>
          <p className="mt-1 text-sm text-muted">{t("Your name is saved with every fix and approval.", "প্রতিটি সংশোধন আর অনুমোদনের সাথে আপনার নাম থাকে।")}</p>
          <form onSubmit={go} className="mt-6 space-y-4 rounded-xl border border-line bg-surface p-5">
            <label className="block text-sm text-ink2">{t("Username", "ইউজারনেম")}
              <input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} required className={`${inputCls} mt-1 w-full`} />
            </label>
            <label className="block text-sm text-ink2">{t("Password", "পাসওয়ার্ড")}
              <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" required className={`${inputCls} mt-1 w-full`} />
            </label>
            {err && <p className="text-sm text-bad" role="alert">{err}</p>}
            <Button type="submit" disabled={busy} className="w-full">{busy && <Spinner />} {t("Sign in", "সাইন ইন")}</Button>
          </form>
          {DEMO && (
            <div className="mt-6">
              <p className="text-sm font-medium">{t("Try a demo account", "ডেমো অ্যাকাউন্ট দিয়ে দেখুন")}</p>
              <div className="mt-2 grid gap-2">
                {[
                  { u: "nadia", p: "demo-clerk", name: "Nadia", role: t("Clerk: fixes and approves small invoices", "ক্লার্ক: ঠিক করে, ছোট ইনভয়েস অনুমোদন করে") },
                  { u: "farhan", p: "demo-approver", name: "Farhan", role: t("Approver: approves large invoices and pays", "অনুমোদনকারী: বড় ইনভয়েস অনুমোদন ও পেমেন্ট করে") },
                ].map((d) => (
                  <button key={d.u} type="button" disabled={busy} onClick={() => go(undefined, d.u, d.p)}
                    className="flex items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2.5 text-left transition-colors hover:border-brand hover:bg-paper disabled:opacity-50">
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-infowash text-brand"><UserRound size={17} aria-hidden /></span>
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-ink">{d.name}</span>
                      <span className="block text-xs text-muted">{d.role}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

export default function Login() {
  return <Suspense><Form /></Suspense>;
}
