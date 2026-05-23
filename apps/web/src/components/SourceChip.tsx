"use client";

import { useState } from "react";
import { cn, confidencePct, reviewStatusLabel } from "@/lib/utils";
import type { SourcePassage, SourceDocument } from "@/lib/types";

function passageLocator(sp: SourcePassage): string {
  if (sp.paragraph) return `¶${sp.paragraph}`;
  if (sp.page) return `p.${sp.page}`;
  if (sp.section) return sp.section.split(" ").slice(0, 2).join(" ");
  return sp.passage_id;
}

function chipClass(status: string): string {
  switch (status) {
    case "lawyer_reviewed":
      return "bg-green-100 text-green-800 border-green-300 hover:bg-green-200";
    case "spot_checked":
      return "bg-yellow-100 text-yellow-800 border-yellow-300 hover:bg-yellow-200";
    default:
      return "bg-red-100 text-red-700 border-red-200 hover:bg-red-200";
  }
}

// Resolution order: pdf_url → case_page_url → url (direct only) → url (fallback) → null
function sourceLink(
  doc: SourceDocument,
  page?: string
): { href: string; label: string; isFallback: boolean } | null {
  if (doc.pdf_url) {
    const href = page ? `${doc.pdf_url}#page=${page}` : doc.pdf_url;
    return { href, label: page ? `Open PDF (p.${page})` : "Open PDF", isFallback: false };
  }
  if (doc.case_page_url) {
    return { href: doc.case_page_url, label: "Open case page", isFallback: false };
  }
  if (doc.url) {
    if (doc.retrieval_status === "direct") {
      return { href: doc.url, label: "Open source", isFallback: false };
    }
    if (doc.retrieval_status === "fallback") {
      return { href: doc.url, label: "Open source", isFallback: true };
    }
  }
  return null;
}

export function SourceChip({
  passage,
  doc,
}: {
  passage: SourcePassage;
  doc?: SourceDocument;
}) {
  const [open, setOpen] = useState(false);
  const locator = passageLocator(passage);
  const link = doc ? sourceLink(doc, passage.page ?? undefined) : null;

  if (!doc && process.env.NODE_ENV === "development") {
    console.debug(
      `[SourceChip] passage ${passage.passage_id} references source_document_id=${passage.source_document_id} which was not found in docMap`
    );
  }

  return (
    <span className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex items-center px-1.5 py-0.5 rounded border text-xs font-mono transition-colors cursor-pointer",
          chipClass(passage.review_status)
        )}
        title={`${reviewStatusLabel(passage.review_status)} · ${confidencePct(passage.confidence_score)} confidence`}
        aria-expanded={open}
      >
        {locator}
      </button>

      {open && (
        <div className="absolute top-full left-0 z-30 mt-1 w-80 bg-white border border-slate-200 rounded-lg shadow-lg p-3 text-sm">
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="float-right text-slate-400 hover:text-slate-600 text-xs ml-2 leading-none"
            aria-label="Close"
          >
            ✕
          </button>

          <blockquote className="text-slate-700 italic text-xs leading-relaxed border-l-2 border-brand-300 pl-2 mb-2 pr-5">
            &ldquo;{passage.quote_snippet.trim()}&rdquo;
          </blockquote>

          {doc && (
            <div className="text-xs font-medium text-slate-700 mb-1.5 truncate">
              {doc.title}
            </div>
          )}

          <div className="flex flex-wrap gap-x-2 gap-y-1 text-xs text-slate-500 mb-2">
            {passage.page && <span>p.{passage.page}</span>}
            {passage.paragraph && <span>¶{passage.paragraph}</span>}
            {passage.section && (
              <span className="text-slate-400">{passage.section}</span>
            )}
          </div>

          <div className="mb-2">
            <span className="px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-600">
              {confidencePct(passage.confidence_score)} confidence
            </span>
          </div>

          {link ? (
            <a
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(
                "inline-flex items-center gap-1 text-xs px-2 py-1 rounded border",
                link.isFallback
                  ? "border-orange-200 text-orange-700 bg-orange-50 hover:bg-orange-100"
                  : "border-brand-200 text-brand-700 bg-brand-50 hover:bg-brand-100"
              )}
            >
              {link.label} ↗
              {link.isFallback && <span className="text-orange-500 ml-1">(fallback)</span>}
            </a>
          ) : (
            <span className="text-xs text-slate-400">Source unavailable</span>
          )}
        </div>
      )}
    </span>
  );
}
