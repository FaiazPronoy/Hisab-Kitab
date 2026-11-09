import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export function Button({ variant = "primary", className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  return (
    <button
      type="button"
      {...p}
      className={clsx(
        "inline-flex h-9 items-center justify-center gap-2 rounded-md px-3.5 text-sm font-medium whitespace-nowrap transition-colors active:translate-y-px disabled:pointer-events-none disabled:opacity-45 max-sm:h-11",
        variant === "primary" && "bg-brand text-white hover:bg-brand-dark",
        variant === "ghost" && "border border-control bg-surface text-ink hover:bg-paper",
        variant === "danger" && "bg-red-700 text-white hover:bg-red-800",
        className,
      )}
    />
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("rounded-lg border border-line bg-surface", className)}>{children}</div>;
}

export function Panel({ title, meta, right, children, className }: { title: string; meta?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={clsx("min-w-0 rounded-lg border border-line bg-surface", className)}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-3">
        <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
        {meta && <span className="text-xs text-muted">{meta}</span>}
        {right && <div className="ml-auto">{right}</div>}
      </header>
      {children}
    </section>
  );
}

type Tone = "good" | "warn" | "bad" | "info" | "plain";
const TONES: Record<Tone, string> = {
  good: "bg-goodwash text-good",
  warn: "bg-warnwash text-accent-ink",
  bad: "bg-badwash text-bad",
  info: "bg-infowash text-brand",
  plain: "bg-plainwash text-ink2",
};
const TONE_OF: Record<string, Tone> = {
  done: "good", auto_validated: "good", approved: "good", matched: "good",
  needs_review: "warn", completed_with_errors: "warn", warning: "warn",
  processing: "info", finalizing: "info", queued: "plain", info: "plain",
  failed: "bad", rejected: "bad", error: "bad", critical: "bad",
};

export function Chip({ value, className }: { value: string; className?: string }) {
  const tone = TONE_OF[value] || TONE_OF[value.split(" ").pop() || ""] || "plain";
  return (
    <span className={clsx("inline-flex h-[22px] items-center gap-1.5 rounded px-2 text-xs font-medium whitespace-nowrap", TONES[tone], className)}>
      <span className={clsx("h-1.5 w-1.5 rounded-full", { good: "bg-[#1f8a4c]", warn: "bg-accent", bad: "bg-[#c4242a]", info: "bg-brand", plain: "bg-[#8a919c]" }[tone])} aria-hidden />
      {value.replaceAll("_", " ")}
    </span>
  );
}

export function Confidence({ c, reason, source }: { c: number | null; reason?: string | null; source?: string | null }) {
  if (reason) return <span className="shrink-0 text-xs text-muted">{reason.replaceAll("_", " ")}</span>;
  if (source === "user") return <span className="shrink-0 text-xs font-medium text-brand">corrected</span>;
  if (source === "memory") return <span className="shrink-0 text-xs font-medium text-brand" title="Found with a label learned from an earlier correction">learned</span>;
  if (c == null) return null;
  const p = Math.round(c * 100);
  const low = c < 0.75;
  const mid = c < 0.9;
  if (!mid) return <span className="num w-9 shrink-0 text-right text-xs text-muted" title={`Confidence ${p}%`}>{p}%</span>;
  return (
    <span className="flex shrink-0 items-center gap-1.5" title={`Confidence ${p}%`}>
      <span className="relative h-1 w-8 rounded-full bg-track" aria-hidden>
        <span className={clsx("absolute inset-y-0 left-0 rounded-full", low ? "bg-[#c4242a]" : mid ? "bg-accent" : "bg-brand")} style={{ width: `${p}%` }} />
      </span>
      <span className={clsx("num w-9 text-right text-xs", low ? "text-bad" : mid ? "text-accent-ink" : "text-muted")}>{p}%</span>
    </span>
  );
}

export function Empty({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed border-control bg-surface/60 px-4 py-4 text-sm text-muted">
      <div>{children}</div>
      {action}
    </div>
  );
}

export function Loading({ rows = 4 }: { rows?: number }) {
  return (
    <div className="rounded-lg border border-line bg-surface" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4 border-b border-rule px-4 py-[15px] last:border-0">
          <span className="h-3.5 w-40 rounded bg-rule" />
          <span className="h-3.5 w-24 rounded bg-rule" />
          <span className="ml-auto h-3.5 w-16 rounded bg-rule" />
        </div>
      ))}
    </div>
  );
}

export function ErrorNote({ children, retry }: { children: ReactNode; retry?: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-badline bg-badwash px-4 py-3 text-sm text-bad" role="alert">
      <span>{children}</span>
      {retry && <button type="button" onClick={retry} className="font-medium underline underline-offset-2">Retry</button>}
    </div>
  );
}

export function Spinner() {
  return <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" aria-hidden />;
}

export function PageTitle({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="text-[22px] leading-7 font-semibold tracking-[-0.01em] text-ink sm:text-2xl">{title}</h1>
        {sub && <p className="mt-1 max-w-2xl text-sm text-muted">{sub}</p>}
      </div>
      {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-3 mt-8 flex items-center gap-3">
      <h2 className="text-[15px] font-semibold text-ink">{children}</h2>
      {right && <div className="ml-auto">{right}</div>}
    </div>
  );
}

export function Figures({ items }: { items: { label: string; value: ReactNode; note?: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-2 overflow-hidden rounded-lg border border-line bg-line gap-px sm:grid-cols-3 xl:grid-cols-6">
      {items.map((t) => (
        <div key={t.label} className="bg-surface px-4 py-3.5">
          <dt className="text-xs text-muted">{t.label}</dt>
          <dd className="num mt-1 text-[22px] leading-7 text-ink">{t.value}</dd>
          {t.note && <dd className="mt-0.5 text-xs text-muted">{t.note}</dd>}
        </div>
      ))}
    </dl>
  );
}

export const inputCls = "h-9 rounded-md border border-control bg-surface px-3 text-sm text-ink placeholder:text-faint hover:border-faint focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/15 max-sm:h-11";
