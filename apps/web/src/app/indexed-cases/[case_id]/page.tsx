import Link from "next/link";
import { notFound } from "next/navigation";
import { getIndexedCase } from "@/lib/api";
import {
  cn,
  conceptCategoryColor,
  formatConceptId,
  formatDate,
  formatOutcome,
  jurisdictionFlag,
  outcomeColor,
} from "@/lib/utils";
import { Badge } from "@/components/Badge";
import type { ConceptRef } from "@/lib/types";

interface Props {
  params: Promise<{ case_id: string }>;
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-8">
      <h2 className="text-base font-semibold text-slate-900 border-b border-slate-100 pb-2 mb-4">
        {title}
      </h2>
      {children}
    </section>
  );
}

function ProvenanceLabel({ provenance }: { provenance: string }) {
  const labels: Record<string, string> = {
    manually_tagged: "manually tagged",
    ai_extracted: "AI",
    yaml_concept_field: "YAML",
  };
  return (
    <span className="text-xs text-slate-400">
      {labels[provenance] ?? provenance.replace(/_/g, " ")}
    </span>
  );
}

function ConceptRefRow({ cr }: { cr: ConceptRef }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={cn(
          "text-sm px-2.5 py-1 rounded font-medium",
          conceptCategoryColor(cr.concept_id)
        )}
      >
        {formatConceptId(cr.concept_id)}
      </span>
      <Badge
        className={
          cr.quality_level === "canonical"
            ? "bg-green-100 text-green-800"
            : "bg-amber-100 text-amber-700"
        }
      >
        {cr.quality_level}
      </Badge>
      <ProvenanceLabel provenance={cr.provenance} />
    </div>
  );
}

export default async function IndexedCaseDetailPage({ params }: Props) {
  const { case_id } = await params;

  let entry;
  try {
    entry = await getIndexedCase(case_id);
  } catch {
    notFound();
  }

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Breadcrumb */}
      <nav className="text-sm text-slate-400 mb-6">
        <Link href="/explore" className="hover:text-slate-600">
          ← Explore
        </Link>
      </nav>

      {/* Index-entry notice */}
      <div className="bg-amber-50 border border-amber-200 rounded-xl px-5 py-3 mb-6 flex items-start gap-3">
        <span className="text-amber-500 mt-0.5 shrink-0">ⓘ</span>
        <div className="text-sm text-amber-800 leading-relaxed">
          <span className="font-semibold">Index entry — metadata only.</span>{" "}
          This record contains basic case facts and concept tags but has not yet
          undergone source-backed extraction. Markets, theories of harm, remedies,
          and legal propositions are not available here.
        </div>
      </div>

      {/* Header */}
      <div className="mb-8">
        <div className="flex items-start gap-4 flex-wrap">
          <span className="text-4xl mt-1" title={entry.jurisdiction}>
            {jurisdictionFlag(entry.jurisdiction)}
          </span>
          <div className="flex-1 min-w-0">
            <h1 className="text-3xl font-bold text-slate-900 leading-tight mb-2">
              {entry.case_name}
            </h1>
            <div className="flex flex-wrap items-center gap-3">
              <Badge className={outcomeColor(entry.outcome)}>
                {formatOutcome(entry.outcome)}
              </Badge>
              <Badge className="bg-amber-100 text-amber-800 border border-amber-200">
                Index entry
              </Badge>
              <span className="text-sm text-slate-400">
                {entry.authority} · {formatDate(entry.decision_date)}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-8">
        {/* Main column */}
        <div>
          {/* Case details */}
          <Section title="Case details">
            <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-3 text-sm">
              {[
                { label: "Authority", value: entry.authority },
                { label: "Decision date", value: formatDate(entry.decision_date) },
                { label: "Jurisdiction", value: entry.jurisdiction },
                { label: "Sector", value: entry.sector },
                { label: "Case type", value: entry.case_type },
              ].map(({ label, value }) => (
                <div key={label}>
                  <dt className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-0.5">
                    {label}
                  </dt>
                  <dd className="text-slate-800 capitalize">{value}</dd>
                </div>
              ))}
            </dl>
          </Section>

          {/* Parties */}
          {entry.parties.length > 0 && (
            <Section title="Parties">
              <div className="flex flex-wrap gap-2">
                {entry.parties.map((p) => (
                  <div
                    key={p.name}
                    className="border border-slate-200 rounded-lg px-3 py-2 text-sm"
                  >
                    <span className="font-medium text-slate-800">{p.name}</span>
                    <span className="ml-2 text-xs text-slate-400 capitalize">
                      {p.role}
                    </span>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Concept refs */}
          {entry.concept_refs.length > 0 && (
            <Section title="Concept tags">
              <p className="text-xs text-slate-500 mb-3">
                Manually tagged concepts — not extracted from source documents.
              </p>
              <div className="space-y-2">
                {entry.concept_refs.map((cr) => (
                  <ConceptRefRow key={cr.concept_id} cr={cr} />
                ))}
              </div>
            </Section>
          )}

          {/* What's not here — explicit placeholder */}
          <div className="bg-slate-50 border border-dashed border-slate-200 rounded-xl p-5 text-sm text-slate-500">
            <p className="font-medium text-slate-700 mb-2">
              Source-backed sections not yet available
            </p>
            <ul className="list-disc list-inside space-y-1 text-xs">
              <li>Product and geographic markets considered</li>
              <li>Theories of harm</li>
              <li>Remedies and commitments</li>
              <li>Source passages and document citations</li>
            </ul>
          </div>
        </div>

        {/* Sidebar */}
        <aside className="space-y-6">
          {/* AI summary */}
          {entry.ai_summary && (
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-slate-700 mb-3">Summary</h3>
              <p className="text-sm text-slate-700 whitespace-pre-wrap leading-relaxed mb-3">
                {entry.ai_summary.trim()}
              </p>
              <p className="text-xs text-slate-400">
                Summary — not source-verified.
              </p>
            </div>
          )}

          {/* Source link */}
          {entry.source_url && (
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-slate-700 mb-3">
                Authority source
              </h3>
              <a
                href={entry.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-brand-600 hover:underline break-all"
              >
                {entry.authority} case page ↗
              </a>
            </div>
          )}

          {/* Record status */}
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-amber-900 mb-2">
              Record status
            </h3>
            <div className="space-y-2 text-xs text-amber-800">
              <div className="flex items-center justify-between">
                <span>Data layer</span>
                <Badge className="bg-amber-100 text-amber-800">indexed</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span>Review status</span>
                <Badge className="bg-slate-100 text-slate-600">
                  metadata only
                </Badge>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
