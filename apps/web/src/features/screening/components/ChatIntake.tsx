"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import type { ScreeningRequest } from "@/lib/types";
import { getBaseUrl } from "@/lib/api-client";

// ── Jurisdiction metadata ────────────────────────────────────────────────────

interface JurMeta { id: string; name: string; region: string; flag: string }

const JURISDICTIONS: JurMeta[] = [
  { id: "eu",     name: "EU (EUMR)",        region: "EU",           flag: "🇪🇺" },
  { id: "de",     name: "Germany",           region: "EU",           flag: "🇩🇪" },
  { id: "fr",     name: "France",            region: "EU",           flag: "🇫🇷" },
  { id: "it",     name: "Italy",             region: "EU",           flag: "🇮🇹" },
  { id: "es",     name: "Spain",             region: "EU",           flag: "🇪🇸" },
  { id: "nl",     name: "Netherlands",       region: "EU",           flag: "🇳🇱" },
  { id: "pl",     name: "Poland",            region: "EU",           flag: "🇵🇱" },
  { id: "be",     name: "Belgium",           region: "EU",           flag: "🇧🇪" },
  { id: "se",     name: "Sweden",            region: "EU",           flag: "🇸🇪" },
  { id: "at",     name: "Austria",           region: "EU",           flag: "🇦🇹" },
  { id: "dk",     name: "Denmark",           region: "EU",           flag: "🇩🇰" },
  { id: "fi",     name: "Finland",           region: "EU",           flag: "🇫🇮" },
  { id: "pt",     name: "Portugal",          region: "EU",           flag: "🇵🇹" },
  { id: "ro",     name: "Romania",           region: "EU",           flag: "🇷🇴" },
  { id: "cz",     name: "Czech Republic",    region: "EU",           flag: "🇨🇿" },
  { id: "hu",     name: "Hungary",           region: "EU",           flag: "🇭🇺" },
  { id: "gr",     name: "Greece",            region: "EU",           flag: "🇬🇷" },
  { id: "uk",     name: "United Kingdom",    region: "UK",           flag: "🇬🇧" },
  { id: "us_hsr", name: "United States",     region: "Americas",     flag: "🇺🇸" },
  { id: "ca",     name: "Canada",            region: "Americas",     flag: "🇨🇦" },
  { id: "br",     name: "Brazil",            region: "Americas",     flag: "🇧🇷" },
  { id: "mx",     name: "Mexico",            region: "Americas",     flag: "🇲🇽" },
  { id: "co",     name: "Colombia",          region: "Americas",     flag: "🇨🇴" },
  { id: "cl",     name: "Chile",             region: "Americas",     flag: "🇨🇱" },
  { id: "pe",     name: "Peru",              region: "Americas",     flag: "🇵🇪" },
  { id: "ar",     name: "Argentina",         region: "Americas",     flag: "🇦🇷" },
  { id: "cn",     name: "China",             region: "Asia-Pacific", flag: "🇨🇳" },
  { id: "jp",     name: "Japan",             region: "Asia-Pacific", flag: "🇯🇵" },
  { id: "kr",     name: "South Korea",       region: "Asia-Pacific", flag: "🇰🇷" },
  { id: "in",     name: "India",             region: "Asia-Pacific", flag: "🇮🇳" },
  { id: "au",     name: "Australia",         region: "Asia-Pacific", flag: "🇦🇺" },
  { id: "nz",     name: "New Zealand",       region: "Asia-Pacific", flag: "🇳🇿" },
  { id: "sg",     name: "Singapore",         region: "Asia-Pacific", flag: "🇸🇬" },
  { id: "ph",     name: "Philippines",       region: "Asia-Pacific", flag: "🇵🇭" },
  { id: "id",     name: "Indonesia",         region: "Asia-Pacific", flag: "🇮🇩" },
  { id: "sa",     name: "Saudi Arabia",      region: "MEA",          flag: "🇸🇦" },
  { id: "uae",    name: "UAE",               region: "MEA",          flag: "🇦🇪" },
  { id: "il",     name: "Israel",            region: "MEA",          flag: "🇮🇱" },
  { id: "tr",     name: "Turkey",            region: "MEA",          flag: "🇹🇷" },
  { id: "eg",     name: "Egypt",             region: "MEA",          flag: "🇪🇬" },
  { id: "ng",     name: "Nigeria",           region: "MEA",          flag: "🇳🇬" },
  { id: "ke",     name: "Kenya",             region: "MEA",          flag: "🇰🇪" },
  { id: "za",     name: "South Africa",      region: "MEA",          flag: "🇿🇦" },
  { id: "ch",     name: "Switzerland",       region: "Other",        flag: "🇨🇭" },
  { id: "no",     name: "Norway",            region: "Other",        flag: "🇳🇴" },
  { id: "ru",     name: "Russia",            region: "Other",        flag: "🇷🇺" },
  { id: "tw",     name: "Taiwan",            region: "Other",        flag: "🇹🇼" },
];

const REGIONS = ["EU", "UK", "Americas", "Asia-Pacific", "MEA", "Other"] as const;
const REGION_LABELS: Record<string, string> = {
  EU: "European Union", UK: "United Kingdom", Americas: "Americas",
  "Asia-Pacific": "Asia-Pacific", MEA: "Middle East & Africa", Other: "Other",
};

const DEFAULT_FX: Record<string, number> = {
  EUR: 0.92, GBP: 0.79, CNY: 7.24, CAD: 1.37, BRL: 5.10,
  JPY: 150.0, KRW: 1370.0, INR: 84.0, AUD: 1.53, ZAR: 18.5,
  TRY: 32.0, MXN: 17.0, PLN: 4.0, ILS: 3.7, AED: 3.67,
  SAR: 3.75, NTD: 32.0, ARS: 1050.0, NGN: 1600.0, NZD: 1.63,
  RUB: 90.0, COP: 4200.0, KES: 130.0, EGP: 50.0, SGD: 1.35,
  HUF: 370.0, CZK: 23.0, DKK: 6.9, SEK: 10.5, NOK: 10.8,
  CHF: 0.9, RON: 4.6,
};

