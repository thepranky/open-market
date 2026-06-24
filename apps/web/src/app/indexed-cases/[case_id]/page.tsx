import Link from "next/link";
import { notFound } from "next/navigation";
import { getIndexedCase } from "@/features/cases/api";
import {
  formatDate, formatOutcome, outcomeTone,
  conceptCategoryColor, formatConceptId,
} from "@/lib/utils";
import { Badge } from "@/components/Badge";
import { Juris } from "@/features/cases/components/Juris";
import type { ConceptRef } from "@/lib/types";

interface Props {
  params: Promise<{ case_id: string }>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase tracking-[0.07em] text-faint mb-1">{label}</dt>
      <dd className="text-[15px] text-ink capitalize">{children}</dd>
    </div>
  );
}

function ProvenanceLabel({ provenance }: { provenance: string }) {
  const labels: Record<string, string> = {
    manually_tagged: "manually tagged",
    ai_extracted: "AI",
    yaml_concept_field: "YAML",
  };
  return <span className="text-[11.5px] text-faint">{labels[provenance] ?? provenance.replace(/_/g, " ")}</span>;
}

function ConceptRefRow({ cr }: { cr: ConceptRef }) {
  const catCls = conceptCategoryColor(cr.concept_id);
  const qualityTone = cr.quality_level === "canonical" ? "pos" : "ai" as const;
  return (
    <div className="flex items-center gap-2.5 py-2 border-b border-line last:border-0">
      <span className={`text-[13px] px-2.5 py-[4px] rounded-[6px] font-medium ${catCls}`}>
        {formatConceptId(cr.concept_id)}
      </span>
      <Badge tone={qualityTone}>{cr.quality_level}</Badge>
      <ProvenanceLabel provenance={cr.provenance} />
    </div>
  );
}

