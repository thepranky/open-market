import Link from "next/link";
import { notFound } from "next/navigation";
import { getCase } from "@/features/cases/api";
import { formatDate, formatOutcome, outcomeTone, defnTone, defnLabel, jurisdictionAuthority } from "@/lib/utils";
import { Badge } from "@/components/Badge";
import { Juris } from "@/features/cases/components/Juris";
import { SourceChip } from "@/components/SourceChip";
import { CopyButton } from "@/components/CopyButton";
import {
  EvidenceSection, SourceNeededBadge, VerifiedBadge, effectiveVerificationStatus,
} from "@/features/cases/components/Evidence";
import { CaseHistoryPanel } from "@/features/cases/components/CaseHistory";
import type { CaseRecord, SourcePassage } from "@/lib/types";

interface Props {
  params: Promise<{ case_id: string }>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-9">
      <h2 className="text-[19px] font-semibold text-ink tracking-tight">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase tracking-[0.07em] text-faint mb-1">{label}</dt>
      <dd className="text-[15px] text-ink">{children}</dd>
    </div>
  );
}

function RelatedCasesPanel({ c }: { c: CaseRecord }) {
  if (!c.similar_cases || c.similar_cases.length === 0) return null;
  return (
    <div className="bg-surface border border-line rounded-xl p-5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-faint mb-3">Related cases</p>
      <ul className="space-y-1">
        {c.similar_cases.map((s) => {
          const name = s.case_id.replace(/^(eu|uk|us)_/, "").replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
          return (
            <li key={s.case_id}>
              <Link href={`/cases/${s.case_id}`}
                className="flex items-center justify-between gap-3 rounded-[8px] -mx-2 px-2 py-2 hover:bg-slatey-soft transition-colors group">
                <span className="text-[13.5px] text-ink group-hover:text-brand-ink transition-colors">{name}</span>
                <svg width={14} height={14} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" className="text-faint shrink-0" aria-hidden="true"><path d="M4 10h12M11 5l5 5-5 5" /></svg>
              </Link>
              {s.reasons.length > 0 && (
                <p className="text-[11.5px] text-faint mt-0.5 pl-2">{s.reasons.slice(0, 2).join(" · ")}</p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function buildPassageIndex(
  passages: SourcePassage[],
  key: keyof Pick<SourcePassage, "supports_markets" | "supports_geographic_markets" | "supports_theories">,
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
  try { c = await getCase(case_id); } catch { notFound(); }

  const docMap             = new Map(c.source_documents.map((d) => [d.doc_id, d]));
  const passagesByMarket   = buildPassageIndex(c.source_passages, "supports_markets");
  const passagesByGeoMarket = buildPassageIndex(c.source_passages, "supports_geographic_markets");
  const passagesByTheory   = buildPassageIndex(c.source_passages, "supports_theories");
  const totalCites         = c.source_passages.length;

  return (
    <div className="mx-auto max-w-content px-6 lg:px-8 py-8">
      {/* Breadcrumb */}
      <Link href="/explore"
        className="inline-flex items-center gap-1.5 text-[13.5px] text-muted hover:text-ink mb-6 transition-colors">
        <svg width={15} height={15} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M16 10H4M9 5l-5 5 5 5" /></svg>
        Explore
      </Link>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-5 pb-7 border-b border-line">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5 mb-3">
            <Juris code={c.jurisdiction} />
            <span className="font-mono text-[12px] text-faint">{c.case_id}</span>
            <span className="inline-flex items-center gap-1 whitespace-nowrap text-[11.5px] font-medium text-pos-ink">
              <svg width={13} height={13} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 10.5l4 4 8-9" /></svg>
              Source-reviewed
            </span>
          </div>
          <h1 className="font-serif text-ink" style={{ fontSize: "clamp(30px, 4vw, 44px)", lineHeight: 1.05, letterSpacing: "-0.01em" }}>
            {c.case_name}
          </h1>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Badge tone={outcomeTone(c.outcome)} dot>{formatOutcome(c.outcome)}</Badge>
            <span className="text-[14px] text-muted">{c.authority} · {formatDate(c.decision_date)}</span>
          </div>
        </div>
        <Link href="/graph"
          className="inline-flex items-center gap-2 bg-surface text-ink border border-line-strong px-3 py-1.5 rounded-[7px] text-[13px] font-medium hover:border-faint hover:bg-canvas transition-colors">
          <svg width={15} height={15} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M10 3v4M10 13v4M5.5 6.5L8 9M12 11l2.5 2.5M5 14a2 2 0 100-4 2 2 0 000 4zm10 0a2 2 0 100-4 2 2 0 000 4zM10 11a2 2 0 100-4 2 2 0 000 4z" /></svg>
          View in graph
        </Link>
      </div>

      <div className="grid lg:grid-cols-[1fr_350px] gap-8 mt-8">
        {/* Main */}
        <main className="space-y-9 min-w-0">
          <Section title="Case details">
            <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-5">
              <Field label="Authority">{c.authority}</Field>
              <Field label="Decision date">{formatDate(c.decision_date)}</Field>
              <Field label="Jurisdiction"><Juris code={c.jurisdiction} /></Field>
              <Field label="Stage"><span className="capitalize">{c.procedure_stage.replace(/_/g, " ")}</span></Field>
              <Field label="Sector"><span className="capitalize">{c.sector}</span></Field>
              <Field label="Case type"><span className="capitalize">{c.case_type}</span></Field>
            </dl>
          </Section>

          {c.parties.length > 0 && (
            <Section title="Parties">
              <div className="flex flex-wrap gap-3">
                {c.parties.map((p) => (
                  <div key={p.name} className="flex items-center gap-3 rounded-[10px] border border-line bg-surface pl-4 pr-3 py-2.5">
                    <span className="text-[15px] font-medium text-ink whitespace-nowrap">{p.name}</span>
                    <span className="text-[11px] font-medium uppercase tracking-[0.06em] text-muted bg-slatey-soft rounded-[5px] px-2 py-[3px] capitalize">{p.role}</span>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {c.theories_of_harm.length > 0 && (
            <Section title="Theories of harm">
              <div className="space-y-2.5">
                {c.theories_of_harm.map((t) => {
                  const passages = passagesByTheory.get(t.theory_id) ?? [];
                  const vStatus  = effectiveVerificationStatus(passages.length, t.verification);
                  return (
                    <div key={t.theory_id} className="flex items-start gap-3 rounded-[10px] border border-line bg-surface px-4 py-3">
                      <span className="mt-1 w-1.5 h-1.5 rounded-full bg-neg shrink-0" />
                      <div className="min-w-0">
                        <div className="text-[15px] text-ink leading-snug">{t.name}</div>
                        {t.description && (
                          <p className="text-[13.5px] text-muted leading-relaxed mt-1 whitespace-pre-wrap">{t.description.trim()}</p>
                        )}
                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                          {passages.map((sp) => <SourceChip key={sp.passage_id} passage={sp} doc={docMap.get(sp.source_document_id)} />)}
                          {vStatus === "verified" && <VerifiedBadge />}
                          {vStatus === "no_source_linked" && <SourceNeededBadge />}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {c.product_markets_considered.length > 0 && (
            <section className="mb-9">
              <div className="flex items-center justify-between">
                <h2 className="text-[19px] font-semibold text-ink tracking-tight">Product markets considered</h2>
                <span className="text-[12.5px] text-faint font-mono">{c.product_markets_considered.length} markets · {totalCites} citations</span>
              </div>
              <div className="mt-4 space-y-3">
                {c.product_markets_considered.map((m) => {
                  const passages = passagesByMarket.get(m.market_id) ?? [];
                  const vStatus  = effectiveVerificationStatus(passages.length, m.verification);
                  const firstQuote = passages[0]?.quote_snippet;
                  const copyText = [
                    `${m.name} (${defnLabel(m.definition_status)})`,
                    `— ${c.case_name}, ${c.authority} (${formatDate(c.decision_date).slice(0, 4)})`,
                    firstQuote ? `"${firstQuote.trim()}"` : "",
                  ].filter(Boolean).join(" ");

                  return (
                    <div key={m.market_id} className="rounded-xl border border-line bg-surface p-5">
                      <div className="flex items-start justify-between gap-4">
                        <h3 className="text-[16.5px] font-semibold text-ink leading-snug flex-1 min-w-0">{m.name}</h3>
                        <div className="flex items-center gap-2 shrink-0">
                          <CopyButton text={copyText} />
                          <Badge tone={defnTone(m.definition_status)}>{defnLabel(m.definition_status)}</Badge>
                        </div>
                      </div>
                      {m.notes && (
                        <p className="mt-2.5 text-[14.5px] leading-relaxed text-muted whitespace-pre-wrap">{m.notes.trim()}</p>
                      )}
                      {(passages.length > 0 || vStatus === "no_source_linked") && (
                        <div className="mt-3.5 flex flex-wrap items-center gap-2">
                          <span className="text-[11px] font-semibold uppercase tracking-[0.07em] text-faint mr-0.5">Source</span>
                          {passages.map((sp) => <SourceChip key={sp.passage_id} passage={sp} doc={docMap.get(sp.source_document_id)} />)}
                          {vStatus === "verified" && <VerifiedBadge />}
                          {vStatus === "no_source_linked" && <SourceNeededBadge />}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {c.geographic_markets_considered.length > 0 && (
            <Section title="Geographic markets considered">
              <div className="space-y-3">
                {c.geographic_markets_considered.map((m) => {
                  const passages = passagesByGeoMarket.get(m.market_id) ?? [];
                  const vStatus  = effectiveVerificationStatus(passages.length, m.verification);
                  return (
                    <div key={m.market_id} className="rounded-xl border border-line bg-surface p-5">
                      <div className="flex items-center gap-3">
                        <h3 className="text-[15px] font-semibold text-ink flex-1">{m.name}</h3>
                        <Badge tone={defnTone(m.definition_status)}>{defnLabel(m.definition_status)}</Badge>
                      </div>
                      {m.notes && <p className="mt-2 text-[14px] text-muted whitespace-pre-wrap">{m.notes.trim()}</p>}
                      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                        {passages.map((sp) => <SourceChip key={sp.passage_id} passage={sp} doc={docMap.get(sp.source_document_id)} />)}
                        {vStatus === "verified" && <VerifiedBadge />}
                        {vStatus === "no_source_linked" && <SourceNeededBadge />}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {c.remedies.length > 0 && (
            <Section title="Remedies">
              <ul className="space-y-1.5">
                {c.remedies.map((r, i) => (
                  <li key={i} className="flex items-start gap-2.5 text-[14.5px] text-ink">
                    <span className="mt-1.5 w-1 h-1 rounded-full bg-neg shrink-0" />
                    {r}
                  </li>
                ))}
              </ul>
              <div className="mt-3"><SourceNeededBadge label="Source passages not yet linked to individual remedies" /></div>
            </Section>
          )}

          {c.source_passages.length > 0 && (
            <details className="mb-8 group">
              <summary className="list-none flex items-center gap-2 cursor-pointer border-b border-line pb-2 mb-4 select-none">
                <span className="text-[19px] font-semibold text-ink tracking-tight">All source passages</span>
                <span className="text-[12.5px] text-faint font-mono">({c.source_passages.length})</span>
                <span className="ml-auto text-[12.5px] text-faint">
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
        </main>

        {/* Sidebar */}
        <aside className="space-y-5 lg:sticky lg:top-[74px] self-start">
          {/* AI summary */}
          {c.ai_summary && (
            <div className="rounded-xl border border-ai-soft bg-ai-soft p-5">
              <div className="flex items-center justify-between mb-2.5">
                <div className="flex items-center gap-2 text-ai-ink">
                  <svg width={16} height={16} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M10 3l1.6 4.4L16 9l-4.4 1.6L10 15l-1.6-4.4L4 9l4.4-1.6L10 3z" /></svg>
                  <span className="text-[13px] font-semibold">Summary</span>
                </div>
                <span className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-ai-ink border border-ai rounded-[4px] px-1.5 py-[2px]" style={{ borderColor: "var(--ai)" }}>AI-generated</span>
              </div>
              <p className="text-[14px] leading-relaxed text-ink">
                {c.ai_summary.replace(/\[AI-generated summary[^\]]*\]/gi, "").trim()}
              </p>
              <p className="mt-3 text-[11.5px] text-ai-ink">Generated from the decision text. Verify against the source before relying on it.</p>
            </div>
          )}

          {/* Source documents */}
          {c.source_documents.length > 0 && (
            <div className="bg-surface border border-line rounded-xl p-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-faint mb-3">Source documents</p>
              <div className="space-y-1">
                {c.source_documents.map((doc) => {
                  const primaryUrl = doc.pdf_url ?? doc.case_page_url ?? doc.url;
                  const isPdf = !!doc.pdf_url;
                  return (
                    <div key={doc.doc_id} className="group flex items-center gap-3 rounded-[8px] -mx-2 px-2 py-2 hover:bg-slatey-soft transition-colors">
                      <span className="text-muted group-hover:text-brand-ink">
                        {isPdf ? (
                          <svg width={17} height={17} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 3h5l4 4v10H6V3zM11 3v4h4" /></svg>
                        ) : (
                          <svg width={17} height={17} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M8 12a3 3 0 004 0l2-2a3 3 0 00-4-4M12 8a3 3 0 00-4 0l-2 2a3 3 0 004 4" /></svg>
                        )}
                      </span>
                      <div className="min-w-0 flex-1">
                        {primaryUrl ? (
                          <a href={primaryUrl} target="_blank" rel="noopener noreferrer"
                            className="block text-[13.5px] font-medium text-ink group-hover:text-brand-ink transition-colors truncate">
                            {doc.title}
                          </a>
                        ) : (
                          <span className="block text-[13.5px] font-medium text-ink truncate">{doc.title}</span>
                        )}
                        {doc.published_date && (
                          <span className="block text-[11.5px] text-faint font-mono">{formatDate(doc.published_date)}</span>
                        )}
                      </div>
                      {primaryUrl && (
                        <svg width={14} height={14} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" className="text-faint shrink-0" aria-hidden="true"><path d="M7 13L13 7M8 7h5v5" /></svg>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Case history */}
          <CaseHistoryPanel history={c.case_history} />

          {/* Related cases */}
          <RelatedCasesPanel c={c} />
        </aside>
      </div>
    </div>
  );
}
