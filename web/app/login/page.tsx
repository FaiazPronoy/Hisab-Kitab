"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { Mark } from "@/components/Nav";
import { Button, Spinner, inputCls } from "@/components/ui";
import { api } from "@/lib/api";
import { setSession } from "@/lib/session";

const DEMO = process.env.NEXT_PUBLIC_DEMO_LOGINS !== "0";

function Form() {
  const router = useRouter();
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
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <section className="hidden flex-col justify-between bg-navy p-10 text-white lg:flex">
        <div className="flex items-center gap-3"><Mark size={34} /><span className="text-lg font-semibold">Document Intelligence</span></div>
        <div className="max-w-md">
          <h2 className="text-[28px] leading-9 font-semibold tracking-[-0.01em]">Every value on an invoice, with the line it came from.</h2>
          <ul className="mt-6 space-y-3 text-[15px] text-[#c3cfe2]">
            <li>Values are kept only when they can be found on the page.</li>
            <li>Totals, tax, duplicates and changed bank details are checked in code.</li>
            <li>Only doubtful invoices reach a person, and what they fix is remembered.</li>
          </ul>
        </div>
        <p className="text-xs text-[#9fb2cf]">Accounts payable workspace</p>
      </section>
      <section className="flex items-center justify-center bg-ground px-4 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden"><Mark size={32} /><span className="font-semibold">Document Intelligence</span></div>
          <h1 className="text-2xl font-semibold tracking-[-0.01em]">Sign in</h1>
          <p className="mt-1 text-sm text-muted">Corrections and approvals are recorded under your name.</p>
          <form onSubmit={go} className="mt-6 space-y-4">
            <label className="block text-sm text-ink2">Username
              <input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} required className={`${inputCls} mt-1 w-full`} />
            </label>
            <label className="block text-sm text-ink2">Password
              <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" required className={`${inputCls} mt-1 w-full`} />
            </label>
            {err && <p className="text-sm text-bad" role="alert">{err}</p>}
            <Button type="submit" disabled={busy} className="w-full">{busy && <Spinner />} Sign in</Button>
          </form>
          {DEMO && (
            <div className="mt-8 rounded-lg border border-line bg-surface p-4">
              <p className="text-sm font-medium">Demo accounts</p>
              <p className="mt-1 text-xs text-muted">Created by <code className="num">make seed</code>. A clerk can approve invoices under the approval limit; larger ones need an approver.</p>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <Button variant="ghost" onClick={() => go(undefined, "nadia", "demo-clerk")} disabled={busy}>Nadia, clerk</Button>
                <Button variant="ghost" onClick={() => go(undefined, "farhan", "demo-approver")} disabled={busy}>Farhan, approver</Button>
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
