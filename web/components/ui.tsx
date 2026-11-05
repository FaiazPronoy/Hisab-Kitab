import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export function Button({ variant = "primary", className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  return (
    <button
      {...p}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand",
        variant === "primary" && "bg-brand text-white hover:bg-brand-dark",
        variant === "ghost" && "border border-line bg-white text-ink hover:bg-paper",
        variant === "danger" && "bg-red-600 text-white hover:bg-red-700",
        className,
      )}
    />
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("rounded-lg border border-line bg-white", className)}>{children}</div>;
}

const TONE: Record<string, string> = {
  done: "bg-green-50 text-green-800 border-green-200", auto_validated: "bg-green-50 text-green-800 border-green-200",
  approved: "bg-green-100 text-green-900 border-green-300", matched: "bg-green-50 text-green-800 border-green-200",
  needs_review: "bg-amber-50 text-amber-800 border-amber-200", completed_with_errors: "bg-amber-50 text-amber-800 border-amber-200",
  warning: "bg-amber-50 text-amber-800 border-amber-200", processing: "bg-blue-50 text-blue-800 border-blue-200",
  queued: "bg-slate-50 text-slate-700 border-slate-200", failed: "bg-red-50 text-red-800 border-red-200",
  rejected: "bg-red-50 text-red-800 border-red-200", error: "bg-red-50 text-red-800 border-red-200",
  critical: "bg-red-100 text-red-900 border-red-300", info: "bg-slate-50 text-slate-700 border-slate-200",
};

export function Chip({ value, className }: { value: string; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
      TONE[value] || "bg-slate-50 text-slate-700 border-slate-200", className)}>
      {value.replaceAll("_", " ")}
    </span>
  );
}

export function Confidence({ c, reason, source }: { c: number | null; reason?: string | null; source?: string | null }) {
  if (reason) return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{reason.replaceAll("_", " ")}</span>;
  if (source === "user") return <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-800">corrected</span>;
  if (c == null) return null;
  const tone = c >= 0.9 ? "bg-green-50 text-green-800" : c >= 0.75 ? "bg-amber-50 text-amber-800" : "bg-red-50 text-red-800";
  return <span className={clsx("rounded-full px-2 py-0.5 text-xs tabular-nums", tone)}>{Math.round(c * 100)}%</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-line p-10 text-center text-sm text-muted">{children}</div>;
}

export function Spinner() {
  return <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent" aria-hidden />;
}

export function PageTitle({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold text-ink">{title}</h1>
        {sub && <p className="mt-1 text-sm text-muted">{sub}</p>}
      </div>
      {right}
    </div>
  );
}
