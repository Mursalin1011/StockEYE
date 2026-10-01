import type { Metadata } from "next";
import Link from "next/link";
import { NavLinks } from "@/components/NavLinks";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "StockEYE", template: "%s · StockEYE" },
  description: "DSE stock screener: your strategies, explained daily.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        <header className="sticky top-0 z-20 border-b border-line bg-surface/90 backdrop-blur">
          <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
            <Link href="/" className="text-lg font-semibold tracking-tight">
              Stock<span className="text-accent">EYE</span>
            </Link>
            <NavLinks />
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
        <footer className="border-t border-line py-4 text-center text-xs text-muted">
          Screening output from your own rules. Not investment advice. Charts by{" "}
          <a className="underline" href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noreferrer">
            TradingView Lightweight Charts
          </a>
          .
        </footer>
      </body>
    </html>
  );
}
