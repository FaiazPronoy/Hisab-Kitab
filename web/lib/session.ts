export type Session = { token: string; name: string; role: "clerk" | "approver"; username: string; approval_limit: number };
const KEY = "docintel.session";

export function getSession(): Session | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function setSession(s: Session | null) {
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  } catch {}
  window.dispatchEvent(new Event("docintel-session"));
}

export function toggleTheme() {
  const dark = document.documentElement.classList.toggle("dark");
  try { localStorage.setItem("docintel.theme", dark ? "dark" : "light"); } catch {}
  return dark;
}