// Jurisdictions requiring assets (in addition to revenue) for their thresholds
const NEEDS_ASSETS = new Set(["ca", "eg", "id", "in", "ke", "kr", "mx", "ru", "za"]);

// Jurisdictions where competitive relationship (H/V/conglomerate) affects minority thresholds
const NEEDS_RELATIONSHIP_TYPE = new Set(["br", "cl", "de"]);

// Jurisdictions where banking / sensitive sector flags matter for parallel regimes
const NEEDS_SECTOR_FLAGS = new Set(["ng", "uk", "us_hsr", "in", "cn", "sa", "uae"]);

// Jurisdictions where listed/unlisted distinction matters and may not be captured in chat
const NEEDS_LISTED_STATUS = new Set(["ca", "kr", "mx"]);

// ── Persistence key / version ─────────────────────────────────────────────────
const STORAGE_KEY = "meridian_screen_intake";
const STORAGE_VERSION = 3; // bump when PersistedState shape changes

// ── Types ─────────────────────────────────────────────────────────────────────

interface DealBasics {
  deal_value_m: number | null;
  deal_currency: string;
  deal_type: string | null;
  acquirer_worldwide_m: number | null;
  target_worldwide_m: number | null;
  pct_shares_acquired: number | null;
  post_closing_control: string | null;
  is_passive_investment: boolean | null;
  target_listed: string | null; // "listed" | "unlisted" | null
}

interface DealContext {
  relationship_type: string | null;  // "horizontal" | "vertical" | "non_horizontal" | null
  target_listed: string | null;      // override if not captured in chat
  sector_flags: string[];
}

interface FigureRow { acq: string; tgt: string }
type Stage = "chat" | "jurisdictions" | "context" | "figures";

interface ChatMessage { role: "user" | "assistant"; content: string }

interface PersistedState {
  v: number;
  stage: Stage;
  messages: ChatMessage[];
  basics: DealBasics | null;
  selectedIds: string[];
  dealContext: DealContext;
  rows: Record<string, FigureRow>;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseM(s: string): number | undefined {
  const n = parseFloat(s.replace(/,/g, ""));
  return isNaN(n) ? undefined : n * 1_000_000;
}

const BLANK_CONTEXT: DealContext = { relationship_type: null, target_listed: null, sector_flags: [] };

function loadState(): PersistedState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed?.v !== STORAGE_VERSION) return null; // reset on schema change
    return parsed as PersistedState;
  } catch { return null; }
}

function saveState(s: PersistedState) {
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(s)); } catch { /* ignore */ }
}

function clearState() {
  try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
}

// Determine whether the context stage has anything to ask for the given selection
function needsContextStage(selectedIds: string[], basics: DealBasics | null): boolean {
  const sel = new Set(selectedIds);
  const isMinority = basics?.deal_type === "minority_stake" ||
    basics?.deal_type === "share_acquisition";

  if (!isMinority) {
    return Array.from(NEEDS_SECTOR_FLAGS).some((id) => sel.has(id));
  }

  const needsRelationship = Array.from(NEEDS_RELATIONSHIP_TYPE).some((id) => sel.has(id));
  const needsListed = Array.from(NEEDS_LISTED_STATUS).some((id) => sel.has(id)) && !basics?.target_listed;
  const needsSector = Array.from(NEEDS_SECTOR_FLAGS).some((id) => sel.has(id));

  return needsRelationship || needsListed || needsSector;
}

// ── Stepper ───────────────────────────────────────────────────────────────────

