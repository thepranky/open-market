import Link from "next/link";
import { getAppStats } from "@/lib/api";
import type { AppStats } from "@/lib/types";

async function StatsStrip() {
  let stats: AppStats | null = null;
  try { stats = await getAppStats(); } catch { /* API down */ }
  if (!stats) return null;

  const items = [
    { value: stats.total_case_count.toLocaleString(), label: "Cases indexed" },
    { value: stats.unique_market_count.toLocaleString(), label: "Product markets" },
    { value: stats.canonical_case_count.toLocaleString(), label: "Source-reviewed" },
    { value: stats.jurisdiction_count.toString(), label: "Jurisdictions" },
  ];

  return (
    <div className="mt-14 grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-8 border-t border-line pt-8 max-w-3xl">
      {items.map((item) => (
        <div key={item.label}>
          <div className="font-serif text-ink leading-none" style={{ fontSize: "clamp(28px, 3.4vw, 40px)" }}>
            {item.value}
          </div>
          <div className="mt-2 text-[13px] text-muted">{item.label}</div>
        </div>
      ))}
    </div>
  );
}

function EntryCard({ icon, title, body, cta, href, primary = false }: {
  icon: React.ReactNode;
  title: string;
  body: string;
  cta: string;
  href: string;
  primary?: boolean;
}) {
  return (
    <Link href={href}
      className={`group flex flex-col h-full rounded-xl p-5 border transition-all ${
        primary
          ? "bg-brand text-brand-fg border-brand"
          : "bg-surface border-line hover:border-line-strong hover:shadow-card"
      }`}>
      <span className={`inline-flex items-center justify-center w-9 h-9 rounded-[9px] mb-4 ${
        primary ? "bg-white/15" : "bg-brand-soft text-brand-ink"
      }`}>
        {icon}
      </span>
      <div className={`text-[16px] font-semibold mb-1.5 ${primary ? "text-brand-fg" : "text-ink"}`}>{title}</div>
      <p className={`text-[13.5px] leading-relaxed mb-4 flex-1 ${primary ? "text-white/80" : "text-muted"}`}>{body}</p>
      <span className={`inline-flex items-center gap-1.5 text-[13.5px] font-medium group-hover:gap-2.5 transition-all ${
        primary ? "text-brand-fg" : "text-brand-ink"
      }`}>
        {cta}
        <svg width={15} height={15} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 10h12M11 5l5 5-5 5" /></svg>
      </span>
    </Link>
  );
}

const SearchIcon = () => (
  <svg width={19} height={19} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M9 16a7 7 0 100-14 7 7 0 000 14zm6 2l-3.5-3.5" />
  </svg>
);
const GraphIcon = () => (
  <svg width={19} height={19} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M10 3v4M10 13v4M5.5 6.5L8 9M12 11l2.5 2.5M5 14a2 2 0 100-4 2 2 0 000 4zm10 0a2 2 0 100-4 2 2 0 000 4zM10 11a2 2 0 100-4 2 2 0 000 4z" />
  </svg>
);
const LayersIcon = () => (
  <svg width={19} height={19} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M10 3l7 4-7 4-7-4 7-4zM3 11l7 4 7-4M3 14l7 4 7-4" />
  </svg>
);

export default async function HomePage() {
  return (
    <div>
      {/* Hero */}
      <section className="mx-auto max-w-content px-6 lg:px-8 pt-16 lg:pt-24 pb-12">
        <div className="max-w-reading">
          <div className="flex items-center gap-2.5 text-[12.5px] text-muted mb-6">
            <span className="font-semibold uppercase tracking-[0.08em] text-faint">Market-definition research</span>
            <span className="w-1 h-1 rounded-full bg-line-strong" />
            <span className="font-mono whitespace-nowrap">EU · UK · US</span>
          </div>

          <h1 className="font-serif text-ink" style={{ fontSize: "clamp(36px, 5.4vw, 60px)", lineHeight: 1.04, letterSpacing: "-0.015em" }}>
            Every market definition,<br />traced to its source.
          </h1>

          <p className="mt-6 text-[18px] leading-relaxed text-muted max-w-2xl">
            Search merger precedent across the European Commission, CMA, and DOJ/FTC.
            Find how regulators defined a market, which theories of harm applied,
            and the exact paragraph that says so.
          </p>

          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Link href="/explore"
              className="inline-flex items-center gap-2 bg-brand text-brand-fg px-5 py-2.5 rounded-[7px] text-[15px] font-medium hover:bg-brand-hover transition-colors shadow-sm">
              Explore cases
              <svg width={15} height={15} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 10h12M11 5l5 5-5 5" /></svg>
            </Link>
            <Link href="/graph"
              className="inline-flex items-center gap-2 bg-surface text-ink border border-line-strong px-5 py-2.5 rounded-[7px] text-[15px] font-medium hover:border-faint hover:bg-canvas transition-colors">
              Market graph
            </Link>
          </div>

          <StatsStrip />
        </div>
      </section>

      {/* Entry points */}
      <section className="mx-auto max-w-content px-6 lg:px-8 pb-10">
        <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-faint mb-4">Start here</p>
        <div className="grid md:grid-cols-3 gap-4">
          <EntryCard
            icon={<SearchIcon />}
            title="Explore cases"
            body="Filter precedent by jurisdiction, sector, and outcome. Source-reviewed records carry full market definitions and paragraph-level citations."
            cta="Open explorer"
            href="/explore"
            primary
          />
          <EntryCard
            icon={<GraphIcon />}
            title="Market graph"
            body="Drill from sector to product market to the cases that defined it. Follow shared markets across transactions and regulators."
            cta="Open graph"
            href="/graph"
          />
          <EntryCard
            icon={<LayersIcon />}
            title="By definition status"
            body="See where a market was firmly defined, left open, segmented, or merely discussed — and how that varied by regulator."
            cta="Browse statuses"
            href="/explore"
          />
        </div>
      </section>

      {/* Disclaimer */}
      <section className="mx-auto max-w-content px-6 lg:px-8 pb-10">
        <div className="rounded-xl border border-ai-soft bg-ai-soft p-5 text-[13.5px] text-ai-ink max-w-2xl">
          <strong>Research aid only.</strong> Meridian is not legal advice. Records may be AI-assisted and may contain errors — verify all propositions against the linked source materials before relying on them in practice.
        </div>
      </section>
    </div>
  );
}
