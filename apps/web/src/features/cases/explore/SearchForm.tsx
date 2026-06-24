"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { searchSemantic, getGraphSectors } from "@/features/cases/api";
import type { CaseSearchHit } from "@/lib/types";

interface SearchFormProps {
  initialQ?: string;
  initialJurisdiction?: string;
  initialSector?: string;
  initialOutcome?: string;
  initialYearFrom?: string;
  initialYearTo?: string;
  onSemanticResults?: (hits: CaseSearchHit[]) => void;
  onKeywordMode?: () => void;
  children: React.ReactNode;
}

const JURISDICTIONS = [
  { value: "", label: "All jurisdictions" },
  { value: "EU", label: "EU — European Commission" },
  { value: "UK", label: "UK — CMA" },
  { value: "US", label: "US — DOJ / FTC" },
];

const OUTCOMES = [
  { value: "", label: "All outcomes" },
  { value: "cleared", label: "Cleared" },
  { value: "cleared_with_remedies", label: "Cleared with conditions" },
  { value: "blocked", label: "Blocked" },
  { value: "abandoned", label: "Abandoned" },
  { value: "referred", label: "Referred" },
  { value: "under_appeal", label: "Under appeal" },
  { value: "annulled", label: "Annulled" },
  { value: "upheld_on_appeal", label: "Upheld on appeal" },
  { value: "pending", label: "Pending" },
];

const CURRENT_YEAR = new Date().getFullYear();

const selectCls =
  "w-full appearance-none rounded-lg border border-line bg-surface pl-3 pr-9 py-2 text-[13px] text-ink cursor-pointer hover:border-faint focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand transition-colors";
const labelCls = "block text-[11px] font-semibold uppercase tracking-[0.06em] text-faint mb-1.5";

const ChevDown = () => (
  <svg
    width={14}
    height={14}
    viewBox="0 0 20 20"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    strokeLinecap="round"
    strokeLinejoin="round"
    className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-faint"
    aria-hidden="true"
  >
    <path d="M4 7l6 6 6-6" />
  </svg>
);

function StyledSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="block">
      <span className={labelCls}>{label}</span>
      <div className="relative">
        <select value={value} onChange={(e) => onChange(e.target.value)} className={selectCls}>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevDown />
      </div>
    </label>
  );
}