function StepDots({
  stage, hasContext, onJump,
}: { stage: Stage; hasContext: boolean; onJump: (s: Stage) => void }) {
  const steps: [Stage, string][] = hasContext
    ? [["chat", "Deal basics"], ["jurisdictions", "Jurisdictions"], ["context", "Context"], ["figures", "Revenues"]]
    : [["chat", "Deal basics"], ["jurisdictions", "Jurisdictions"], ["figures", "Revenues"]];

  const idx = steps.findIndex(([s]) => s === stage);

  return (
    <nav aria-label="Screening progress" className="flex items-center gap-1">
      {steps.map(([s, label], i) => {
        const done = i < idx;
        const active = i === idx;
        const upcoming = i > idx;
        return (
          <button
            key={s}
            type="button"
            onClick={() => done && onJump(s)}
            disabled={upcoming}
            aria-current={active ? "step" : undefined}
            className={`flex items-center gap-1.5 rounded-full px-2 py-1 transition-all duration-200 ${
              active ? "bg-brand-soft" : done ? "cursor-pointer hover:bg-canvas" : "cursor-default"
            }`}
          >
            <span
              className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold transition-colors ${
                done ? "bg-pos text-white" : active ? "bg-brand text-white shadow-sm" : "border border-line bg-surface text-faint"
              }`}
            >
              {done ? (
                <svg width="10" height="10" viewBox="0 0 12 12" fill="none" aria-hidden>
                  <path d="M2.5 6L5 8.5L9.5 3.5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : i + 1}
            </span>
            <span className={`hidden text-[12px] whitespace-nowrap sm:inline ${
              active ? "font-semibold text-brand" : done ? "font-medium text-ink" : "text-faint"
            }`}>
              {label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}

function StartOverButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title="Start over"
      className="group flex h-8 items-center overflow-hidden rounded-full border border-line bg-surface text-faint transition-all duration-200 hover:border-neg/25 hover:bg-neg-soft/40 hover:text-neg w-8 hover:w-[7.25rem] hover:pl-0 hover:pr-3"
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
          <path d="M3 3v5h5" />
        </svg>
      </span>
      <span className="max-w-0 overflow-hidden whitespace-nowrap text-[12px] font-medium opacity-0 transition-all duration-200 group-hover:max-w-[5.5rem] group-hover:opacity-100">
        Start over
      </span>
    </button>
  );
}

// ── Live deal summary card ─────────────────────────────────────────────────────

interface LiveExtracted {
  deal_value_m: number | null;
  deal_currency: string;
  deal_type: string | null;
  target_listed: string | null;
  pct_shares_acquired: number | null;
  post_closing_control: string | null;
  acquirer_worldwide_m: number | null;
  target_worldwide_m: number | null;
}

const DEAL_TYPE_LABELS: Record<string, string> = {
  merger: "Full acquisition",
  share_acquisition: "Share acquisition",
  asset_acquisition: "Asset deal",
  joint_venture: "Joint venture",
  minority_stake: "Minority stake",
};

const CONTROL_LABELS: Record<string, string> = {
  sole_control: "Sole control",
  joint_control: "Joint control",
  material_influence: "Material influence",
  no_control: "Passive / no control",
};

function formatRevM(m: number | null, cur: string): string | null {
  if (m == null) return null;
  if (m >= 1000) return `${cur} ${(m / 1000).toFixed(m % 1000 === 0 ? 0 : 1)}bn`;
  return `${cur} ${m.toLocaleString()}m`;
}

function DealSummaryCard({ live }: { live: LiveExtracted }) {
  type Pill = { label: string; value: string; muted?: boolean };
  const pills: Pill[] = [];

  if (live.deal_type) pills.push({ label: "Type", value: DEAL_TYPE_LABELS[live.deal_type] ?? live.deal_type });
  if (live.pct_shares_acquired != null) pills.push({ label: "Stake", value: `${live.pct_shares_acquired}%` });
  if (live.post_closing_control) pills.push({ label: "Control", value: CONTROL_LABELS[live.post_closing_control] ?? live.post_closing_control });
  if (live.target_listed) pills.push({ label: "Target", value: live.target_listed === "listed" ? "Listed" : "Private" });
  if (live.deal_value_m != null) pills.push({ label: "Value", value: formatRevM(live.deal_value_m, live.deal_currency) ?? "" });
  const acqRev = formatRevM(live.acquirer_worldwide_m, live.deal_currency);
  const tgtRev = formatRevM(live.target_worldwide_m, live.deal_currency);
  if (acqRev) pills.push({ label: "Acq. rev", value: acqRev });
  if (tgtRev) pills.push({ label: "Tgt. rev", value: tgtRev });

  if (pills.length === 0) return null;

  return (
    <div className="mx-auto mb-2 w-full max-w-2xl shrink-0">
      <div className="rounded-xl border border-line bg-surface px-3 py-2.5">
        <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-faint">Deal so far</p>
        <div className="flex flex-wrap gap-1.5">
          {pills.map((p) => (
            <span key={p.label} className="inline-flex items-center gap-1 rounded-full bg-canvas border border-line px-2.5 py-0.5 text-[12px]">
              <span className="text-faint">{p.label}</span>
              <span className="font-medium text-ink">{p.value}</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Stage 1: Chat ─────────────────────────────────────────────────────────────

const BLANK_LIVE: LiveExtracted = {
  deal_value_m: null, deal_currency: "USD", deal_type: null,
  target_listed: null, pct_shares_acquired: null, post_closing_control: null,
  acquirer_worldwide_m: null, target_worldwide_m: null,
};

function ChatStage({
  messages, onMessagesChange, onComplete, baseUrl,
}: {
  messages: ChatMessage[];
  onMessagesChange: (m: ChatMessage[]) => void;
  onComplete: (basics: DealBasics) => void;
  baseUrl: string;
}) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [live, setLive] = useState<LiveExtracted>(BLANK_LIVE);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const started = messages.length > 0;

  const sendMessage = useCallback(
    async (userText: string, currentMessages: ChatMessage[]) => {
      const newMessages: ChatMessage[] = [
        ...currentMessages,
        { role: "user" as const, content: userText },
      ];
      onMessagesChange(newMessages);
      setInput("");
      setLoading(true);
      try {
        const res = await fetch(`${baseUrl}/jurisdictions/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: newMessages }),
        });
        if (!res.ok) throw new Error(`API error ${res.status}`);
        const data = await res.json();
        const withReply = [...newMessages, { role: "assistant" as const, content: data.message }];
        onMessagesChange(withReply);

        // Update live summary with any newly extracted fields (merge, don't overwrite with nulls)
        if (data.extracted) {
          const e = data.extracted;
          const acqWw = e.acquirer_worldwide_m ?? e.acquirer?.worldwide_m ?? null;
          const tgtWw = e.target_worldwide_m ?? e.target?.worldwide_m ?? null;
          setLive((prev) => ({
            deal_value_m: e.deal_value_m ?? prev.deal_value_m,
            deal_currency: e.deal_currency ?? prev.deal_currency,
            deal_type: e.deal_type ?? prev.deal_type,
            target_listed: e.target_listed ?? prev.target_listed,
            pct_shares_acquired: e.pct_shares_acquired ?? prev.pct_shares_acquired,
            post_closing_control: e.post_closing_control ?? prev.post_closing_control,
            acquirer_worldwide_m: acqWw ?? prev.acquirer_worldwide_m,
            target_worldwide_m: tgtWw ?? prev.target_worldwide_m,
          }));

          if (data.ready && acqWw != null && tgtWw != null) {
            onComplete({
              deal_value_m: e.deal_value_m ?? null,
              deal_currency: e.deal_currency ?? "USD",
              deal_type: e.deal_type ?? null,
              acquirer_worldwide_m: acqWw,
              target_worldwide_m: tgtWw,
              pct_shares_acquired: e.pct_shares_acquired ?? null,
              post_closing_control: e.post_closing_control ?? null,
              is_passive_investment: e.is_passive_investment ?? null,
              target_listed: e.target_listed ?? null,
            });
          }
        }
      } catch {
        onMessagesChange([...currentMessages, { role: "assistant", content: "Sorry, couldn't reach the server." }]);
      } finally {
        setLoading(false);
      }
    },
    [baseUrl, onMessagesChange, onComplete]
  );

  const handleStart = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${baseUrl}/jurisdictions/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: [] }),
      });
      const data = await res.json();
      onMessagesChange([{ role: "assistant", content: data.message }]);
    } catch {
      onMessagesChange([{ role: "assistant", content: "Hi! Tell me about the deal — what's the transaction type and approximate value?" }]);
    } finally {
      setLoading(false);
    }
  }, [baseUrl, onMessagesChange]);

  const handleFileUpload = useCallback(async (file: File) => {
    setUploading(true);
    setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${baseUrl}/jurisdictions/parse-financials`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(err.detail ?? "Upload failed");
      }
      const data = await res.json();
      const entities: Array<{
        name?: string;
        worldwide_revenue_m?: number | null;
        currency?: string;
        year?: number | null;
        total_assets_m?: number | null;
      }> = data.entities ?? [];

      if (entities.length === 0) {
        setUploadError("No financial figures found in the file. Try a different document.");
        return;
      }

      let summary = `📎 Extracted from **${file.name}**:\n`;
      entities.forEach((e, i) => {
        summary += `\n**${e.name ?? `Company ${i + 1}`}**: `;
        if (e.worldwide_revenue_m != null) {
          summary += `${e.currency ?? ""} ${e.worldwide_revenue_m.toLocaleString()}m worldwide revenue`;
          if (e.year) summary += ` (FY${e.year})`;
        } else {
          summary += "revenue not found";
        }
      });
      if (data.notes) summary += `\n\n_${data.notes}_`;
      await sendMessage(summary, messages);
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }, [baseUrl, messages, sendMessage]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    if (!loading && !uploading && started) inputRef.current?.focus();
  }, [messages, loading, uploading, started]);

  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
      <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
        {!started ? (
          <div className="flex h-full items-center justify-center py-8">
            <div className="max-w-sm w-full text-center space-y-4">
              <p className="text-[15px] font-medium text-ink">Screen your deal</p>
              <p className="text-[13px] text-muted">
                Answer a few questions to identify filing obligations, or upload a financial document to auto-fill the numbers.
              </p>
              <div className="flex gap-2 justify-center">
                <button
                  onClick={handleStart}
                  disabled={loading}
                  className="rounded-[8px] bg-brand px-5 py-2.5 text-[14px] font-medium text-white hover:bg-brand-hover disabled:opacity-50 transition-colors"
                >
                  {loading ? "Starting…" : "Start conversation"}
                </button>
                <button
                  onClick={() => fileRef.current?.click()}
                  disabled={uploading}
                  className="rounded-[8px] border border-line bg-surface px-4 py-2.5 text-[14px] font-medium text-ink hover:bg-canvas disabled:opacity-50 transition-colors"
                >
                  {uploading ? "Reading…" : "Upload file"}
                </button>
              </div>
              <p className="text-[11px] text-faint">PDF, Excel (.xlsx), or CSV</p>
            </div>
          </div>
        ) : (
          <div className="flex min-h-full flex-col justify-end py-4">
            <div className="mx-auto w-full max-w-2xl space-y-4">
              {messages.map((m, i) => (
                <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[13px] leading-relaxed ${
                      m.role === "user"
                        ? "bg-brand text-white rounded-br-md"
                        : "bg-surface border border-line text-ink rounded-bl-md"
                    }`}
                  >
                    {m.content}
                  </div>
                </div>
              ))}
              {(loading || uploading) && (
                <div className="flex justify-start">
                  <div className="rounded-2xl rounded-bl-md border border-line bg-surface px-4 py-2.5">
                    <span className="flex items-center gap-1">
                      <span className="mr-1 text-[11px] text-faint">{uploading ? "Reading file…" : ""}</span>
                      {[0, 150, 300].map((d) => (
                        <span key={d} className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted" style={{ animationDelay: `${d}ms` }} />
                      ))}
                    </span>
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          </div>
        )}
      </div>

      {started && <DealSummaryCard live={live} />}

      {uploadError && (
        <div className="mx-auto mb-2 w-full max-w-2xl shrink-0">
          <div className="rounded-lg border border-neg bg-neg-soft px-3 py-2 text-[12px] text-neg">
            {uploadError}
          </div>
        </div>
      )}

      <div className="shrink-0 pb-4 pt-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!started) { if (!loading) handleStart(); return; }
            if (input.trim() && !loading && !uploading) sendMessage(input.trim(), messages);
          }}
          className="mx-auto flex w-full max-w-2xl items-end"
        >
          <div className="flex flex-1 items-center gap-2 rounded-2xl border border-line bg-surface px-2 py-1.5 shadow-sm focus-within:border-brand/40 focus-within:ring-2 focus-within:ring-brand/15">
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              title="Upload PDF or Excel"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl text-faint transition-colors hover:bg-surface hover:text-ink disabled:opacity-40"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            </button>
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={started ? "Type your answer…" : "Start a conversation or upload a file…"}
              disabled={loading || uploading}
              className="min-h-[36px] flex-1 bg-transparent py-1.5 text-[13px] text-ink placeholder:text-faint focus:outline-none disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={loading || uploading || (started && !input.trim())}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-brand text-white transition-colors hover:bg-brand-hover disabled:opacity-40"
              title="Send"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="19" x2="12" y2="5" />
                <polyline points="5 12 12 5 19 12" />
              </svg>
            </button>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.xlsx,.xls,.csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) {
                if (!started) handleStart().then(() => handleFileUpload(f));
                else handleFileUpload(f);
              }
              e.target.value = "";
            }}
          />
        </form>
      </div>
    </div>
  );
}

