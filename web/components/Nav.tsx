"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { BarChart3, Banknote, FileStack, GitCompareArrows, Inbox, Languages, LogOut, Menu, Moon, ScanSearch, Sun, UploadCloud, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { setSession, toggleTheme, type Session } from "@/lib/session";

const GROUPS = [
  { label: ["Files", "ফাইল"], links: [
    { href: "/", label: ["Upload", "আপলোড"], icon: UploadCloud },
    { href: "/documents", label: ["Documents", "ডকুমেন্ট"], icon: FileStack },
  ] },
  { label: ["Daily work", "রোজকার কাজ"], links: [
    { href: "/review", label: ["To review", "রিভিউ বাকি"], icon: Inbox, count: true },
    { href: "/search", label: ["Search", "খুঁজুন"], icon: ScanSearch },
    { href: "/reconcile", label: ["Match ledger", "লেজার মেলান"], icon: GitCompareArrows },
    { href: "/payments", label: ["Payments", "পেমেন্ট"], icon: Banknote, pay: true },
  ] },
  { label: ["Reports", "রিপোর্ট"], links: [
    { href: "/metrics", label: ["Numbers", "পরিসংখ্যান"], icon: BarChart3 },
  ] },
];

export function Mark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden>
      <rect width="28" height="28" rx="7" fill="#ff6f59" />
      <path d="M8 6h8.6L20.5 9.9V22H8z" fill="#fff" />
      <path d="M16.6 6v3.9h3.9" fill="#ffc4b8" />
      <rect x="10.2" y="12" width="7.8" height="1.5" rx=".75" fill="#bcd2ce" />
      <rect x="9.5" y="15.2" width="9.2" height="3.8" rx=".7" fill="none" stroke="#0b3b3c" strokeWidth="1.4" />
    </svg>
  );
}

function Brand({ dark = true }: { dark?: boolean }) {
  const { t } = useLang();
  return (
    <Link href="/" className="flex items-center gap-2.5 rounded-md">
      <Mark />
      <span className="leading-tight">
        <span className={clsx("block text-sm font-semibold", dark ? "text-white" : "text-ink")}>Hisab Kitab</span>
        <span className={clsx("block text-xs", dark ? "text-[#a6c6c1]" : "text-muted")}>{t("Invoices and payments", "ইনভয়েস ও পেমেন্ট")}</span>
      </span>
    </Link>
  );
}

