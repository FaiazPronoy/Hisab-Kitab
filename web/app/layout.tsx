import "./globals.css";
import type { ReactNode } from "react";
import Nav from "@/components/Nav";
import Providers from "@/components/Providers";

export const metadata = { title: "Document Intelligence", description: "Invoice extraction, validation and review" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <Providers>
          <Nav />
          <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