// ── Stage 2: Jurisdiction selector ────────────────────────────────────────────

function JurisdictionStage({
  selected, onToggle, onComplete, onBack,
}: {
  selected: Set<string>;
  onToggle: (id: string) => void;
  onComplete: () => void;
  onBack: () => void;
}) {
  const [activeRegion, setActiveRegion] = useState<string>("EU");

  const selectRegion = (region: string) => {
    const ids = JURISDICTIONS.filter((j) => j.region === region).map((j) => j.id);
    const allSelected = ids.every((id) => selected.has(id));
    ids.forEach((id) => { if (allSelected !== selected.has(id)) onToggle(id); });
  };

  const toggleAll = () => {
    if (selected.size === JURISDICTIONS.length) {
      JURISDICTIONS.forEach((j) => { if (selected.has(j.id)) onToggle(j.id); });
    } else {
      JURISDICTIONS.forEach((j) => { if (!selected.has(j.id)) onToggle(j.id); });
    }
  };

  const visibleJurs = JURISDICTIONS.filter((j) => j.region === activeRegion);
  const regionAllSelected = (r: string) =>
    JURISDICTIONS.filter((j) => j.region === r).every((j) => selected.has(j.id));

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="py-3 border-b border-line shrink-0 flex items-center justify-between">
        <div>
          <p className="text-[14px] font-semibold text-ink">Which jurisdictions should we screen?</p>
          <p className="text-[12px] text-muted">Select every country where either company has revenue or operations.</p>
        </div>
        <button onClick={toggleAll} className="text-[12px] text-brand hover:underline ml-4 shrink-0">
          {selected.size === JURISDICTIONS.length ? "Deselect all" : "Select all 47"}
        </button>
      </div>

      <div className="flex gap-1 pt-3 shrink-0 overflow-x-auto">
        {REGIONS.map((r) => (
          <button key={r} onClick={() => setActiveRegion(r)}
            className={`px-3 py-1.5 rounded-t-lg text-[12px] font-medium whitespace-nowrap border border-b-0 transition-colors ${
              activeRegion === r ? "bg-surface border-line text-ink" : "bg-canvas border-transparent text-muted hover:text-ink"
            }`}
          >
            {r === "MEA" ? "M.E. & Africa" : r}
            {JURISDICTIONS.filter((j) => j.region === r).some((j) => selected.has(j.id)) && (
              <span className="ml-1 text-brand font-bold">·</span>
            )}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto pt-3 pb-2 border-t border-line">
        <div className="flex items-center justify-between mb-2">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">{REGION_LABELS[activeRegion]}</p>
          <button onClick={() => selectRegion(activeRegion)} className="text-[11px] text-brand hover:underline">
            {regionAllSelected(activeRegion) ? "Deselect all" : "Select all"}
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {visibleJurs.map((j) => (
            <button key={j.id} onClick={() => onToggle(j.id)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[13px] font-medium border transition-all ${
                selected.has(j.id)
                  ? "bg-brand border-brand text-white"
                  : "bg-canvas border-line text-ink hover:border-brand/40"
              }`}
            >
              <span>{j.flag}</span><span>{j.name}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="py-3 border-t border-line bg-canvas flex items-center justify-between shrink-0">
        <div className="flex flex-wrap gap-1.5 max-w-[55%] overflow-hidden">
          {selected.size === 0 && <span className="text-[12px] text-faint">None selected</span>}
          {selected.size > 0 && selected.size <= 6 && Array.from(selected).map((id) => {
            const j = JURISDICTIONS.find((x) => x.id === id);
            return j ? (
              <span key={id} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-brand/10 text-brand text-[12px]">
                {j.flag} {j.name}
                <button onClick={() => onToggle(id)} className="ml-0.5 opacity-60 hover:opacity-100 leading-none">×</button>
              </span>
            ) : null;
          })}
          {selected.size > 6 && (
            <span className="text-[12px] text-brand font-medium">{selected.size} selected</span>
          )}
        </div>
        <div className="flex gap-2 shrink-0">
          <button onClick={onBack} className="text-[13px] text-muted hover:text-ink px-2">← Back</button>
          <button
            onClick={onComplete}
            disabled={selected.size === 0}
            className="rounded-[8px] bg-brand px-4 py-2 text-[13px] font-medium text-white hover:bg-brand-hover disabled:opacity-40 transition-colors"
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Stage 2.5: Deal context (conditional) ────────────────────────────────────

const RELATIONSHIP_OPTIONS = [
  { value: "horizontal", label: "Direct or indirect competitors", sub: "Both companies operate in the same or adjacent markets" },
  { value: "vertical",   label: "Supplier / customer",           sub: "One company buys from or sells to the other" },
  { value: "non_horizontal", label: "No meaningful overlap",     sub: "Unrelated businesses — conglomerate deal" },
];

const SECTOR_OPTIONS = [
  { value: "banking",        label: "Banking or financial services" },
  { value: "defence",        label: "Defence or national security" },
  { value: "media",          label: "Media or broadcasting" },
  { value: "healthcare",     label: "Healthcare or pharmaceuticals" },
  { value: "semiconductor",  label: "Advanced technology / semiconductors" },
];

function ContextStage({
  basics, selectedIds, context, onContextChange, onComplete, onBack,
}: {
  basics: DealBasics;
  selectedIds: string[];
  context: DealContext;
  onContextChange: (c: DealContext) => void;
  onComplete: () => void;
  onBack: () => void;
}) {
  const sel = new Set(selectedIds);
  const isMinority = basics.deal_type === "minority_stake" || basics.deal_type === "share_acquisition";

  const showRelationship = isMinority && Array.from(NEEDS_RELATIONSHIP_TYPE).some((id) => sel.has(id));
  const showListed = Array.from(NEEDS_LISTED_STATUS).some((id) => sel.has(id)) && !basics.target_listed;
  const showSectors = Array.from(NEEDS_SECTOR_FLAGS).some((id) => sel.has(id));

  const relTriggers = ["br", "cl", "de"].filter((id) => sel.has(id))
    .map((id) => JURISDICTIONS.find((j) => j.id === id)?.name).filter(Boolean);
  const sectorTriggers = Array.from(NEEDS_SECTOR_FLAGS).filter((id) => sel.has(id))
    .map((id) => JURISDICTIONS.find((j) => j.id === id)?.name).filter(Boolean);

  const toggleSector = (v: string) => {
    const flags = context.sector_flags.includes(v)
      ? context.sector_flags.filter((f) => f !== v)
      : [...context.sector_flags, v];
    onContextChange({ ...context, sector_flags: flags });
  };

  const canAdvance =
    (!showRelationship || context.relationship_type !== null) &&
    (!showListed || context.target_listed !== null);

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-xl py-6 space-y-8">

          {showRelationship && (
            <section>
              <p className="text-[14px] font-semibold text-ink mb-0.5">
                How does the acquirer relate to the target?
              </p>
              <p className="text-[12px] text-muted mb-3">
                Required for {relTriggers.join(", ")} — relationship type affects which minority thresholds apply.
              </p>
              <div className="space-y-2">
                {RELATIONSHIP_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => onContextChange({ ...context, relationship_type: opt.value })}
                    className={`w-full text-left rounded-xl border px-4 py-3 transition-all ${
                      context.relationship_type === opt.value
                        ? "border-brand bg-brand-soft"
                        : "border-line bg-surface hover:border-brand/40"
                    }`}
                  >
                    <p className={`text-[13px] font-medium ${context.relationship_type === opt.value ? "text-brand" : "text-ink"}`}>
                      {opt.label}
                    </p>
                    <p className="text-[12px] text-muted mt-0.5">{opt.sub}</p>
                  </button>
                ))}
              </div>
            </section>
          )}

          {showListed && (
            <section>
              <p className="text-[14px] font-semibold text-ink mb-0.5">
                Is the target listed on a stock exchange?
              </p>
              <p className="text-[12px] text-muted mb-3">
                Affects notification thresholds in Canada, South Korea, and Mexico.
              </p>
              <div className="flex gap-3">
                {(["listed", "unlisted"] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => onContextChange({ ...context, target_listed: v })}
                    className={`flex-1 rounded-xl border px-4 py-3 text-[13px] font-medium transition-all ${
                      context.target_listed === v
                        ? "border-brand bg-brand-soft text-brand"
                        : "border-line bg-surface text-ink hover:border-brand/40"
                    }`}
                  >
                    {v === "listed" ? "Yes, listed" : "No, private"}
                  </button>
                ))}
              </div>
            </section>
          )}

          {showSectors && (
            <section>
              <p className="text-[14px] font-semibold text-ink mb-0.5">
                Does the target operate in any of these sectors?
              </p>
              <p className="text-[12px] text-muted mb-3">
                {sectorTriggers.join(", ")} have parallel regimes (banking approvals, national security screening) that apply separately from merger control.
              </p>
              <div className="space-y-2">
                {SECTOR_OPTIONS.map((opt) => {
                  const active = context.sector_flags.includes(opt.value);
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => toggleSector(opt.value)}
                      className={`w-full text-left rounded-xl border px-4 py-2.5 transition-all flex items-center gap-3 ${
                        active ? "border-brand bg-brand-soft" : "border-line bg-surface hover:border-brand/40"
                      }`}
                    >
                      <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
                        active ? "bg-brand border-brand" : "border-line"
                      }`}>
                        {active && (
                          <svg width="9" height="9" viewBox="0 0 12 12" fill="none">
                            <path d="M2.5 6L5 8.5L9.5 3.5" stroke="white" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        )}
                      </span>
                      <span className={`text-[13px] font-medium ${active ? "text-brand" : "text-ink"}`}>{opt.label}</span>
                    </button>
                  );
                })}
              </div>
              <p className="text-[11px] text-faint mt-2">Leave unchecked if none apply.</p>
            </section>
          )}
        </div>
      </div>

      <div className="py-3 border-t border-line bg-canvas flex items-center justify-between shrink-0">
        <button onClick={onBack} className="text-[13px] text-muted hover:text-ink px-2">← Back</button>
        <button
          onClick={onComplete}
          disabled={!canAdvance}
          className="rounded-[8px] bg-brand px-5 py-2 text-[13px] font-medium text-white hover:bg-brand-hover disabled:opacity-40 transition-colors"
        >
          Next: Enter revenues →
        </button>
      </div>
    </div>
  );
}

