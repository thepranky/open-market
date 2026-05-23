import { cn, confidencePct } from "@/lib/utils";
import type {
  SourcePassage,
  SourceDocument,
  ProductMarket,
  GeographicMarket,
  TheoryOfHarm,
  VerificationStatus,
} from "@/lib/types";

function docSourceLinks(doc: SourceDocument) {
  const links: { href: string; label: string; variant: "primary" | "secondary" | "fallback" }[] = [];

  if (doc.pdf_url) {
    links.push({ href: doc.pdf_url, label: "Open PDF", variant: "primary" });
  }
  if (doc.case_page_url) {
    links.push({ href: doc.case_page_url, label: "Case page", variant: "secondary" });
  }
  if (!doc.pdf_url && !doc.case_page_url && doc.url) {
    links.push({
      href: doc.url,
      label: "Open source",
      variant: doc.retrieval_status === "fallback" ? "fallback" : "primary",
    });
  }
  return links;
}

// Resolution order mirrors SourceChip: pdf_url → case_page_url → url (direct/fallback only)
function pageAnchoredPdfUrl(doc: SourceDocument, page?: string): string | undefined {
  if (doc.pdf_url && page) return `${doc.pdf_url}#page=${page}`;
  if (doc.pdf_url) return doc.pdf_url;
  if (doc.case_page_url) return doc.case_page_url;
  if (doc.url && (doc.retrieval_status === "direct" || doc.retrieval_status === "fallback")) return doc.url;
  return undefined;
}

export function SourceNeededBadge({ label = "Source needed" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-slate-200 text-xs text-slate-400 bg-slate-50">
      <span aria-hidden="true">◌</span>
      {label}
    </span>
  );
}

export function VerifiedBadge() {
  return (
    <span
      className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-xs text-green-700 bg-green-50 border border-green-200"
      title="Verified against source"
    >
      ✓ verified
    </span>
  );
}

export function effectiveVerificationStatus(
  passageCount: number,
  verification?: { verification_status: VerificationStatus } | null
): VerificationStatus {
  if (verification?.verification_status) return verification.verification_status;
  return passageCount > 0 ? "source_linked" : "no_source_linked";
}

export function EvidenceSection({
  passages,
  documents,
  markets,
  geoMarkets,
  theories,
}: {
  passages: SourcePassage[];
  documents: SourceDocument[];
  markets: ProductMarket[];
  geoMarkets: GeographicMarket[];
  theories: TheoryOfHarm[];
}) {
  if (passages.length === 0) return null;

  const docMap = new Map(documents.map((d) => [d.doc_id, d]));
  const marketMap = new Map(markets.map((m) => [m.market_id, m.name]));
  const geoMap = new Map(geoMarkets.map((m) => [m.market_id, m.name]));
  const theoryMap = new Map(theories.map((t) => [t.theory_id, t.name]));

  const byDoc = new Map<string, SourcePassage[]>();
  for (const sp of passages) {
    const arr = byDoc.get(sp.source_document_id) ?? [];
    arr.push(sp);
    byDoc.set(sp.source_document_id, arr);
  }

  return (
    <section className="mb-8">
      <h2 className="text-base font-semibold text-slate-900 border-b border-slate-100 pb-2 mb-4">
        Evidence
      </h2>
      <div className="space-y-6">
        {Array.from(byDoc.entries()).map(([docId, sps]) => {
          const doc = docMap.get(docId);
          const links = doc ? docSourceLinks(doc) : [];

          return (
            <div key={docId}>
              <div className="flex flex-wrap items-baseline gap-2 mb-1">
                <span className="text-sm font-medium text-slate-700">
                  {doc?.title ?? docId}
                </span>
                {doc?.doc_type && (
                  <span className="text-xs text-slate-400 capitalize font-normal">
                    {doc.doc_type.replace(/_/g, " ")}
                  </span>
                )}
                {doc?.retrieval_status === "fallback" && (
                  <span className="text-xs text-orange-600 bg-orange-50 border border-orange-200 px-1.5 py-0.5 rounded">
                    fallback source
                  </span>
                )}
                {doc?.retrieval_status === "broken" && (
                  <span className="text-xs text-red-600 bg-red-50 border border-red-200 px-1.5 py-0.5 rounded">
                    source unavailable
                  </span>
                )}
              </div>

              {links.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {links.map((l) => (
                    <a
                      key={l.href}
                      href={l.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={cn(
                        "inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded border",
                        l.variant === "fallback"
                          ? "border-orange-200 text-orange-700 bg-orange-50 hover:bg-orange-100"
                          : l.variant === "secondary"
                          ? "border-slate-200 text-slate-600 bg-slate-50 hover:bg-slate-100"
                          : "border-brand-200 text-brand-700 bg-brand-50 hover:bg-brand-100"
                      )}
                    >
                      {l.label} ↗
                    </a>
                  ))}
                </div>
              )}

              <div className="space-y-4 pl-3 border-l-2 border-slate-100">
                {sps.map((sp) => {
                  const supports: string[] = [
                    ...sp.supports_markets.map((id) => marketMap.get(id) ?? id),
                    ...sp.supports_geographic_markets.map(
                      (id) => geoMap.get(id) ?? id
                    ),
                    ...sp.supports_theories.map((id) => theoryMap.get(id) ?? id),
                  ];
                  const pagedLink = doc ? pageAnchoredPdfUrl(doc, sp.page) : undefined;

                  return (
                    <div key={sp.passage_id}>
                      <blockquote className="text-slate-700 italic text-xs leading-relaxed border-l-2 border-brand-300 pl-2 mb-1.5">
                        &ldquo;{sp.quote_snippet.trim()}&rdquo;
                      </blockquote>

                      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500 mb-1 items-center">
                        {pagedLink && (sp.page || sp.paragraph) && (
                          <a
                            href={pagedLink}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-brand-600 hover:underline"
                          >
                            {sp.page && `p.${sp.page}`}
                            {sp.paragraph && ` ¶${sp.paragraph}`}
                            {" ↗"}
                          </a>
                        )}
                        {!pagedLink && sp.page && <span>p.{sp.page}</span>}
                        {!pagedLink && sp.paragraph && <span>¶{sp.paragraph}</span>}
                        {sp.section && (
                          <span className="text-slate-400">{sp.section}</span>
                        )}
                        <span>{confidencePct(sp.confidence_score)} confidence</span>
                      </div>

                      {supports.length > 0 && (
                        <div className="text-xs text-slate-400">
                          Supports:{" "}
                          {supports.map((s, i) => (
                            <span key={i}>
                              {i > 0 && " · "}
                              <span className="text-slate-500">{s}</span>
                            </span>
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
