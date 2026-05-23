import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "CompMap – Market Definition Research",
  description:
    "Open-source market-definition research graph for competition lawyers. " +
    "Search merger precedent across EU, UK, and US.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen flex flex-col bg-white text-slate-900">
        <header className="border-b border-slate-200 bg-white sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
            <Link
              href="/"
              className="text-lg font-semibold text-brand-700 tracking-tight hover:text-brand-900"
            >
              CompMap
            </Link>
            <nav className="flex items-center gap-6 text-sm text-slate-600">
              <Link href="/explore" className="hover:text-slate-900 font-medium">
                Explore
              </Link>
              <a
                href="https://github.com"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-slate-900"
              >
                GitHub
              </a>
            </nav>
          </div>
        </header>

        <main className="flex-1">{children}</main>

        <footer className="border-t border-slate-100 py-6 text-center text-xs text-slate-400">
          CompMap is an open-source research aid. Not legal advice. Records may
          be AI-assisted and may contain errors — verify all propositions against
          source materials.
        </footer>
      </body>
    </html>
  );
}
