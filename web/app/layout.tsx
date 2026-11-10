import "./globals.css";
import type { ReactNode } from "react";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import Shell from "@/components/Shell";
import Providers from "@/components/Providers";

const sans = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-plex-sans", display: "swap" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono", display: "swap" });

export const metadata = {
  title: { default: "Hisab Kitab", template: "%s | Hisab Kitab" },
  description: "Document intelligence for accounts payable: invoices read, checked, reviewed and paid",
};

export const viewport = { themeColor: "#10233f" };

// runs before paint so a dark-mode user never sees a white flash
const THEME = `try{var t=localStorage.getItem("docintel.theme");if(t==="dark"||(!t&&matchMedia("(prefers-color-scheme: dark)").matches))document.documentElement.classList.add("dark")}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME }} />
      </head>
      <body className="min-h-screen antialiased">
        <Providers>
          <a href="#main" className="sr-only z-50 rounded-md bg-surface px-3 py-2 text-sm font-medium focus:not-sr-only focus:fixed focus:top-3 focus:left-3">Skip to content</a>
          <Shell>{children}</Shell>
        </Providers>
      </body>
    </html>
  );
}
