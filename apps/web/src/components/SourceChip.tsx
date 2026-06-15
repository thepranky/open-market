"use client";

import { useState } from "react";
import { formatDate } from "@/lib/utils";
import type { SourcePassage, SourceDocument } from "@/lib/types";

function passageLocator(sp: SourcePassage): { page?: string; para?: string } {
  return { page: sp.page ?? undefined, para: sp.paragraph ?? undefined };
}

function sourceLink(doc: SourceDocument, page?: string): { href: string; label: string } | null {
  if (doc.pdf_url) {
    const href = page ? `${doc.pdf_url}#page=${page}` : doc.pdf_url;
    return { href, label: page ? `Open PDF (p.${page})` : "Open PDF" };
  }
  if (doc.case_page_url) return { href: doc.case_page_url, label: "Open case page" };
  if (doc.url && (doc.retrieval_status === "direct" || doc.retrieval_status === "fallback")) {
    return { href: doc.url, label: "Open source" };
  }
  return null;
}

export function SourceChip({ passage, doc }: { passage: SourcePassage; doc?: SourceDocument }) {
  const [open, setOpen] = useState(false);
  const { page, para } = passageLocator(passage);
  const link = doc ? sourceLink(doc, page) : null;

  const label = [page && `p.${page}`, para && `¶${para}`].filter(Boolean).join(" ") || passage.passage_id.slice(-6);

  return (
    <span className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="View source passage"
        aria-expanded={open}
        className="group inline-flex items-center gap-1 rounded-[4px] border border-brand-soft bg-brand-soft px-1.5 py-[2px] font-mono text-[11px] font-medium text-brand-ink leading-none hover:border-brand transition-colors"
        style={{ borderColor: "color-mix(in srgb, var(--brand) 25%, transparent)" }}
      >
        {label}
        <svg width={11} height={11} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className="opacity-0 -ml-1 group-hover:opacity-100 group-hover:ml-0 transition-all" aria-hidden="true">
          <path d="M4 10h12M11 5l5 5-5 5" />
        </svg>
      </button>

      {open && (
        <div className="absolute top-full left-0 z-30 mt-1 w-80 bg-surface border border-line rounded-xl shadow-raised p-4 text-sm">
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="float-right text-faint hover:text-ink text-xs ml-2 leading-none"
            aria-label="Close"
          >
            ✕
          </button>

          <div className="flex items-center gap-2 mb-1">
            {page && <span className="font-mono text-[12px] font-semibold text-brand-ink bg-brand-soft rounded-[4px] px-1.5 py-[2px]">p.{page}</span>}
            {para && <span className="font-mono text-[12px] text-faint">¶{para}</span>}
          </div>

          {doc && (
            <div className="text-[12.5px] text-faint mb-3 truncate">{doc.title}</div>
          )}

          <blockquote className="text-[14px] leading-relaxed text-ink font-serif border-l-2 border-brand-soft pl-3 mb-3 pr-5" style={{ borderColor: "var(--brand-soft)" }}>
            &ldquo;{passage.quote_snippet.trim()}&rdquo;
          </blockquote>

          {link ? (
            <a
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[12px] px-2.5 py-1.5 rounded-[6px] bg-surface border border-line-strong text-brand-ink hover:border-brand transition-colors"
            >
              {link.label} ↗
            </a>
          ) : (
            <span className="text-[12px] text-faint">Source unavailable</span>
          )}
        </div>
      )}
    </span>
  );
}
