import "./globals.css";
import type { ReactNode } from "react";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import Nav from "@/components/Nav";
import Providers from "@/components/Providers";

const sans = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-plex-sans", display: "swap" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono", display: "swap" });

export const metadata = {
  title: { default: "Document Intelligence", template: "%s | Document Intelligence" },
  description: "Invoice extraction, validation and review",
};

export const viewport = { themeColor: "#10233f" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`} style={{ colorScheme: "light" }}>
      <body className="min-h-screen antialiased">
        <Providers>
          <a href="#main" className="sr-only z-50 rounded-md bg-white px-3 py-2 text-sm font-medium focus:not-sr-only focus:fixed focus:top-3 focus:left-3">Skip to content</a>
          <Nav />
          <div className="lg:pl-60">
            <main id="main" className="mx-auto max-w-[1180px] px-4 pt-6 pb-16 sm:px-8 lg:pt-9">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
