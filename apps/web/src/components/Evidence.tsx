import { confidencePct } from "@/lib/utils";
import type {
  SourcePassage, SourceDocument, ProductMarket, GeographicMarket,
  TheoryOfHarm, VerificationStatus,
} from "@/lib/types";

function docSourceLinks(doc: SourceDocument) {
  const links: { href: string; label: string; fallback?: boolean }[] = [];
  if (doc.pdf_url) links.push({ href: doc.pdf_url, label: "Open PDF" });
  if (doc.case_page_url) links.push({ href: doc.case_page_url, label: "Case page" });
  if (!doc.pdf_url && !doc.case_page_url && doc.url) {
    links.push({ href: doc.url, label: "Open source", fallback: doc.retrieval_status === "fallback" });
  }
  return links;
}

function pageAnchoredUrl(doc: SourceDocument, page?: string): string | undefined {
  if (doc.pdf_url && page) return `${doc.pdf_url}#page=${page}`;
  if (doc.pdf_url) return doc.pdf_url;
  if (doc.case_page_url) return doc.case_page_url;
  if (doc.url && (doc.retrieval_status === "direct" || doc.retrieval_status === "fallback")) return doc.url;
}

export function SourceNeededBadge({ label = "Source needed" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-[5px] border border-line text-[11.5px] text-faint bg-canvas">
      <span aria-hidden="true">◌</span>
      {label}
    </span>
  );
}

export function VerifiedBadge() {
  return (
    <span className="inline-flex items-center gap-0.5 px-1.5 py-[3px] rounded-[5px] text-[11.5px] text-pos-ink bg-pos-soft" title="Verified against source">
      ✓ verified
    </span>
  );
}

export function effectiveVerificationStatus(
  passageCount: number,
  verification?: { verification_status: VerificationStatus } | null,
): VerificationStatus {
  if (verification?.verification_status) return verification.verification_status;
  return passageCount > 0 ? "source_linked" : "no_source_linked";
}

export function EvidenceSection({
  passages, documents, markets, geoMarkets, theories,
}: {
  passages: SourcePassage[];
  documents: SourceDocument[];
  markets: ProductMarket[];
  geoMarkets: GeographicMarket[];
  theories: TheoryOfHarm[];
}) {
  if (passages.length === 0) return null;

  const docMap    = new Map(documents.map((d) => [d.doc_id, d]));
  const marketMap = new Map(markets.map((m) => [m.market_id, m.name]));
  const geoMap    = new Map(geoMarkets.map((m) => [m.market_id, m.name]));
  const theoryMap = new Map(theories.map((t) => [t.theory_id, t.name]));

  const byDoc = new Map<string, SourcePassage[]>();
  for (const sp of passages) {
    const arr = byDoc.get(sp.source_document_id) ?? [];
    arr.push(sp);
    byDoc.set(sp.source_document_id, arr);
  }

  return (
    <section className="mb-8">
      <h2 className="text-[19px] font-semibold text-ink tracking-tight border-b border-line pb-2 mb-4">Evidence</h2>
      <div className="space-y-6">
        {Array.from(byDoc.entries()).map(([docId, sps]) => {
          const doc = docMap.get(docId);
          const links = doc ? docSourceLinks(doc) : [];

          return (
            <div key={docId}>
              <div className="flex flex-wrap items-baseline gap-2 mb-1">
                <span className="text-[14px] font-medium text-ink">{doc?.title ?? docId}</span>
                {doc?.doc_type && <span className="text-[12.5px] text-faint capitalize">{doc.doc_type.replace(/_/g, " ")}</span>}
                {doc?.retrieval_status === "fallback" && (
                  <span className="text-[11px] bg-ai-soft text-ai-ink px-1.5 py-[2px] rounded-[4px]">fallback source</span>
                )}
                {doc?.retrieval_status === "broken" && (
                  <span className="text-[11px] bg-neg-soft text-neg-ink px-1.5 py-[2px] rounded-[4px]">source unavailable</span>
                )}
              </div>

              {links.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {links.map((l) => (
                    <a key={l.href} href={l.href} target="_blank" rel="noopener noreferrer"
                      className={`inline-flex items-center gap-1 text-[12px] px-2.5 py-1 rounded-[6px] border transition-colors ${
                        l.fallback
                          ? "border-ai text-ai-ink bg-ai-soft hover:bg-ai-soft"
                          : "border-line-strong text-brand-ink bg-surface hover:border-brand"
                      }`}>
                      {l.label} ↗
                    </a>
                  ))}
                </div>
              )}

              <div className="space-y-4 pl-3 border-l-2 border-line">
                {sps.map((sp) => {
                  const supports = [
                    ...sp.supports_markets.map((id) => marketMap.get(id) ?? id),
                    ...sp.supports_geographic_markets.map((id) => geoMap.get(id) ?? id),
                    ...sp.supports_theories.map((id) => theoryMap.get(id) ?? id),
                  ];
                  const pagedLink = doc ? pageAnchoredUrl(doc, sp.page ?? undefined) : undefined;

                  return (
                    <div key={sp.passage_id}>
                      <blockquote className="text-[13.5px] leading-relaxed text-ink font-serif italic border-l-2 pl-2 mb-1.5" style={{ borderColor: "var(--brand-soft)" }}>
                        &ldquo;{sp.quote_snippet.trim()}&rdquo;
                      </blockquote>

                      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-faint mb-1 items-center">
                        {pagedLink && (sp.page || sp.paragraph) ? (
                          <a href={pagedLink} target="_blank" rel="noopener noreferrer" className="text-brand-ink hover:underline">
                            {sp.page && `p.${sp.page}`}{sp.paragraph && ` ¶${sp.paragraph}`} ↗
                          </a>
                        ) : (
                          <>
                            {sp.page && <span>p.{sp.page}</span>}
                            {sp.paragraph && <span>¶{sp.paragraph}</span>}
                          </>
                        )}
                        {sp.section && <span>{sp.section}</span>}
                        <span>{confidencePct(sp.confidence_score)} confidence</span>
                      </div>

                      {supports.length > 0 && (
                        <div className="text-[12px] text-faint">
                          Supports:{" "}
                          {supports.map((s, i) => (
                            <span key={i}>{i > 0 && " · "}<span className="text-muted">{s}</span></span>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
