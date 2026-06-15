"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "./ThemeToggle";

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5 rounded-sm">
      <span className="relative inline-flex items-center justify-center" style={{ width: 20, height: 20 }}>
        <span className="absolute inset-0 rounded-full border-2 border-brand" />
        <span className="absolute bg-brand" style={{ width: 2, height: 20 }} />
        <span className="absolute bg-brand rounded-full" style={{ width: 5.5, height: 5.5 }} />
      </span>
      <span className="font-serif font-medium text-ink" style={{ fontSize: 19, letterSpacing: "-0.01em" }}>
        Meridian
      </span>
    </Link>
  );
}

export function NavBar() {
  const pathname = usePathname();
  const links = [
    { href: "/explore",        label: "Explore" },
    { href: "/graph",          label: "Graph" },
    { href: "/jurisdictions",  label: "Thresholds" },
    { href: "/screen",         label: "Screen deal" },
  ];

  return (
    <header className="sticky top-0 z-30 bg-surface border-b border-line" style={{ backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)", backgroundColor: "color-mix(in srgb, var(--surface) 85%, transparent)" }}>
      <div className="mx-auto max-w-content px-6 lg:px-8 h-[58px] flex items-center justify-between">
        <Logo />
        <nav className="flex items-center gap-1">
          {links.map((l) => {
            const active = pathname === l.href || pathname.startsWith(l.href + "/");
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`rounded-[7px] px-3 py-1.5 text-[14px] font-medium whitespace-nowrap transition-colors ${
                  active ? "text-ink bg-slatey-soft" : "text-muted hover:text-ink hover:bg-slatey-soft"
                }`}
              >
                {l.label}
              </Link>
            );
          })}
          <div className="w-px h-5 bg-line mx-2" />
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
