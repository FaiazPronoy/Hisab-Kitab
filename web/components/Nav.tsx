"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { BarChart3, FileStack, GitCompareArrows, Inbox, Menu, ScanSearch, UploadCloud, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const GROUPS = [
  { label: "Intake", links: [
    { href: "/", label: "Upload", icon: UploadCloud },
    { href: "/documents", label: "Documents", icon: FileStack },
  ] },
  { label: "Work", links: [
    { href: "/review", label: "Review queue", icon: Inbox, count: true },
    { href: "/search", label: "Search", icon: ScanSearch },
    { href: "/reconcile", label: "Reconciliation", icon: GitCompareArrows },
  ] },
  { label: "Pipeline", links: [
    { href: "/metrics", label: "Metrics", icon: BarChart3 },
  ] },
];

export function Mark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden>
      <rect width="28" height="28" rx="7" fill="#f2a20c" />
      <path d="M8 6h8.6L20.5 9.9V22H8z" fill="#fff" />
      <path d="M16.6 6v3.9h3.9" fill="#fbd38d" />
      <rect x="10.2" y="12" width="7.8" height="1.5" rx=".75" fill="#c7d2e3" />
      <rect x="9.5" y="15.2" width="9.2" height="3.8" rx=".7" fill="none" stroke="#12284a" strokeWidth="1.4" />
    </svg>
  );
}

function Brand({ dark = true }: { dark?: boolean }) {
  return (
    <Link href="/" className="flex items-center gap-2.5 rounded-md">
      <Mark />
      <span className="leading-tight">
        <span className={clsx("block text-sm font-semibold", dark ? "text-white" : "text-ink")}>Document Intelligence</span>
        <span className={clsx("block text-xs", dark ? "text-[#9fb2cf]" : "text-muted")}>Accounts payable</span>
      </span>
    </Link>
  );
}

function Links({ onPick }: { onPick?: () => void }) {
  const path = usePathname();
  const on = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const m = useQuery({ queryKey: ["metrics"], queryFn: () => api<any>("/metrics/summary"), refetchInterval: 10000 });
  const waiting: number | undefined = m.data?.needs_review;
  return (
    <nav aria-label="Main">
      {GROUPS.map((g) => (
        <div key={g.label} className="mt-6 first:mt-0">
          <p className="mb-1.5 px-3 text-xs font-medium text-[#8197b8]">{g.label}</p>
          <ul className="space-y-0.5">
            {g.links.map(({ href, label, icon: Icon, count }) => (
              <li key={href}>
                <Link href={href} onClick={onPick} aria-current={on(href) ? "page" : undefined}
                  className={clsx("relative flex h-9 items-center gap-2.5 rounded-md px-3 text-sm transition-colors max-lg:h-11",
                    on(href) ? "bg-white/10 font-medium text-white" : "text-[#c3cfe2] hover:bg-white/5 hover:text-white")}>
                  {on(href) && <span className="absolute top-2 bottom-2 left-0 w-[3px] rounded-r bg-[#f2a20c]" aria-hidden />}
                  <Icon size={16} strokeWidth={1.7} aria-hidden className={on(href) ? "text-[#f2a20c]" : "text-[#8197b8]"} />
                  {label}
                  {count && waiting ? (
                    <span className="num ml-auto rounded bg-[#f2a20c] px-1.5 text-xs leading-5 font-medium text-[#12284a]" aria-label={`${waiting} invoices waiting`}>{waiting}</span>
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

export default function Nav() {
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
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-60 flex-col bg-navy px-3 py-5 lg:flex">
        <div className="px-1"><Brand /></div>
        <div className="mt-9 flex-1 overflow-y-auto"><Links /></div>
        <div className="mx-1 rounded-lg bg-white/5 p-3">
          <p className="text-xs leading-5 text-[#c3cfe2]">
            A value is kept only when it can be found on the page. Everything else goes to review.
          </p>
        </div>
      </aside>

      <header className="sticky top-0 z-30 flex h-14 items-center justify-between bg-navy px-4 lg:hidden">
        <Brand />
        <button type="button" onClick={() => setOpen(true)} aria-label="Open menu" aria-expanded={open}
          className="grid h-11 w-11 place-items-center rounded-md text-white hover:bg-white/10">
          <Menu size={20} aria-hidden />
        </button>
      </header>

      {open && (
        <div className="fixed inset-0 z-40 flex flex-col bg-navy px-4 pb-6 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="flex h-14 shrink-0 items-center justify-between">
            <Brand />
            <button type="button" onClick={() => setOpen(false)} aria-label="Close menu" className="grid h-11 w-11 place-items-center rounded-md text-white hover:bg-white/10">
              <X size={20} aria-hidden />
            </button>
          </div>
          <div className="mt-4 overflow-y-auto"><Links onPick={() => setOpen(false)} /></div>
        </div>
      )}
    </>
  );
}
