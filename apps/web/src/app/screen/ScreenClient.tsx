"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import type { ScreeningResult, RevenueByScopeInput, ScreeningRequest } from "@/lib/types";

// ── Default FX rates (approx. 2025 rates: units of local currency per 1 USD) ─

const DEFAULT_FX: Record<string, number> = {
  EUR: 0.92, GBP: 0.79, CNY: 7.24, CAD: 1.37, BRL: 5.10,
  JPY: 150.0, KRW: 1370.0, INR: 84.0, AUD: 1.53, ZAR: 18.5,
  TRY: 32.0, MXN: 17.0, PLN: 4.0, ILS: 3.7, AED: 3.67,
  SAR: 3.75, NTD: 32.0, ARS: 1050.0, NGN: 1600.0, NZD: 1.63,
  RUB: 90.0, COP: 4200.0, KES: 130.0, EGP: 50.0, SGD: 1.35,
};

// ── Types ─────────────────────────────────────────────────────────────────────

interface PartyFields {
  worldwide: string;
  eu_eea: string;
  uk: string;
  us: string;
  domestic: string;
  assets: string;
  byCountry: { code: string; amount: string }[];
}

function emptyParty(): PartyFields {
  return { worldwide: "", eu_eea: "", uk: "", us: "", domestic: "", assets: "", byCountry: [] };
}

function parseNum(s: string): number | undefined {
  const n = parseFloat(s.replace(/,/g, ""));
  return isNaN(n) ? undefined : n;
}

function partyToScope(p: PartyFields): RevenueByScopeInput {
  const by_country: Record<string, number> = {};
  for (const row of p.byCountry) {
    const code = row.code.trim().toLowerCase();
    const amt = parseNum(row.amount);
    if (code && amt != null) by_country[code] = amt;
  }
  return {
    worldwide: parseNum(p.worldwide),
    eu_eea: parseNum(p.eu_eea),
    uk: parseNum(p.uk),
    us: parseNum(p.us),
    domestic: parseNum(p.domestic),
    by_country: Object.keys(by_country).length > 0 ? by_country : undefined,
  };
}

// ── Form section / input primitives ──────────────────────────────────────────

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-[12px] font-medium text-ink mb-1">{children}</label>;
}

function NumInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <input
      type="text"
      inputMode="decimal"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder ?? "—"}
      className="w-full rounded-[7px] border border-line bg-canvas px-3 py-1.5 text-[13px] text-ink placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand"
    />
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-[13px] font-semibold text-ink uppercase tracking-wide mb-3 mt-6 first:mt-0">
      {children}
    </h3>
  );
}

// ── Party inputs ──────────────────────────────────────────────────────────────

