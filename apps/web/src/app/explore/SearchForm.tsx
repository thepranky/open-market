"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

interface SearchFormProps {
  initialQ?: string;
  initialJurisdiction?: string;
  initialSector?: string;
  initialOutcome?: string;
}

const JURISDICTIONS = [
  { value: "", label: "All jurisdictions" },
  { value: "EU", label: "🇪🇺 EU (European Commission)" },
  { value: "UK", label: "🇬🇧 UK (CMA)" },
  { value: "US", label: "🇺🇸 US (DOJ / FTC)" },
];

const SECTORS = [
  { value: "", label: "All sectors" },
  { value: "digital", label: "Digital / Platforms" },
  { value: "pharma", label: "Pharma / Life Sciences" },
  { value: "airlines", label: "Airlines / Travel" },
  { value: "energy", label: "Energy" },
  { value: "telecoms", label: "Telecoms" },
  { value: "retail", label: "Retail / Grocery" },
  { value: "AI", label: "AI / Chips / Cloud" },
];

const OUTCOMES = [
  { value: "", label: "All outcomes" },
  { value: "cleared", label: "Cleared" },
  { value: "cleared_with_remedies", label: "Cleared with Conditions" },
  { value: "cleared_with_conditions", label: "Cleared with Conditions (EU/UK)" },
  { value: "blocked", label: "Blocked" },
  { value: "abandoned", label: "Abandoned" },
  { value: "referred", label: "Referred" },
  { value: "under_appeal", label: "Under Appeal" },
  { value: "annulled", label: "Annulled" },
  { value: "upheld_on_appeal", label: "Upheld on Appeal" },
  { value: "pending", label: "Pending" },
];

export function SearchForm({
  initialQ = "",
  initialJurisdiction = "",
  initialSector = "",
  initialOutcome = "",
}: SearchFormProps) {
  const router = useRouter();
  const [q, setQ] = useState(initialQ);
  const [jurisdiction, setJurisdiction] = useState(initialJurisdiction);
  const [sector, setSector] = useState(initialSector);
  const [outcome, setOutcome] = useState(initialOutcome);

  function apply(overrides?: Record<string, string>) {
    const params = new URLSearchParams();
    const effectiveQ = overrides?.q ?? q;
    const effectiveJ = overrides?.jurisdiction ?? jurisdiction;
    const effectiveS = overrides?.sector ?? sector;
    const effectiveO = overrides?.outcome ?? outcome;

    if (effectiveQ) params.set("q", effectiveQ);
    if (effectiveJ) params.set("jurisdiction", effectiveJ);
    if (effectiveS) params.set("sector", effectiveS);
    if (effectiveO) params.set("outcome", effectiveO);

    router.push(`/explore?${params.toString()}`);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    apply();
  }

  function handleFilterChange(key: string, value: string) {
    const setters: Record<string, (v: string) => void> = {
      jurisdiction: setJurisdiction,
      sector: setSector,
      outcome: setOutcome,
    };
    setters[key]?.(value);
    apply({ [key]: value });
  }

  function reset() {
    setQ("");
    setJurisdiction("");
    setSector("");
    setOutcome("");
    router.push("/explore");
  }

  const labelClass = "block text-xs font-semibold text-slate-600 mb-1 uppercase tracking-wide";
  const selectClass =
    "w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 bg-white focus:outline-none focus:ring-2 focus:ring-brand-500";

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {/* Keyword search */}
      <div>
        <label className={labelClass}>Search</label>
        <div className="flex gap-2">
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="e.g. wearables, foreclosure…"
            className="flex-1 border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
          <button
            type="submit"
            className="bg-brand-600 hover:bg-brand-700 text-white text-sm font-medium px-3 py-2 rounded-lg transition-colors"
          >
            Go
          </button>
        </div>
      </div>

      {/* Jurisdiction */}
      <div>
        <label className={labelClass}>Jurisdiction</label>
        <select
          value={jurisdiction}
          onChange={(e) => handleFilterChange("jurisdiction", e.target.value)}
          className={selectClass}
        >
          {JURISDICTIONS.map((j) => (
            <option key={j.value} value={j.value}>
              {j.label}
            </option>
          ))}
        </select>
      </div>

      {/* Sector */}
      <div>
        <label className={labelClass}>Sector</label>
        <select
          value={sector}
          onChange={(e) => handleFilterChange("sector", e.target.value)}
          className={selectClass}
        >
          {SECTORS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>

      {/* Outcome */}
      <div>
        <label className={labelClass}>Outcome</label>
        <select
          value={outcome}
          onChange={(e) => handleFilterChange("outcome", e.target.value)}
          className={selectClass}
        >
          {OUTCOMES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <button
        type="button"
        onClick={reset}
        className="text-xs text-slate-400 hover:text-slate-600 underline"
      >
        Reset filters
      </button>
    </form>
  );
}
