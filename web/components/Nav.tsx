"use client";
import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  ["/", "Upload"], ["/documents", "Documents"], ["/review", "Review queue"], ["/search", "Search"],
  ["/reconcile", "Reconciliation"], ["/metrics", "Metrics"],
];

export default function Nav() {
  const path = usePathname();
  return (
    <header className="border-b border-line bg-white">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
        <Link href="/" className="font-semibold text-brand">Document Intelligence</Link>
        <nav className="flex flex-wrap gap-1 text-sm">
          {LINKS.map(([href, label]) => {
            const on = href === "/" ? path === "/" : path.startsWith(href);
            return (
              <Link key={href} href={href}
                className={clsx("rounded-md px-3 py-1.5", on ? "bg-brand text-white" : "text-muted hover:bg-paper hover:text-ink")}>
                {label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