export default async function IndexedCaseDetailPage({ params }: Props) {
  const { case_id } = await params;

  let entry;
  try { entry = await getIndexedCase(case_id); } catch { notFound(); }

  return (
    <div className="mx-auto max-w-content px-6 lg:px-8 py-8">
      {/* Breadcrumb */}
      <Link href="/explore"
        className="inline-flex items-center gap-1.5 text-[13.5px] text-muted hover:text-ink mb-6 transition-colors">
        <svg width={15} height={15} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M16 10H4M9 5l-5 5 5 5" /></svg>
        Explore
      </Link>

      {/* Index-entry notice */}
      <div className="rounded-xl border border-ai-soft bg-ai-soft px-5 py-3.5 mb-7 flex items-start gap-3">
        <svg width={16} height={16} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" className="text-ai-ink mt-0.5 shrink-0" aria-hidden="true"><circle cx="10" cy="10" r="7"/><path d="M10 10v4M10 7h.01"/></svg>
        <div className="text-[13.5px] text-ai-ink leading-relaxed">
          <span className="font-semibold">Index entry — metadata only.</span>{" "}
          This record has not yet undergone source-backed extraction. Markets, theories of harm, remedies, and legal propositions are not available here.
        </div>
      </div>

      {/* Header */}
      <div className="flex flex-wrap items-start gap-5 pb-7 border-b border-line">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5 mb-3">
            <Juris code={entry.jurisdiction} />
            <span className="font-mono text-[12px] text-faint">{entry.case_id}</span>
            <span className="inline-flex items-center gap-1.5 text-[11.5px] font-medium text-ai-ink bg-ai-soft rounded-[5px] px-2 py-[3px]">
              Indexed
            </span>
          </div>
          <h1 className="font-serif text-ink" style={{ fontSize: "clamp(28px, 4vw, 42px)", lineHeight: 1.07, letterSpacing: "-0.01em" }}>
            {entry.case_name}
          </h1>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Badge tone={outcomeTone(entry.outcome)} dot>{formatOutcome(entry.outcome)}</Badge>
            <span className="text-[14px] text-muted">{entry.authority} · {formatDate(entry.decision_date)}</span>
          </div>
        </div>
      </div>

      <div className="grid lg:grid-cols-[1fr_340px] gap-8 mt-8">
        {/* Main */}
        <main className="space-y-9 min-w-0">
          {/* Case details */}
          <section>
            <h2 className="text-[19px] font-semibold text-ink tracking-tight mb-4">Case details</h2>
            <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-5">
              <Field label="Authority">{entry.authority}</Field>
              <Field label="Decision date">{formatDate(entry.decision_date)}</Field>
              <Field label="Jurisdiction"><Juris code={entry.jurisdiction} /></Field>
              <Field label="Sector">{entry.sector}</Field>
              <Field label="Case type">{entry.case_type}</Field>
            </dl>
          </section>

          {/* Parties */}
          {entry.parties.length > 0 && (
            <section>
              <h2 className="text-[19px] font-semibold text-ink tracking-tight mb-4">Parties</h2>
              <div className="flex flex-wrap gap-3">
                {entry.parties.map((p) => (
                  <div key={p.name} className="flex items-center gap-3 rounded-[10px] border border-line bg-surface pl-4 pr-3 py-2.5">
                    <span className="text-[15px] font-medium text-ink whitespace-nowrap">{p.name}</span>
                    <span className="text-[11px] font-medium uppercase tracking-[0.06em] text-muted bg-slatey-soft rounded-[5px] px-2 py-[3px] capitalize">{p.role}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Concept refs */}
          {entry.concept_refs.length > 0 && (
            <section>
              <h2 className="text-[19px] font-semibold text-ink tracking-tight mb-1">Concept tags</h2>
              <p className="text-[13px] text-faint mb-4">Manually tagged — not extracted from source documents.</p>
              <div className="rounded-xl border border-line bg-surface px-5 divide-y divide-line">
                {entry.concept_refs.map((cr) => <ConceptRefRow key={cr.concept_id} cr={cr} />)}
              </div>
            </section>
          )}

          {/* Placeholder for source-backed content */}
          <div className="rounded-xl border border-dashed border-line p-6 text-[14px] text-muted">
            <p className="font-semibold text-ink mb-2">Source-backed sections not yet available</p>
            <ul className="space-y-1.5 text-[13.5px]">
              {["Product and geographic markets considered", "Theories of harm", "Remedies and commitments", "Source passages and document citations"].map((item) => (
                <li key={item} className="flex items-center gap-2">
                  <span className="w-1 h-1 rounded-full bg-faint shrink-0" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </main>

        {/* Sidebar */}
        <aside className="space-y-5 lg:sticky lg:top-[74px] self-start">
          {/* AI summary */}
          {entry.ai_summary && (
            <div className="rounded-xl border border-ai-soft bg-ai-soft p-5">
              <div className="flex items-center justify-between mb-2.5">
                <div className="flex items-center gap-2 text-ai-ink">
                  <svg width={16} height={16} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M10 3l1.6 4.4L16 9l-4.4 1.6L10 15l-1.6-4.4L4 9l4.4-1.6L10 3z" /></svg>
                  <span className="text-[13px] font-semibold">Summary</span>
                </div>
                <span className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-ai-ink border border-ai rounded-[4px] px-1.5 py-[2px]" style={{ borderColor: "var(--ai)" }}>AI-generated</span>
              </div>
              <p className="text-[14px] leading-relaxed text-ink whitespace-pre-wrap">
                {entry.ai_summary.trim()}
              </p>
              <p className="mt-3 text-[11.5px] text-ai-ink">Summary only — not source-verified. Confirm against the authority's published decision.</p>
            </div>
          )}

          {/* Source link */}
          {entry.source_url && (
            <div className="bg-surface border border-line rounded-xl p-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-faint mb-3">Authority source</p>
              <a href={entry.source_url} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-[13.5px] font-medium text-brand-ink hover:underline break-all">
                <svg width={16} height={16} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M8 12a3 3 0 004 0l2-2a3 3 0 00-4-4M12 8a3 3 0 00-4 0l-2 2a3 3 0 004 4" /></svg>
                {entry.authority} case page
              </a>
            </div>
          )}

          {/* Record status */}
          <div className="bg-surface border border-line rounded-xl p-5">
            <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-faint mb-3">Record status</p>
            <div className="space-y-2.5">
              <div className="flex items-center justify-between text-[13.5px]">
                <span className="text-muted">Data layer</span>
                <Badge tone="ai">indexed</Badge>
              </div>
              <div className="flex items-center justify-between text-[13.5px]">
                <span className="text-muted">Extraction</span>
                <Badge tone="slatey">not started</Badge>
              </div>
            </div>
            <p className="mt-4 text-[12px] text-faint leading-relaxed">
              Source-backed extraction will add market definitions, theories of harm, and passage-level citations to this record.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
