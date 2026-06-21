"use client";

import { useCallback, useRef, useState } from "react";
import { createPortal } from "react-dom";

export type SourceType =
  | "primary_legislation"
  | "official_guidance"
  | "authority_announcement"
  | "practitioner";

const SOURCE_STYLES: Record<SourceType, { label: string; cls: string }> = {
  primary_legislation:    { label: "Primary legislation", cls: "bg-brand-soft text-brand" },
  official_guidance:      { label: "Official guidance",   cls: "bg-pos-soft text-pos" },
  authority_announcement: { label: "Authority notice",    cls: "bg-slatey-soft text-slatey" },
  practitioner:           { label: "Practitioner",        cls: "bg-neg-soft text-neg" },
};

interface SourcePillProps {
  type: SourceType;
  href: string;
  quotedText?: string;
  articleRef?: string;
  label?: string; // overrides source_type default label
}

export function SourcePill({ type, href, quotedText, articleRef, label }: SourcePillProps) {
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const anchorRef = useRef<HTMLAnchorElement>(null);

  const show = useCallback(() => {
    if (!quotedText) return;
    const r = anchorRef.current?.getBoundingClientRect();
    if (r) setPos({ top: r.bottom + 6, left: r.left });
  }, [quotedText]);

  const hide = useCallback(() => setPos(null), []);

  const s = SOURCE_STYLES[type] ?? SOURCE_STYLES.official_guidance;
  const pillLabel = label ?? s.label;

  return (
    <>
      <a
        ref={anchorRef}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        onMouseEnter={show}
        onMouseLeave={hide}
        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium whitespace-nowrap ${s.cls} hover:opacity-80 hover:underline underline-offset-2`}
      >
        {pillLabel} ↗
      </a>
      {pos && quotedText && typeof document !== "undefined" &&
        createPortal(
          <div
            style={{ position: "fixed", top: pos.top, left: pos.left, zIndex: 9999, maxWidth: 360 }}
            className="bg-ink text-canvas rounded-lg shadow-xl px-3 py-2.5 pointer-events-none"
          >
            {articleRef && (
              <p className="text-[10px] font-semibold uppercase tracking-wide text-canvas/50 mb-1.5">
                {articleRef}
              </p>
            )}
            <p className="text-[11px] leading-relaxed">{quotedText.trim()}</p>
          </div>,
          document.body
        )}
    </>
  );
}
