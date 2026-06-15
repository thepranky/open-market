"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { searchSemantic, getGraphSectors } from "@/lib/api";
import type { CaseSearchHit } from "@/lib/types";
import { defnLabel } from "@/lib/utils";

interface SearchFormProps {
  initialQ?: string;
  initialJurisdiction?: string;
  initialSector?: string;
  initialOutcome?: string;
  initialTheory?: string;
  initialYearFrom?: string;
  initialYearTo?: string;
  onSemanticResults?: (hits: CaseSearchHit[]) => void;
  onKeywordMode?: () => void;
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

const DEFINITION_STATUSES = [
  ["defined",   "Market firmly defined"],
  ["left_open", "Definition left open"],
  ["segmented", "Segmented into sub-markets"],
  ["discussed", "Discussed, not delineated"],
] as const;

const CURRENT_YEAR = new Date().getFullYear();

const selectCls = "w-full appearance-none rounded-[8px] border border-line-strong bg-surface pl-3 pr-9 py-2.5 text-[14px] text-ink cursor-pointer hover:border-faint focus:outline-none focus:ring-1 focus:ring-brand transition-colors";
const inputCls  = "w-full rounded-[8px] border border-line-strong bg-surface pl-9 pr-3 py-2.5 text-[14px] text-ink placeholder:text-faint focus:outline-none focus:ring-1 focus:ring-brand transition-colors";
const labelCls  = "block text-[11px] font-semibold uppercase tracking-[0.07em] text-faint mb-2";

const ChevDown = () => (
  <svg width={16} height={16} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-faint" aria-hidden="true"><path d="M4 7l6 6 6-6" /></svg>
);
const SearchIcon = () => (
  <svg width={16} height={16} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" className="absolute left-3 top-1/2 -translate-y-1/2 text-faint pointer-events-none" aria-hidden="true"><path d="M9 16a7 7 0 100-14 7 7 0 000 14zm6 2l-3.5-3.5" /></svg>
);

function StyledSelect({ label, value, onChange, options }: {
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
          {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <ChevDown />
      </div>
    </label>
  );
}

export function SearchForm({
  initialQ = "", initialJurisdiction = "", initialSector = "",
  initialOutcome = "", initialTheory = "", initialYearFrom = "", initialYearTo = "",
  onSemanticResults, onKeywordMode,
}: SearchFormProps) {
  const router = useRouter();
  const [q, setQ]                       = useState(initialQ);
  const [jurisdiction, setJurisdiction] = useState(initialJurisdiction);
  const [sector, setSector]             = useState(initialSector);
  const [outcome, setOutcome]           = useState(initialOutcome);
  const [theory, setTheory]             = useState(initialTheory);
  const [yearFrom, setYearFrom]         = useState(initialYearFrom);
  const [yearTo, setYearTo]             = useState(initialYearTo);
  const [mode, setMode]                 = useState<"keyword" | "semantic">("keyword");
  const [semanticLoading, setSemanticLoading] = useState(false);
  const [sectors, setSectors]           = useState<{ value: string; label: string }[]>([]);

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
    if (get("q",            q))            p.set("q",            get("q", q));
    if (get("jurisdiction", jurisdiction)) p.set("jurisdiction", get("jurisdiction", jurisdiction));
    if (get("sector",       sector))       p.set("sector",       get("sector", sector));
    if (get("outcome",      outcome))      p.set("outcome",      get("outcome", outcome));
    if (get("theory",       theory))       p.set("theory",       get("theory", theory));
    if (get("year_from",    yearFrom))     p.set("year_from",    get("year_from", yearFrom));
    if (get("year_to",      yearTo))       p.set("year_to",      get("year_to", yearTo));
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
      theory: setTheory,
      year_from: setYearFrom,
      year_to: setYearTo,
    };
    setters[key]?.(value);
    if (mode === "keyword") { onKeywordMode?.(); apply({ [key]: value }); }
  }

  function reset() {
    setQ(""); setJurisdiction(""); setSector(""); setOutcome("");
    setTheory(""); setYearFrom(""); setYearTo(""); setMode("keyword");
    onKeywordMode?.();
    router.push("/explore");
  }