// ── Stage 3: Figures table ────────────────────────────────────────────────────

const EU_IDS = new Set(["eu", "de", "fr", "it", "es", "nl", "pl", "be", "se", "at", "dk", "fi", "pt", "ro", "cz", "hu", "gr"]);
const EU_MEMBERS = new Set(["de", "fr", "it", "es", "nl", "pl", "be", "se", "at", "dk", "fi", "pt", "ro", "cz", "hu", "gr"]);

function FiguresStage({
  basics, selectedIds, rows, onRowChange, onSubmit, onBack,
}: {
  basics: DealBasics;
  selectedIds: string[];
  rows: Record<string, FigureRow>;
  onRowChange: (rows: Record<string, FigureRow>) => void;
  onSubmit: (req: ScreeningRequest) => void;
  onBack: () => void;
}) {
  const cur = basics.deal_currency;
  const set = (key: string, party: "acq" | "tgt", val: string) =>
    onRowChange({ ...rows, [key]: { ...rows[key], [party]: val } });

  const needsEuEea = selectedIds.some((id) => EU_IDS.has(id));
  const needsAssets = selectedIds.filter((id) => NEEDS_ASSETS.has(id));
  const needsDealValue = basics.deal_value_m == null;

  const handleSubmit = () => {
    const acqByCountry: Record<string, number> = {};
    const tgtByCountry: Record<string, number> = {};
    const acqAssetsByCountry: Record<string, number> = {};
    const tgtAssetsByCountry: Record<string, number> = {};

    for (const [key, row] of Object.entries(rows)) {
      if (key === "eu_eea" || key === "uk" || key === "us" || key === "_deal_value") continue;
      if (key.endsWith(":assets")) {
        const jid = key.replace(":assets", "");
        const acq = parseM(row.acq); const tgt = parseM(row.tgt);
        if (acq != null) acqAssetsByCountry[jid] = acq;
        if (tgt != null) tgtAssetsByCountry[jid] = tgt;
        continue;
      }
      const acq = parseM(row.acq); const tgt = parseM(row.tgt);
      if (acq != null) acqByCountry[key] = acq;
      if (tgt != null) tgtByCountry[key] = tgt;
    }

    const euEeaRow = rows["eu_eea"];
    const ukRow = rows["uk"];
    const usRow = rows["us"];
    const dealValueRow = rows["_deal_value"];
    const dealValue = needsDealValue
      ? (dealValueRow ? parseM(dealValueRow.acq) : undefined)
      : (basics.deal_value_m != null ? basics.deal_value_m * 1_000_000 : undefined);

    onSubmit({
      acquirer: {
        worldwide: (basics.acquirer_worldwide_m ?? 0) * 1_000_000,
        eu_eea: euEeaRow ? parseM(euEeaRow.acq) : undefined,
        uk: ukRow ? parseM(ukRow.acq) : undefined,
        us: usRow ? parseM(usRow.acq) : undefined,
        by_country: Object.keys(acqByCountry).length > 0 ? acqByCountry : undefined,
      },
      target: {
        worldwide: (basics.target_worldwide_m ?? 0) * 1_000_000,
        eu_eea: euEeaRow ? parseM(euEeaRow.tgt) : undefined,
        uk: ukRow ? parseM(ukRow.tgt) : undefined,
        us: usRow ? parseM(usRow.tgt) : undefined,
        by_country: Object.keys(tgtByCountry).length > 0 ? tgtByCountry : undefined,
      },
      acquirer_assets_by_country: Object.keys(acqAssetsByCountry).length > 0 ? acqAssetsByCountry : undefined,
      target_assets_by_country: Object.keys(tgtAssetsByCountry).length > 0 ? tgtAssetsByCountry : undefined,
      deal_value: dealValue,
      deal_currency: cur,
      revenue_currency: cur,
      fx_rates: DEFAULT_FX,
      deal_type: basics.deal_type ?? undefined,
      pct_shares_acquired: basics.pct_shares_acquired ?? undefined,
      post_closing_control: basics.post_closing_control ?? undefined,
    });
  };

  type RowDef =
    | { kind: "section"; label: string }
    | { kind: "readonly"; label: string; flag?: string; acqVal: string; tgtVal: string }
    | { kind: "input"; key: string; label: string; flag?: string }
    | { kind: "single"; key: string; label: string; flag?: string };

  const defs: RowDef[] = [];

  defs.push({ kind: "section", label: `Revenue (${cur}m)` });
  defs.push({
    kind: "readonly",
    label: "Worldwide",
    acqVal: basics.acquirer_worldwide_m?.toLocaleString() ?? "—",
    tgtVal: basics.target_worldwide_m?.toLocaleString() ?? "—",
  });
  if (needsEuEea) defs.push({ kind: "input", key: "eu_eea", label: "EU / EEA", flag: "🇪🇺" });
  if (selectedIds.includes("uk")) defs.push({ kind: "input", key: "uk", label: "United Kingdom", flag: "🇬🇧" });
  if (selectedIds.includes("us_hsr")) defs.push({ kind: "input", key: "us", label: "United States", flag: "🇺🇸" });
  for (const id of selectedIds) {
    if (["eu", "uk", "us_hsr"].includes(id)) continue;
    if (EU_MEMBERS.has(id)) {
      const j = JURISDICTIONS.find((x) => x.id === id);
      if (j) defs.push({ kind: "input", key: id, label: j.name, flag: j.flag });
    }
  }
  for (const id of selectedIds) {
    if (["eu", "uk", "us_hsr"].includes(id) || EU_MEMBERS.has(id)) continue;
    const j = JURISDICTIONS.find((x) => x.id === id);
    if (j) defs.push({ kind: "input", key: id, label: j.name, flag: j.flag });
  }

  if (needsAssets.length > 0) {
    defs.push({ kind: "section", label: `Assets (${cur}m)` });
    for (const id of needsAssets) {
      const j = JURISDICTIONS.find((x) => x.id === id);
      if (j) defs.push({ kind: "input", key: `${id}:assets`, label: j.name, flag: j.flag });
    }
  }

  if (needsDealValue) {
    defs.push({ kind: "section", label: "Deal" });
    defs.push({ kind: "single", key: "_deal_value", label: `Deal value (${cur}m)` });
  }

  const inputCls = "w-full rounded-[6px] border border-line bg-canvas px-2 py-1.5 text-[13px] text-ink placeholder:text-faint focus:outline-none focus:ring-1 focus:ring-brand/40 focus:border-brand";

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex-1 overflow-y-auto">
        <table className="w-full text-[13px]">
          <thead className="sticky top-0 bg-canvas border-b border-line z-10">
            <tr>
              <th className="text-left px-6 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint w-52" />
              <th className="text-left px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint">Acquirer</th>
              <th className="text-left px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint">Target</th>
            </tr>
          </thead>
          <tbody>
            {defs.map((def, i) => {
              if (def.kind === "section") {
                return (
                  <tr key={`section-${i}`} className="bg-canvas/40">
                    <td colSpan={3} className="px-6 pt-4 pb-1.5 text-[10px] font-semibold uppercase tracking-widest text-faint border-t border-line">
                      {def.label}
                    </td>
                  </tr>
                );
              }
              if (def.kind === "readonly") {
                return (
                  <tr key={`ro-${i}`} className="border-t border-line">
                    <td className="px-6 py-2.5">
                      <div className="flex items-center gap-2">
                        {def.flag && <span className="text-base">{def.flag}</span>}
                        <span className="font-medium text-ink">{def.label}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-muted">{def.acqVal}</td>
                    <td className="px-3 py-2.5 text-muted">{def.tgtVal}</td>
                  </tr>
                );
              }
              if (def.kind === "single") {
                return (
                  <tr key={def.key} className="border-t border-line">
                    <td className="px-6 py-2">
                      <span className="font-medium text-ink">{def.label}</span>
                    </td>
                    <td className="px-3 py-2" colSpan={2}>
                      <input
                        type="text" inputMode="decimal"
                        value={rows[def.key]?.acq ?? ""}
                        onChange={(e) => set(def.key, "acq", e.target.value)}
                        className={inputCls}
                        style={{ maxWidth: 160 }}
                      />
                    </td>
                  </tr>
                );
              }
              return (
                <tr key={def.key} className="border-t border-line">
                  <td className="px-6 py-2">
                    <div className="flex items-center gap-2">
                      {def.flag && <span className="text-base leading-none">{def.flag}</span>}
                      <span className="font-medium text-ink">{def.label}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <input type="text" inputMode="decimal"
                      value={rows[def.key]?.acq ?? ""}
                      onChange={(e) => set(def.key, "acq", e.target.value)}
                      className={inputCls}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input type="text" inputMode="decimal"
                      value={rows[def.key]?.tgt ?? ""}
                      onChange={(e) => set(def.key, "tgt", e.target.value)}
                      className={inputCls}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="py-3 border-t border-line bg-canvas flex items-center justify-between shrink-0">
        <button onClick={onBack} className="text-[13px] text-muted hover:text-ink">← Back</button>
        <button
          onClick={handleSubmit}
          className="rounded-[8px] bg-brand px-5 py-2 text-[13px] font-medium text-white hover:bg-brand-hover transition-colors"
        >
          Screen deal →
        </button>
      </div>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function buildInitialRows(selectedIds: string[]): Record<string, FigureRow> {
  const rows: Record<string, FigureRow> = {};
  const hasEU = selectedIds.some((id) => EU_IDS.has(id));
  if (hasEU) rows["eu_eea"] = { acq: "", tgt: "" };
  if (selectedIds.includes("uk")) rows["uk"] = { acq: "", tgt: "" };
  if (selectedIds.includes("us_hsr")) rows["us"] = { acq: "", tgt: "" };
  for (const id of selectedIds) {
    if (["eu", "uk", "us_hsr"].includes(id)) continue;
    rows[id] = { acq: "", tgt: "" };
    if (NEEDS_ASSETS.has(id)) rows[`${id}:assets`] = { acq: "", tgt: "" };
  }
  return rows;
}

// ── Main export ────────────────────────────────────────────────────────────────

export function ChatIntake({ onScreeningRequest }: { onScreeningRequest: (req: ScreeningRequest, selectedIds: string[]) => void }) {
  const baseUrl = getBaseUrl();

  const [stage, setStage] = useState<Stage>("chat");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [basics, setBasics] = useState<DealBasics | null>(null);
  const [selectedSet, setSelectedSet] = useState<Set<string>>(() => new Set());
  const [dealContext, setDealContext] = useState<DealContext>(BLANK_CONTEXT);
  const [rows, setRows] = useState<Record<string, FigureRow>>({});
  const [restored, setRestored] = useState(false);

  useEffect(() => {
    const initial = loadState();
    if (initial) {
      setStage(initial.stage);
      setMessages(initial.messages);
      setBasics(initial.basics);
      setSelectedSet(new Set(initial.selectedIds));
      setDealContext(initial.dealContext ?? BLANK_CONTEXT);
      setRows(initial.rows);
    }
    setRestored(true);
  }, []);

  useEffect(() => {
    if (!restored) return;
    saveState({
      v: STORAGE_VERSION,
      stage,
      messages,
      basics,
      selectedIds: Array.from(selectedSet),
      dealContext,
      rows,
    });
  }, [restored, stage, messages, basics, selectedSet, dealContext, rows]);

  const toggleJurisdiction = useCallback((id: string) => {
    setSelectedSet((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  const handleJurisdictionsComplete = useCallback(() => {
    const ids = Array.from(selectedSet);
    setRows(buildInitialRows(ids));
    // Pre-fill target_listed from chat if available
    setDealContext((prev) => ({ ...prev, target_listed: basics?.target_listed ?? prev.target_listed }));
    if (needsContextStage(ids, basics)) {
      setStage("context");
    } else {
      setStage("figures");
    }
  }, [selectedSet, basics]);

  const handleReset = useCallback(() => {
    clearState();
    setStage("chat");
    setMessages([]);
    setBasics(null);
    setSelectedSet(new Set());
    setDealContext(BLANK_CONTEXT);
    setRows({});
  }, []);

  const hasContext = needsContextStage(Array.from(selectedSet), basics);

  const handleFinalSubmit = useCallback((req: ScreeningRequest) => {
    const finalReq: ScreeningRequest = {
      ...req,
      relationship_type: dealContext.relationship_type ?? undefined,
    };
    const ids = Array.from(selectedSet);
    clearState();
    onScreeningRequest(finalReq, ids);
  }, [dealContext, selectedSet, onScreeningRequest]);

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      <div className="flex shrink-0 items-center justify-between gap-6 border-b border-line py-4">
        <div className="min-w-0">
          <h1 className="text-[20px] font-semibold text-ink">Deal screening</h1>
          <p className="mt-0.5 text-[13px] text-muted">
            Identify merger control filing obligations across 47 jurisdictions.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <StepDots stage={stage} hasContext={hasContext} onJump={(s) => setStage(s)} />
          {(stage !== "chat" || messages.length > 0) && (
            <StartOverButton onClick={handleReset} />
          )}
        </div>
      </div>

      <div className="flex flex-1 flex-col min-h-0 overflow-hidden">
        {stage === "chat" && (
          <ChatStage
            messages={messages}
            onMessagesChange={setMessages}
            onComplete={(b) => { setBasics(b); setStage("jurisdictions"); }}
            baseUrl={baseUrl}
          />
        )}

        {stage === "jurisdictions" && (
          <JurisdictionStage
            selected={selectedSet}
            onToggle={toggleJurisdiction}
            onComplete={handleJurisdictionsComplete}
            onBack={() => setStage("chat")}
          />
        )}

        {stage === "context" && basics && (
          <ContextStage
            basics={basics}
            selectedIds={Array.from(selectedSet)}
            context={dealContext}
            onContextChange={setDealContext}
            onComplete={() => setStage("figures")}
            onBack={() => setStage("jurisdictions")}
          />
        )}

        {stage === "figures" && basics && (
          <FiguresStage
            basics={basics}
            selectedIds={Array.from(selectedSet)}
            rows={rows}
            onRowChange={setRows}
            onSubmit={handleFinalSubmit}
            onBack={() => setStage(hasContext ? "context" : "jurisdictions")}
          />
        )}
      </div>
    </div>
  );
}
