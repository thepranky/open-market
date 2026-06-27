"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { JurisdictionSummary } from "@/lib/types";

export function JurisdictionSidebar({ jurisdictions }: { jurisdictions: JurisdictionSummary[] }) {
  const pathname = usePathname();
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    if (!q) return jurisdictions;
    return jurisdictions.filter(
      (j) =>
        j.jurisdiction_name.toLowerCase().includes(q) ||
        j.jurisdiction_id.toLowerCase().includes(q) ||
        j.authority.toLowerCase().includes(q)
    );
  }, [jurisdictions, query]);

  const sorted = useMemo(
    () => [...filtered].sort((a, b) => a.jurisdiction_name.localeCompare(b.jurisdiction_name)),
    [filtered]
  );

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-3 border-b border-line flex-shrink-0">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search jurisdictions…"
          className="w-full rounded-[7px] border border-line bg-canvas px-3 py-1.5 text-[13px] text-ink placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand"
        />
      </div>

      <nav className="flex-1 overflow-y-auto py-1">
        {sorted.length === 0 && (
          <p className="px-4 py-6 text-[13px] text-faint text-center">No results</p>
        )}
        {sorted.map((j) => {
          const href = `/jurisdictions/${j.jurisdiction_id}`;
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={j.jurisdiction_id}
              href={href}
              className={`flex items-center gap-2.5 mx-1.5 px-2.5 py-2 rounded-[7px] group transition-colors ${
                active
                  ? "bg-brand-soft text-brand"
                  : "text-ink hover:bg-slatey-soft"
              }`}
            >
              <span
                className="flex-shrink-0 w-6 h-6 rounded-[4px] flex items-center justify-center text-[10px] font-bold uppercase"
                style={{
                  background: active ? "var(--brand)" : "var(--line)",
                  color: active ? "#fff" : "var(--slatey)",
                }}
              >
                {j.jurisdiction_id.slice(0, 2).toUpperCase()}
              </span>
              <div className="flex-1 min-w-0">
                <div className={`text-[13px] font-medium truncate ${active ? "text-brand" : "text-ink"}`}>
                  {j.jurisdiction_name}
                </div>
                <div className="text-[11px] text-faint truncate">{j.authority}</div>
              </div>
              {!j.mandatory && (
                <span className="flex-shrink-0 text-[10px] text-slatey bg-slatey-soft px-1.5 py-0.5 rounded-full">
                  vol.
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="px-3 py-2 border-t border-line flex-shrink-0">
        <p className="text-[11px] text-faint text-center">
          {jurisdictions.length} jurisdictions
        </p>
      </div>
    </div>
  );
}
