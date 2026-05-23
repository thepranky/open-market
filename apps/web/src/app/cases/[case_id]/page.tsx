import Link from "next/link";
import { notFound } from "next/navigation";
import { getCase, getCaseGraph } from "@/lib/api";
import {
  cn,
  formatDate,
  formatOutcome,
  jurisdictionFlag,
  outcomeColor,
} from "@/lib/utils";
import { Badge } from "@/components/Badge";
import { SourceChip } from "@/components/SourceChip";
import {
  EvidenceSection,
  SourceNeededBadge,
  VerifiedBadge,
  effectiveVerificationStatus,
} from "@/components/Evidence";
import { CaseHistoryPanel } from "@/components/CaseHistory";
import type { GraphNeighbourhood, SourcePassage } from "@/lib/types";

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

function GraphPanel({ graph }: { graph: GraphNeighbourhood }) {
  const hasData =
    graph.product_markets.length > 0 ||
    graph.similar_cases.length > 0 ||
    graph.theories_of_harm.length > 0;

  if (!hasData) return null;

  return (
    <Section title="Graph neighbourhood">
      <div className="space-y-4 text-sm">
        {graph.product_markets.length > 0 && (
          <div>
            <div className="font-medium text-slate-700 mb-1">Product markets</div>
            <ul className="space-y-1">
              {graph.product_markets.map((m, i) => (
                <li key={i} className="text-slate-600">
                  {String(m.name)}{" "}
                  <span className="text-xs text-slate-400">
                    ({String(m.definition_status ?? "")})
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {graph.similar_cases.length > 0 && (
          <div>
            <div className="font-medium text-slate-700 mb-1">Similar cases</div>
            <ul className="space-y-2">
              {graph.similar_cases.map((s, i) => {
                const caseId = String(
                  (s.case as Record<string, unknown>).case_id ?? ""
                );
                return (
                  <li key={i} className="border border-slate-100 rounded-lg p-3">
                    <Link
                      href={`/cases/${caseId}`}
                      className="font-medium text-brand-700 hover:underline"
                    >
                      {caseId}
                    </Link>
                    <div className="text-xs text-slate-500 mt-0.5">
                      Score: {Math.round(s.score * 100)}%
                    </div>
                    {s.reasons.length > 0 && (
                      <ul className="mt-1 list-disc list-inside text-xs text-slate-500 space-y-0.5">
                        {s.reasons.map((r, j) => (
                          <li key={j}>{r}</li>
                        ))}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    </Section>
  );
}

function buildPassageIndex(
  passages: SourcePassage[],
  key: keyof Pick<
    SourcePassage,
    "supports_markets" | "supports_geographic_markets" | "supports_theories"
  >
): Map<string, SourcePassage[]> {
  const map = new Map<string, SourcePassage[]>();
  for (const sp of passages) {
    for (const id of sp[key]) {
      const arr = map.get(id) ?? [];
      arr.push(sp);
      map.set(id, arr);
    }
  }
  return map;
}

export default async function CaseDetailPage({ params }: Props) {
  const { case_id } = await params;

  let c;
  try {
    c = await getCase(case_id);
  } catch {
    notFound();
  }

  let graph: GraphNeighbourhood | null = null;
  try {
    graph = await getCaseGraph(case_id);
  } catch {
    // Graph neighbourhood is best-effort
  }

  const docMap = new Map(c.source_documents.map((d) => [d.doc_id, d]));
  const passagesByMarket = buildPassageIndex(c.source_passages, "supports_markets");
  const passagesByGeoMarket = buildPassageIndex(c.source_passages, "supports_geographic_markets");
  const passagesByTheory = buildPassageIndex(c.source_passages, "supports_theories");

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Breadcrumb */}
      <nav className="text-sm text-slate-400 mb-6">
        <Link href="/explore" className="hover:text-slate-600">
          ← Explore
        </Link>
      </nav>

      {/* Header — outcome status only, no record-level quality badges */}
      <div className="mb-8">
        <div className="flex items-start gap-4 flex-wrap">
          <span className="text-4xl mt-1" title={c.jurisdiction}>
            {jurisdictionFlag(c.jurisdiction)}
          </span>
          <div className="flex-1 min-w-0">
            <h1 className="text-3xl font-bold text-slate-900 leading-tight mb-2">
              {c.case_name}
            </h1>
            <div className="flex flex-wrap items-center gap-3">
              <Badge className={outcomeColor(c.outcome)}>
                {formatOutcome(c.outcome)}
              </Badge>
              <span className="text-sm text-slate-400">
                {c.authority} · {formatDate(c.decision_date)}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-8">
        {/* Main column */}
        <div>
          {/* Metadata */}
          <Section title="Case details">
            <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-3 text-sm">
              {[
                { label: "Authority", value: c.authority },
                { label: "Decision date", value: formatDate(c.decision_date) },
                { label: "Jurisdiction", value: c.jurisdiction },
                {
                  label: "Stage",
                  value: c.procedure_stage.replace(/_/g, " "),
                },
                { label: "Sector", value: c.sector },
                { label: "Case type", value: c.case_type },
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
          {c.parties.length > 0 && (
            <Section title="Parties">
              <div className="flex flex-wrap gap-2">
                {c.parties.map((p) => (
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

          {/* Theories of harm */}
          {c.theories_of_harm.length > 0 && (
            <Section title="Theories of harm">
              <div className="space-y-3">
                {c.theories_of_harm.map((t) => {
                  const passages = passagesByTheory.get(t.theory_id) ?? [];
                  const vStatus = effectiveVerificationStatus(passages.length, t.verification);

                  return (
                    <div
                      key={t.theory_id}
                      className="bg-blue-50 border border-blue-100 rounded-lg p-4"
                    >
                      <div className="font-medium text-blue-900 mb-1">
                        {t.name}
                      </div>
                      {t.description && (
                        <p className="text-sm text-blue-800 whitespace-pre-wrap mb-2">
                          {t.description.trim()}
                        </p>
                      )}
                      <div className="flex flex-wrap gap-1.5 items-center">
                        {passages.map((sp) => (
                          <SourceChip
                            key={sp.passage_id}
                            passage={sp}
                            doc={docMap.get(sp.source_document_id)}
                          />
                        ))}
                        {vStatus === "verified" && <VerifiedBadge />}
                        {vStatus === "no_source_linked" && <SourceNeededBadge />}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {/* Product markets */}
          {c.product_markets_considered.length > 0 && (
            <Section title="Product markets considered">
              <div className="space-y-2">
                {c.product_markets_considered.map((m) => {
                  const passages = passagesByMarket.get(m.market_id) ?? [];
                  const vStatus = effectiveVerificationStatus(passages.length, m.verification);

                  return (
                    <div
                      key={m.market_id}
                      className="border border-slate-200 rounded-lg p-4 text-sm"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium text-slate-800">
                          {m.name}
                        </span>
                        <Badge
                          className={cn(
                            "text-xs",
                            m.definition_status === "defined"
                              ? "bg-green-100 text-green-800"
                              : m.definition_status === "left_open"
                              ? "bg-yellow-100 text-yellow-800"
                              : "bg-slate-100 text-slate-600"
                          )}
                        >
                          {m.definition_status.replace(/_/g, " ")}
                        </Badge>
                      </div>
                      {m.notes && (
                        <p className="text-slate-600 whitespace-pre-wrap mb-2">
                          {m.notes.trim()}
                        </p>
                      )}
                      <div className="flex flex-wrap gap-1.5 items-center">
                        {passages.map((sp) => (
                          <SourceChip
                            key={sp.passage_id}
                            passage={sp}
                            doc={docMap.get(sp.source_document_id)}
                          />
                        ))}
                        {vStatus === "verified" && <VerifiedBadge />}
                        {vStatus === "no_source_linked" && <SourceNeededBadge />}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {/* Geographic markets */}
          {c.geographic_markets_considered.length > 0 && (
            <Section title="Geographic markets considered">
              <div className="space-y-2">
                {c.geographic_markets_considered.map((m) => {
                  const passages = passagesByGeoMarket.get(m.market_id) ?? [];
                  const vStatus = effectiveVerificationStatus(passages.length, m.verification);

                  return (
                    <div
                      key={m.market_id}
                      className="border border-slate-200 rounded-lg p-4 text-sm"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium text-slate-800">
                          {m.name}
                        </span>
                        <Badge
                          className={cn(
                            "text-xs",
                            m.definition_status === "defined"
                              ? "bg-green-100 text-green-800"
                              : "bg-slate-100 text-slate-600"
                          )}
                        >
                          {m.definition_status.replace(/_/g, " ")}
                        </Badge>
                      </div>
                      {m.notes && (
                        <p className="text-slate-600 whitespace-pre-wrap mb-2">
                          {m.notes.trim()}
                        </p>
                      )}
                      <div className="flex flex-wrap gap-1.5 items-center">
                        {passages.map((sp) => (
                          <SourceChip
                            key={sp.passage_id}
                            passage={sp}
                            doc={docMap.get(sp.source_document_id)}
                          />
                        ))}
                        {vStatus === "verified" && <VerifiedBadge />}
                        {vStatus === "no_source_linked" && <SourceNeededBadge />}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {/* Remedies */}
          {c.remedies.length > 0 && (
            <Section title="Remedies">
              <ul className="list-disc list-inside space-y-1 text-sm text-slate-700 mb-2">
                {c.remedies.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
              <SourceNeededBadge label="Source passages not yet linked to individual remedies" />
            </Section>
          )}

          {/* All source passages — collapsed by default; chips are the primary access path */}
          {c.source_passages.length > 0 && (
            <details className="mb-8 group">
              <summary className="list-none flex items-center gap-2 cursor-pointer border-b border-slate-100 pb-2 mb-4 select-none">
                <span className="text-base font-semibold text-slate-900">
                  All source passages
                </span>
                <span className="text-xs text-slate-400 font-normal">
                  ({c.source_passages.length})
                </span>
                <span className="ml-auto text-xs text-slate-400">
                  <span className="group-open:hidden">Show ▸</span>
                  <span className="hidden group-open:inline">Hide ▾</span>
                </span>
              </summary>
              <EvidenceSection
                passages={c.source_passages}
                documents={c.source_documents}
                markets={c.product_markets_considered}
                geoMarkets={c.geographic_markets_considered}
                theories={c.theories_of_harm}
              />
            </details>
          )}
        </div>

        {/* Sidebar */}
        <aside className="space-y-6">
          {/* Summary — strip any inline bracketed disclaimer before rendering */}
          {c.ai_summary && (
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-slate-700 mb-3">
                Summary
              </h3>
              <p className="text-sm text-slate-700 whitespace-pre-wrap leading-relaxed mb-3">
                {c.ai_summary.replace(/\[AI-generated summary[^\]]*\]/gi, "").trim()}
              </p>
              <p className="text-xs text-slate-400">
                AI-generated summary — verify against source-linked fields.
              </p>
            </div>
          )}

          {/* Case history */}
          <CaseHistoryPanel history={c.case_history} />

          {/* Source documents */}
          {c.source_documents.length > 0 && (
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-slate-700 mb-3">
                Source documents
              </h3>
              <ul className="space-y-3">
                {c.source_documents.map((doc) => {
                  const primaryUrl = doc.pdf_url ?? doc.case_page_url ?? doc.url;
                  return (
                    <li key={doc.doc_id} className="text-sm">
                      <div className="font-medium text-slate-700 mb-1">
                        {primaryUrl ? (
                          <a
                            href={primaryUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-brand-600 hover:underline"
                          >
                            {doc.title}
                          </a>
                        ) : (
                          <span>{doc.title}</span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-1.5 items-center">
                        {doc.pdf_url && (
                          <a
                            href={doc.pdf_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs border border-brand-200 text-brand-700 bg-brand-50 hover:bg-brand-100 px-1.5 py-0.5 rounded"
                          >
                            PDF ↗
                          </a>
                        )}
                        {doc.case_page_url && (
                          <a
                            href={doc.case_page_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs border border-slate-200 text-slate-600 bg-slate-50 hover:bg-slate-100 px-1.5 py-0.5 rounded"
                          >
                            Case page ↗
                          </a>
                        )}
                        {!doc.pdf_url && !doc.case_page_url && doc.url && (
                          <a
                            href={doc.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={cn(
                              "text-xs border px-1.5 py-0.5 rounded",
                              doc.retrieval_status === "fallback"
                                ? "border-orange-200 text-orange-700 bg-orange-50 hover:bg-orange-100"
                                : "border-brand-200 text-brand-700 bg-brand-50 hover:bg-brand-100"
                            )}
                          >
                            {doc.retrieval_status === "fallback" ? "Fallback source ↗" : "Source ↗"}
                          </a>
                        )}
                        {doc.retrieval_status === "broken" && (
                          <span className="text-xs text-red-600 bg-red-50 border border-red-200 px-1.5 py-0.5 rounded">
                            source unavailable
                          </span>
                        )}
                        {doc.published_date && (
                          <span className="text-xs text-slate-400">
                            {formatDate(doc.published_date)}
                          </span>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {/* Graph neighbourhood */}
          {graph && <GraphPanel graph={graph} />}
        </aside>
      </div>
    </div>
  );
}