  const hasActiveFilters = jurisdiction || sector || outcome || theory || yearFrom || yearTo;

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {/* Mode toggle */}
      <div>
        <span className={labelCls}>Search mode</span>
        <div className="inline-grid rounded-[8px] bg-canvas border border-line p-[3px]" style={{ gridTemplateColumns: "1fr 1fr" }}>
          {(["keyword", "semantic"] as const).map((m) => (
            <button key={m} type="button" onClick={() => { setMode(m); if (m === "keyword") onKeywordMode?.(); }}
              className={`rounded-[6px] px-3 py-1.5 text-[13px] font-medium capitalize transition-all ${
                mode === m ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"
              }`}>
              {m}
            </button>
          ))}
        </div>
        {mode === "semantic" && (
          <p className="mt-1.5 text-[12px] text-faint">Finds cases by meaning — describe a scenario or theory.</p>
        )}
      </div>

      {/* Query */}
      <label className="block">
        <span className={labelCls}>Search</span>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <SearchIcon />
            <input type="text" value={q} onChange={(e) => setQ(e.target.value)}
              placeholder={mode === "semantic" ? "e.g. vertical foreclosure in pharma…" : "wearables, foreclosure…"}
              className={inputCls} />
          </div>
          <button type="submit" disabled={semanticLoading}
            className="bg-brand text-brand-fg text-[14px] font-medium px-3 py-2 rounded-[7px] hover:bg-brand-hover transition-colors disabled:opacity-50">
            {semanticLoading ? "…" : "Go"}
          </button>
        </div>
      </label>

      <StyledSelect label="Jurisdiction" value={jurisdiction} onChange={(v) => handleFilterChange("jurisdiction", v)} options={JURISDICTIONS} />

      <StyledSelect label="Sector" value={sector} onChange={(v) => handleFilterChange("sector", v)}
        options={sectors.length > 0 ? sectors : [{ value: "", label: "All sectors" }]} />

      <StyledSelect label="Outcome" value={outcome} onChange={(v) => handleFilterChange("outcome", v)} options={OUTCOMES} />

      {/* Theory */}
      <label className="block">
        <span className={labelCls}>Theory of harm</span>
        <div className="relative">
          <SearchIcon />
          <input type="text" value={theory} onChange={(e) => setTheory(e.target.value)}
            onBlur={() => mode === "keyword" && handleFilterChange("theory", theory)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); mode === "keyword" && (onKeywordMode?.(), apply({ theory })); } }}
            placeholder="e.g. vertical foreclosure…"
            className={inputCls} />
        </div>
      </label>

      {/* Year range */}
      <div>
        <span className={labelCls}>Decision year</span>
        <div className="flex items-center gap-2">
          <input type="number" value={yearFrom} onChange={(e) => setYearFrom(e.target.value)}
            onBlur={() => mode === "keyword" && apply({ year_from: yearFrom })}
            placeholder="From" min={1990} max={CURRENT_YEAR}
            className="w-full rounded-[8px] border border-line-strong bg-surface px-3 py-2.5 text-[14px] text-ink placeholder:text-faint focus:outline-none focus:ring-1 focus:ring-brand" />
          <span className="text-faint text-xs shrink-0">–</span>
          <input type="number" value={yearTo} onChange={(e) => setYearTo(e.target.value)}
            onBlur={() => mode === "keyword" && apply({ year_to: yearTo })}
            placeholder="To" min={1990} max={CURRENT_YEAR}
            className="w-full rounded-[8px] border border-line-strong bg-surface px-3 py-2.5 text-[14px] text-ink placeholder:text-faint focus:outline-none focus:ring-1 focus:ring-brand" />
        </div>
      </div>

      {hasActiveFilters && (
        <button type="button" onClick={reset}
          className="inline-flex items-center gap-1.5 text-[13px] font-medium text-brand-ink hover:underline">
          <svg width={14} height={14} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 9a5 5 0 119 3M5 9V5M5 9h4" /></svg>
          Reset filters
        </button>
      )}

      {/* Definition status legend */}
      <div className="pt-2 border-t border-line">
        <span className={labelCls}>Definition status</span>
        <div className="space-y-2">
          {DEFINITION_STATUSES.map(([k, label]) => {
            const toneMap = { defined: "bg-pos-soft text-pos-ink", left_open: "bg-ai-soft text-ai-ink", segmented: "bg-seg-soft text-seg-ink", discussed: "bg-slatey-soft text-slatey-ink" } as const;
            return (
              <div key={k} className="flex items-center gap-2.5 text-[13px] text-muted">
                <span className={`inline-flex items-center rounded-[5px] px-2 py-[3px] text-[12px] font-medium leading-none whitespace-nowrap ${toneMap[k]}`}>
                  {defnLabel(k)}
                </span>
                <span>{label}</span>
              </div>
            );
          })}
        </div>
      </div>
    </form>
  );
}
