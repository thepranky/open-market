import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Serif, IBM_Plex_Mono } from "next/font/google";
import { NavBar } from "@/components/NavBar";
import "./globals.css";

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  style: ["normal", "italic"],
  variable: "--font-plex-sans",
  display: "swap",
});
const plexSerif = IBM_Plex_Serif({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-plex-serif",
  display: "swap",
});
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Meridian — Market Definition Research",
  description:
    "Market-definition research for competition and antitrust lawyers. " +
    "Search merger precedent across EU, UK, and US — every market linked to its source.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Prevent dark-mode flash on load */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{if(localStorage.getItem('meridian-theme')==='dark')document.documentElement.classList.add('dark')}catch(e){}`,
          }}
        />
      </head>
      <body className={`${plexSans.variable} ${plexSerif.variable} ${plexMono.variable} font-sans min-h-screen flex flex-col bg-canvas text-ink antialiased`}>
        <NavBar />
        <main className="flex-1">{children}</main>
        <footer className="mt-16 border-t border-line">
          <div className="mx-auto max-w-content px-6 lg:px-8 py-8 flex flex-wrap items-center justify-between gap-4 text-[13px] text-faint">
            <div className="flex items-center gap-2">
              <span className="font-serif text-muted">Meridian</span>
              <span>·</span>
              <span>Market-definition research</span>
            </div>
            <div className="flex items-center gap-5">
              <span>EU · UK · US precedent</span>
              <span className="text-[12px]">Not legal advice.</span>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