function PartyInputs({
  label,
  fields,
  onChange,
  currency,
}: {
  label: string;
  fields: PartyFields;
  onChange: (f: PartyFields) => void;
  currency: string;
}) {
  const set = (key: keyof PartyFields, val: string) =>
    onChange({ ...fields, [key]: val });

  const setCountry = (i: number, key: "code" | "amount", val: string) => {
    const rows = fields.byCountry.map((r, j) => (j === i ? { ...r, [key]: val } : r));
    onChange({ ...fields, byCountry: rows });
  };

  const addCountry = () =>
    onChange({ ...fields, byCountry: [...fields.byCountry, { code: "", amount: "" }] });

  const removeCountry = (i: number) =>
    onChange({ ...fields, byCountry: fields.byCountry.filter((_, j) => j !== i) });

  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <p className="text-[13px] font-semibold text-ink mb-3">{label}</p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <div>
          <Label>Worldwide revenue ({currency}m)</Label>
          <NumInput value={fields.worldwide} onChange={(v) => set("worldwide", v)} placeholder="e.g. 8000" />
        </div>
        <div>
          <Label>EU/EEA revenue ({currency}m)</Label>
          <NumInput value={fields.eu_eea} onChange={(v) => set("eu_eea", v)} />
        </div>
        <div>
          <Label>UK revenue ({currency}m)</Label>
          <NumInput value={fields.uk} onChange={(v) => set("uk", v)} />
        </div>
        <div>
          <Label>US revenue ({currency}m)</Label>
          <NumInput value={fields.us} onChange={(v) => set("us", v)} />
        </div>
        <div>
          <Label>
            In-country revenue ({currency}m)
          </Label>
          <NumInput value={fields.domestic} onChange={(v) => set("domestic", v)} placeholder="per jurisdiction" />
          <p className="mt-1 text-[10px] text-faint leading-tight">
            Used as this party&apos;s revenue <em>within</em> each jurisdiction&apos;s territory — applied to Germany for the German test, Brazil for the Brazilian test, etc.
          </p>
        </div>
        <div>
          <Label>Total assets ({currency}m)</Label>
          <NumInput value={fields.assets} onChange={(v) => set("assets", v)} />
        </div>
      </div>

      {/* Per-country rows */}
      {fields.byCountry.length > 0 && (
        <div className="mt-3 space-y-2">
          <p className="text-[11px] text-faint uppercase tracking-wide">Country-specific revenues</p>
          {fields.byCountry.map((row, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                type="text"
                value={row.code}
                onChange={(e) => setCountry(i, "code", e.target.value)}
                placeholder="cc (e.g. in)"
                maxLength={4}
                className="w-20 rounded-[7px] border border-line bg-canvas px-2 py-1.5 text-[13px] text-ink placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand"
              />
              <NumInput
                value={row.amount}
                onChange={(v) => setCountry(i, "amount", v)}
                placeholder={`Revenue (${currency}m)`}
              />
              <button
                onClick={() => removeCountry(i)}
                className="flex-shrink-0 text-faint hover:text-neg transition-colors text-[16px] leading-none"
                title="Remove"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      <button
        onClick={addCountry}
        className="mt-3 text-[12px] text-brand hover:underline"
      >
        + Add country revenue
      </button>
    </div>
  );
}

// ── FX rates panel ────────────────────────────────────────────────────────────

function FxRatesPanel({
  rates,
  onChange,
  baseCurrency,
}: {
  rates: Record<string, string>;
  onChange: (r: Record<string, string>) => void;
  baseCurrency: string;
}) {
  const currencies = Object.keys(DEFAULT_FX).filter((c) => c !== baseCurrency);
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <p className="text-[12px] text-muted mb-3">
        Units of each currency per 1 {baseCurrency}. Pre-populated with approximate 2025 rates — adjust as needed.
      </p>
      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
        {currencies.map((cur) => (
          <div key={cur}>
            <Label>{cur}/{baseCurrency}</Label>
            <NumInput
              value={rates[cur] ?? ""}
              onChange={(v) => onChange({ ...rates, [cur]: v })}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Status + confidence badges ────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  if (status === "triggered") {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[12px] font-semibold bg-neg-soft text-neg">
        Filing required
      </span>
    );
  }
  if (status === "unclear" || status === "data_insufficient") {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[12px] font-semibold bg-[#FFF3CD] text-[#856404]">
        {status === "data_insufficient" ? "Insufficient data" : "Unclear"}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[12px] font-semibold bg-slatey-soft text-slatey">
      No filing
    </span>
  );
}

function ConfidenceDot({ confidence }: { confidence: string }) {
  const cls =
    confidence === "high"
      ? "bg-pos"
      : confidence === "medium"
      ? "bg-[#856404]"
      : "bg-neg";
  return (
    <span className="flex items-center gap-1.5 text-[12px] text-muted">
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${cls}`} />
      {confidence}
    </span>
  );
}

// ── Results table ─────────────────────────────────────────────────────────────

function ResultsTable({ results }: { results: ScreeningResult[] }) {
  const sorted = [...results].sort((a, b) => {
    const order: Record<string, number> = { triggered: 0, unclear: 1, data_insufficient: 2, not_triggered: 3 };
    return (order[a.status] ?? 3) - (order[b.status] ?? 3);
  });

  const filingCount = results.filter((r) => r.status === "triggered").length;
  const unclearCount = results.filter((r) => r.status === "unclear" || r.status === "data_insufficient").length;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <h2 className="text-[16px] font-semibold text-ink">Screening results</h2>
        <span className="text-[12px] bg-neg-soft text-neg px-2 py-0.5 rounded-full font-medium">
          {filingCount} filing{filingCount !== 1 ? "s" : ""}
        </span>
        {unclearCount > 0 && (
          <span className="text-[12px] bg-[#FFF3CD] text-[#856404] px-2 py-0.5 rounded-full font-medium">
            {unclearCount} unclear
          </span>
        )}
        <span className="text-[12px] text-faint">
          {results.length} jurisdictions screened
        </span>
      </div>

      <div className="rounded-xl border border-line overflow-hidden">
        <table className="w-full text-[13px]">
          <thead className="bg-canvas border-b border-line">
            <tr>
              <th className="text-left px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint">Jurisdiction</th>
              <th className="text-left px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint">Status</th>
              <th className="text-left px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint hidden sm:table-cell">Confidence</th>
              <th className="text-left px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint hidden md:table-cell">Triggered tests</th>
              <th className="text-left px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint hidden lg:table-cell">Filing type</th>
              <th className="text-left px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint hidden lg:table-cell"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {sorted.map((r) => (
              <tr
                key={r.jurisdiction_id}
                className={`transition-colors hover:bg-canvas/50 ${r.status === "triggered" ? "bg-neg-soft/20" : ""}`}
              >
                <td className="px-4 py-3">
                  <div className="font-medium text-ink">{r.jurisdiction_name}</div>
                  {r.suspensory && (
                    <div className="text-[11px] text-faint">Suspensory</div>
                  )}
                </td>
                <td className="px-3 py-3">
                  <StatusBadge status={r.status} />
                </td>
                <td className="px-3 py-3 hidden sm:table-cell">
                  <ConfidenceDot confidence={r.confidence} />
                </td>
                <td className="px-3 py-3 hidden md:table-cell">
                  {r.triggered_by.length > 0 ? (
                    <ul className="space-y-0.5">
                      {r.triggered_by.map((tid) => {
                        const t = r.test_results.find((tr) => tr.test_id === tid);
                        return (
                          <li key={tid} className="text-[12px] text-muted">
                            {t?.description ?? tid}
                          </li>
                        );
                      })}
                    </ul>
                  ) : (r.status === "unclear" || r.status === "data_insufficient") ? (
                    <div className="text-[12px] text-[#856404]">
                      {(() => {
                        const missing = r.test_results
                          .flatMap((t) => t.conditions)
                          .filter((c) => c.met === null || c.met === undefined)
                          .map((c) => c.missing_data)
                          .filter((v, i, a) => v && a.indexOf(v) === i);
                        return missing.length > 0
                          ? `Missing: ${missing.join("; ")}`
                          : "Insufficient data to evaluate";
                      })()}
                    </div>
                  ) : (
                    <span className="text-faint">—</span>
                  )}
                </td>
                <td className="px-3 py-3 hidden lg:table-cell text-muted text-[12px]">
                  {r.filing_type ?? "—"}
                </td>
                <td className="px-3 py-3 hidden lg:table-cell">
                  <Link
                    href={`/jurisdictions/${r.jurisdiction_id}`}
                    className="text-[12px] text-brand hover:underline"
                  >
                    View ↗
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {results.some((r) => r.notes.length > 0) && (
        <div className="mt-6 space-y-2">
          {results
            .filter((r) => r.notes.length > 0)
            .map((r) =>
              r.notes.map((note, i) => (
                <div key={`${r.jurisdiction_id}-${i}`} className="flex gap-2.5 rounded-lg border border-line bg-surface px-3 py-2.5 text-[12px] text-muted">
                  <span className="flex-shrink-0 font-medium text-ink">{r.jurisdiction_name}:</span>
                  <span>{note.trim()}</span>
                </div>
              ))
            )}
        </div>
      )}
    </div>
  );
}

// ── Main form ─────────────────────────────────────────────────────────────────

const CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CNY"];

const DEAL_TYPES = [
  { value: "", label: "Unknown / not specified" },
  { value: "merger", label: "Full merger / amalgamation" },
  { value: "share_acquisition", label: "Share / equity acquisition" },
  { value: "asset_acquisition", label: "Asset acquisition" },
  { value: "joint_venture", label: "Full-function joint venture" },
  { value: "minority_stake", label: "Minority stake (non-controlling)" },
] as const;

const ACQUIRER_ORIGINS = [
  { value: "", label: "Unknown" },
  { value: "domestic", label: "Domestic" },
  { value: "eu_eea", label: "EU / EEA" },
  { value: "foreign_non_eu", label: "Foreign (non-EU/EEA)" },
] as const;

export function ScreenClient() {
  const [acquirer, setAcquirer] = useState<PartyFields>(emptyParty());
  const [target, setTarget] = useState<PartyFields>(emptyParty());
  const [dealValue, setDealValue] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [dealType, setDealType] = useState("");
  const [acquirerOrigin, setAcquirerOrigin] = useState("");
  const [fxRates, setFxRates] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(DEFAULT_FX).map(([k, v]) => [k, String(v)]))
  );
  const [showFx, setShowFx] = useState(false);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<ScreeningResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const buildRequest = useCallback((): ScreeningRequest => {
    const fx: Record<string, number> = {};
    for (const [k, v] of Object.entries(fxRates)) {
      const n = parseFloat(v);
      if (!isNaN(n) && n > 0) fx[k] = n;
    }

    // Scale millions → raw values (engine compares against full numbers)
    const scale = (s: RevenueByScopeInput): RevenueByScopeInput => {
      const mul = (v?: number) => (v != null ? v * 1_000_000 : undefined);
      return {
        worldwide: mul(s.worldwide),
        eu_eea: mul(s.eu_eea),
        uk: mul(s.uk),
        us: mul(s.us),
        domestic: mul(s.domestic),
        by_country: s.by_country
          ? Object.fromEntries(Object.entries(s.by_country).map(([k, v]) => [k, v * 1_000_000]))
          : undefined,
      };
    };

    const acqScope = partyToScope(acquirer);
    const tgtScope = partyToScope(target);
    const acqAssets = parseNum(acquirer.assets);
    const tgtAssets = parseNum(target.assets);
    const dv = parseNum(dealValue);

    return {
      acquirer: scale(acqScope),
      target: scale(tgtScope),
      acquirer_assets: acqAssets != null ? acqAssets * 1_000_000 : undefined,
      target_assets: tgtAssets != null ? tgtAssets * 1_000_000 : undefined,
      deal_value: dv != null ? dv * 1_000_000 : undefined,
      deal_currency: currency,
      revenue_currency: currency,
      fx_rates: fx,
    };
  }, [acquirer, target, dealValue, currency, fxRates]);

  const handleSubmit = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResults(null);
    try {
      const req = buildRequest();
      const baseUrl =
        typeof window !== "undefined"
          ? (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
          : "http://localhost:8000";
      const res = await fetch(`${baseUrl}/jurisdictions/screen`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const data = await res.json();
      setResults(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [buildRequest]);

  return (
    <div className="space-y-6">
      {/* Deal basics */}
      <div className="rounded-xl border border-line bg-surface p-4">
        <SectionHeading>Deal basics</SectionHeading>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div>
            <Label>Deal value (millions)</Label>
            <NumInput value={dealValue} onChange={setDealValue} placeholder="e.g. 2500" />
          </div>
          <div>
            <Label>Currency</Label>
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              className="w-full rounded-[7px] border border-line bg-canvas px-3 py-1.5 text-[13px] text-ink focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand"
            >
              {CURRENCIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div>
            <Label>Transaction type</Label>
            <select
              value={dealType}
              onChange={(e) => setDealType(e.target.value)}
              className="w-full rounded-[7px] border border-line bg-canvas px-3 py-1.5 text-[13px] text-ink focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand"
            >
              {DEAL_TYPES.map((d) => (
                <option key={d.value} value={d.value}>{d.label}</option>
              ))}
            </select>
          </div>
          <div>
            <Label>Acquirer origin</Label>
            <select
              value={acquirerOrigin}
              onChange={(e) => setAcquirerOrigin(e.target.value)}
              className="w-full rounded-[7px] border border-line bg-canvas px-3 py-1.5 text-[13px] text-ink focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand"
            >
              {ACQUIRER_ORIGINS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
        </div>
        <p className="mt-3 text-[12px] text-faint leading-relaxed">
          All revenue and asset values should be in the selected currency (millions).
          Transaction type and acquirer origin are used to flag FDI screening requirements.
        </p>
      </div>

      {/* Party inputs */}
      <PartyInputs label="Acquirer" fields={acquirer} onChange={setAcquirer} currency={currency} />
      <PartyInputs label="Target" fields={target} onChange={setTarget} currency={currency} />

      {/* FX rates */}
      <div>
        <button
          onClick={() => setShowFx((v) => !v)}
          className="text-[13px] text-brand hover:underline mb-3"
        >
          {showFx ? "▼" : "▶"} FX rates ({currency} → threshold currencies)
        </button>
        {showFx && (
          <FxRatesPanel rates={fxRates} onChange={setFxRates} baseCurrency={currency} />
        )}
      </div>

      {/* Submit */}
      <div className="flex items-center gap-4">
        <button
          onClick={handleSubmit}
          disabled={loading}
          className="rounded-[8px] bg-brand px-5 py-2 text-[14px] font-medium text-white hover:bg-brand-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? "Screening…" : "Screen deal"}
        </button>
        {loading && (
          <span className="text-[13px] text-muted">Checking 29 jurisdictions…</span>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-neg bg-neg-soft px-4 py-3 text-[13px] text-neg">
          {error}
        </div>
      )}

      {/* Results */}
      {results && (
        <div className="space-y-4">
          {acquirerOrigin === "foreign_non_eu" && results.some((r) => r.status === "triggered") && (
            <div className="rounded-xl border border-[#FFC107]/40 bg-[#FFF9E6] px-4 py-3 text-[13px] text-[#856404]">
              <span className="font-semibold">FDI screening note:</span>{" "}
              The acquirer is identified as a foreign (non-EU/EEA) investor. For each triggered jurisdiction, check whether a parallel FDI or national security screening obligation applies — this is separate from the merger control filing.{" "}
              <span className="text-[12px]">See each jurisdiction&apos;s profile page for FDI regime details.</span>
            </div>
          )}
          {dealType === "minority_stake" && results.some((r) => r.status === "triggered") && (
            <div className="rounded-xl border border-[#0D6EFD]/20 bg-[#EBF3FF] px-4 py-3 text-[13px] text-[#0A3D91]">
              <span className="font-semibold">Minority stake note:</span>{" "}
              Some triggered jurisdictions may not require notification for non-controlling minority stakes.
              Review each jurisdiction&apos;s control threshold — notification typically requires acquisition of decisive influence or control.
            </div>
          )}
          <ResultsTable results={results} />
        </div>
      )}
    </div>
  );
}
