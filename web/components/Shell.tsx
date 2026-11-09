"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import Nav from "@/components/Nav";
import { getSession, type Session } from "@/lib/session";

export function useSession() {
  const [s, setS] = useState<Session | null | undefined>(undefined);
  useEffect(() => {
    const read = () => setS(getSession());
    read();
    window.addEventListener("docintel-session", read);
    window.addEventListener("storage", read);
    return () => { window.removeEventListener("docintel-session", read); window.removeEventListener("storage", read); };
  }, []);
  return s;
}

export default function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const session = useSession();
  const onLogin = path === "/login";

  useEffect(() => {
    if (session === null && !onLogin) router.replace(`/login?next=${encodeURIComponent(path)}`);
  }, [session, onLogin, path, router]);

  if (onLogin) return <main id="main">{children}</main>;
  if (!session) return <div className="min-h-screen bg-ground" aria-busy="true" />;
  return (
    <>
      <Nav session={session} />
      <div className="lg:pl-60">
        <main id="main" className="mx-auto max-w-[1180px] px-4 pt-6 pb-16 sm:px-8 lg:pt-9">{children}</main>
      </div>
    </>
  );
}
