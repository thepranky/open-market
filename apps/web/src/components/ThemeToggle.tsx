"use client";

import { useEffect, useState } from "react";

export function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try { localStorage.setItem("meridian-theme", next ? "dark" : "light"); } catch {}
  }

  return (
    <button
      onClick={toggle}
      title={dark ? "Switch to light mode" : "Switch to dark mode"}
      className="rounded-[7px] p-2 text-muted hover:text-ink hover:bg-slatey-soft transition-colors"
    >
      {dark ? (
        <svg width={17} height={17} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M10 3v2M10 15v2M3 10h2M15 10h2M5 5l1.5 1.5M13.5 13.5L15 15M15 5l-1.5 1.5M6.5 13.5L5 15" />
        </svg>
      ) : (
        <svg width={17} height={17} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M16 11.5A6.5 6.5 0 018.5 4 6.5 6.5 0 1016 11.5z" />
        </svg>
      )}
    </button>
  );
}