function Links({ onPick }: { onPick?: () => void }) {
  const path = usePathname();
  const on = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const m = useQuery({ queryKey: ["metrics"], queryFn: () => api<any>("/metrics/summary"), refetchInterval: 10000 });
  const waiting: number | undefined = m.data?.needs_review;
  const unpaid: number | undefined = m.data?.approved_unpaid;
  const { t, lang } = useLang();
  return (
    <nav aria-label="Main">
      {GROUPS.map((g) => (
        <div key={g.label[0]} className="mt-6 first:mt-0">
          <p className="mb-1.5 px-3 text-xs font-medium text-[#88aca6]">{t(g.label[0], g.label[1])}</p>
          <ul className="space-y-0.5">
            {g.links.map(({ href, label, icon: Icon, count, pay }: any) => (
              <li key={href}>
                <Link href={href} onClick={onPick} aria-current={on(href) ? "page" : undefined}
                  className={clsx("relative flex h-9 items-center gap-2.5 rounded-md px-3 text-sm transition-colors max-lg:h-11",
                    on(href) ? "bg-white/10 font-medium text-white" : "text-[#cde2de] hover:bg-white/5 hover:text-white")}>
                  {on(href) && <span className="absolute top-2 bottom-2 left-0 w-[3px] rounded-r bg-[#ff6f59]" aria-hidden />}
                  <Icon size={16} strokeWidth={1.7} aria-hidden className={on(href) ? "text-[#ff6f59]" : "text-[#88aca6]"} />
                  {t(label[0], label[1])}
                  {count && waiting ? (
                    <span className="num ml-auto rounded bg-[#ff6f59] px-1.5 text-xs leading-5 font-medium text-[#0b3b3c]" aria-label={t(`${waiting} invoices to review`, `${waiting}টি ইনভয়েস রিভিউ বাকি`)}>{waiting}</span>
                  ) : null}
                  {pay && unpaid ? (
                    <span className="num ml-auto rounded bg-white/10 px-1.5 text-xs leading-5 text-[#cde2de]" aria-label={t(`${unpaid} approved invoices to pay`, `${unpaid}টি অনুমোদিত ইনভয়েস পরিশোধ বাকি`)}>{unpaid}</span>
                  ) : null}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function Me({ session }: { session: Session }) {
  const { t, lang, setLang } = useLang();
  const [dark, setDark] = useState(false);
  useEffect(() => setDark(document.documentElement.classList.contains("dark")), []);
  return (
    <div className="rounded-lg bg-white/5 p-2.5">
      <div className="flex items-center gap-2.5">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-coral text-xs font-semibold text-[#0b3b3c]" aria-hidden>
          {session.name.split(" ").map((w) => w[0]).slice(0, 2).join("")}
        </span>
        <span className="min-w-0 flex-1 leading-tight">
          <span className="block truncate text-sm font-medium text-white" title={session.name}>{session.name}</span>
          <span className="block text-xs text-[#a6c6c1]">{session.role === "approver" ? t("Approver", "অনুমোদনকারী") : t("Clerk", "ক্লার্ক")}</span>
        </span>
      </div>
      <div className="mt-2 flex items-center gap-1 border-t border-white/10 pt-2">
      <button type="button" onClick={() => setDark(toggleTheme())}
        className="flex h-9 flex-1 items-center justify-center gap-1.5 rounded-md text-xs text-[#cde2de] hover:bg-white/10 hover:text-white max-lg:h-11">
        {dark ? <Sun size={15} aria-hidden /> : <Moon size={15} aria-hidden />} {dark ? t("Light", "লাইট") : t("Dark", "ডার্ক")}
      </button>
      <button type="button" onClick={() => setLang(lang === "bn" ? "en" : "bn")} lang={lang === "bn" ? "en" : "bn"}
        className="flex h-9 flex-1 items-center justify-center gap-1.5 rounded-md text-xs text-[#cde2de] hover:bg-white/10 hover:text-white max-lg:h-11">
        <Languages size={15} aria-hidden /> {lang === "bn" ? "English" : "বাংলা"}
      </button>
      <button type="button" onClick={() => setSession(null)}
        className="flex h-9 flex-1 items-center justify-center gap-1.5 rounded-md text-xs text-[#cde2de] hover:bg-white/10 hover:text-white max-lg:h-11">
        <LogOut size={15} aria-hidden /> {t("Sign out", "সাইন আউট")}
      </button>
      </div>
    </div>
  );
}

export default function Nav({ session }: { session: Session }) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const path = usePathname();
  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-60 flex-col bg-deep px-3 py-5 lg:flex">
        <div className="px-1"><Brand /></div>
        <div className="mt-9 flex-1 overflow-y-auto"><Links /></div>
        <div className="mx-1"><Me session={session} /></div>
      </aside>

      <header className="sticky top-0 z-30 flex h-14 items-center justify-between bg-deep px-4 lg:hidden">
        <Brand />
        <button type="button" onClick={() => setOpen(true)} aria-label={t("Open menu", "মেনু খুলুন")} aria-expanded={open}
          className="grid h-11 w-11 place-items-center rounded-md text-white hover:bg-white/10">
          <Menu size={20} aria-hidden />
        </button>
      </header>

      {open && (
        <div className="fixed inset-0 z-40 flex flex-col bg-deep px-4 pb-6 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="flex h-14 shrink-0 items-center justify-between">
            <Brand />
            <button type="button" onClick={() => setOpen(false)} aria-label={t("Close menu", "মেনু বন্ধ করুন")} className="grid h-11 w-11 place-items-center rounded-md text-white hover:bg-white/10">
              <X size={20} aria-hidden />
            </button>
          </div>
          <div className="mt-4 flex-1 overflow-y-auto"><Links onPick={() => setOpen(false)} /></div>
          <Me session={session} />
        </div>
      )}
    </>
  );
}