export function SearchForm({
  initialQ = "",
  initialJurisdiction = "",
  initialSector = "",
  initialOutcome = "",
  initialYearFrom = "",
  initialYearTo = "",
  onSemanticResults,
  onKeywordMode,
  children,
}: SearchFormProps) {
  const router = useRouter();
  const [q, setQ] = useState(initialQ);
  const [jurisdiction, setJurisdiction] = useState(initialJurisdiction);
  const [sector, setSector] = useState(initialSector);
  const [outcome, setOutcome] = useState(initialOutcome);
  const [yearFrom, setYearFrom] = useState(initialYearFrom);
  const [yearTo, setYearTo] = useState(initialYearTo);
  const [mode, setMode] = useState<"keyword" | "semantic">("keyword");
  const [semanticLoading, setSemanticLoading] = useState(false);
  const [sectors, setSectors] = useState<{ value: string; label: string }[]>([]);

  useEffect(() => {
    getGraphSectors()
      .then((data) =>
        setSectors([
          { value: "", label: "All sectors" },
          ...data.map((s) => ({
            value: s.sector,
            label: `${s.sector.charAt(0).toUpperCase() + s.sector.slice(1)} (${s.case_count})`,
          })),
        ])
      )
      .catch(() => {});
  }, []);

  function buildParams(overrides: Record<string, string> = {}) {
    const p = new URLSearchParams();
    const get = (k: string, v: string) => overrides[k] ?? v;
    if (get("q", q)) p.set("q", get("q", q));
    if (get("jurisdiction", jurisdiction)) p.set("jurisdiction", get("jurisdiction", jurisdiction));
    if (get("sector", sector)) p.set("sector", get("sector", sector));
    if (get("outcome", outcome)) p.set("outcome", get("outcome", outcome));
    if (get("year_from", yearFrom)) p.set("year_from", get("year_from", yearFrom));
    if (get("year_to", yearTo)) p.set("year_to", get("year_to", yearTo));
    return p;
  }

  function apply(overrides: Record<string, string> = {}) {
    router.push(`/explore?${buildParams(overrides)}`);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (mode === "semantic") {
      if (!q.trim()) return;
      setSemanticLoading(true);
      searchSemantic(q)
        .then((hits) => onSemanticResults?.(hits))
        .catch(console.error)
        .finally(() => setSemanticLoading(false));
    } else {
      onKeywordMode?.();
      apply();
    }
  }

  function handleFilterChange(key: string, value: string) {
    const setters: Record<string, (v: string) => void> = {
      jurisdiction: setJurisdiction,
      sector: setSector,
      outcome: setOutcome,
      year_from: setYearFrom,
      year_to: setYearTo,
    };
    setters[key]?.(value);
    if (mode === "keyword") {
      onKeywordMode?.();
      apply({ [key]: value });
    }
  }

  function reset() {
    setQ("");
    setJurisdiction("");
    setSector("");
    setOutcome("");
    setYearFrom("");
    setYearTo("");
    setMode("keyword");
    onKeywordMode?.();
    router.push("/explore");
  }

  const hasActiveFilters = jurisdiction || sector || outcome || yearFrom || yearTo;

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* Search bar */}
      <div className="flex items-center gap-2">
        <div className="inline-flex shrink-0 rounded-xl border border-line bg-canvas p-0.5">
          {(["keyword", "semantic"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => {
                setMode(m);
                if (m === "keyword") onKeywordMode?.();
              }}
              className={`rounded-[10px] px-3 py-1.5 text-[12px] font-medium capitalize transition-all ${
                mode === m ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"
              }`}
            >
              {m}
            </button>
          ))}
        </div>

        <div className="flex min-w-0 flex-1 items-center gap-2 rounded-2xl border border-line bg-surface px-3 py-1.5 shadow-sm focus-within:border-brand/40 focus-within:ring-2 focus-within:ring-brand/15">
          <svg
            width={16}
            height={16}
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="shrink-0 text-faint"
            aria-hidden="true"
          >
            <path d="M9 16a7 7 0 100-14 7 7 0 000 14zm6 2l-3.5-3.5" />
          </svg>
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={
              mode === "semantic"
                ? "Describe a scenario or theory of harm…"
                : "Search cases, markets, theories…"
            }
            className="min-h-[36px] flex-1 bg-transparent text-[14px] text-ink placeholder:text-faint focus:outline-none"
          />
          <button
            type="submit"
            disabled={semanticLoading}
            className="shrink-0 rounded-xl bg-brand px-4 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {semanticLoading ? "…" : "Search"}
          </button>
        </div>
      </div>

      {/* Filters + results */}
      <div className="grid gap-8 lg:grid-cols-[200px_minmax(0,1fr)] lg:gap-10">
        <aside className="space-y-4 lg:sticky lg:top-[74px] lg:self-start">
          <StyledSelect
            label="Jurisdiction"
            value={jurisdiction}
            onChange={(v) => handleFilterChange("jurisdiction", v)}
            options={JURISDICTIONS}
          />

          <StyledSelect
            label="Sector"
            value={sector}
            onChange={(v) => handleFilterChange("sector", v)}
            options={sectors.length > 0 ? sectors : [{ value: "", label: "All sectors" }]}
          />

          <StyledSelect
            label="Outcome"
            value={outcome}
            onChange={(v) => handleFilterChange("outcome", v)}
            options={OUTCOMES}
          />

          <div>
            <span className={labelCls}>Decision year</span>
            <div className="flex items-center gap-1.5">
              <input
                type="number"
                value={yearFrom}
                onChange={(e) => setYearFrom(e.target.value)}
                onBlur={() => mode === "keyword" && apply({ year_from: yearFrom })}
                placeholder="From"
                min={1990}
                max={CURRENT_YEAR}
                className="w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-[13px] text-ink placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
              />
              <span className="shrink-0 text-faint text-xs">–</span>
              <input
                type="number"
                value={yearTo}
                onChange={(e) => setYearTo(e.target.value)}
                onBlur={() => mode === "keyword" && apply({ year_to: yearTo })}
                placeholder="To"
                min={1990}
                max={CURRENT_YEAR}
                className="w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-[13px] text-ink placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
              />
            </div>
          </div>

          {hasActiveFilters && (
            <button
              type="button"
              onClick={reset}
              className="inline-flex items-center gap-1.5 text-[12px] font-medium text-brand-ink hover:underline"
            >
              <svg
                width={13}
                height={13}
                viewBox="0 0 20 20"
                fill="none"
                stroke="currentColor"
                strokeWidth={1.6}
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M5 9a5 5 0 119 3M5 9V5M5 9h4" />
              </svg>
              Reset filters
            </button>
          )}

        </aside>

        <section className="min-w-0">{children}</section>
      </div>
    </form>
  );
}
