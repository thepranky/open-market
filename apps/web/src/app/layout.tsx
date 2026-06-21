import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Serif, IBM_Plex_Mono } from "next/font/google";
import { NavBar } from "@/components/NavBar";
import { ConditionalFooter } from "@/components/ConditionalFooter";
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
      <body className={`${plexSans.variable} ${plexSerif.variable} ${plexMono.variable} font-sans min-h-screen flex flex-col overflow-x-hidden bg-canvas text-ink antialiased`}>
        <NavBar />
        <main className="flex-1 min-h-0">{children}</main>
        <ConditionalFooter />
      </body>
    </html>
  );
}
