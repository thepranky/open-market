"use client";

import { useState } from "react";

interface CopyButtonProps {
  text: string;
  label?: string;
}

export function CopyButton({ text, label = "Copy" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch { /* clipboard not available */ }
  }

  return (
    <button
      onClick={handleCopy}
      className="shrink-0 text-[11.5px] text-faint hover:text-ink border border-line hover:border-line-strong px-2 py-0.5 rounded-[5px] transition-colors font-mono"
      title="Copy to clipboard"
    >
      {copied ? "✓" : label}
    </button>
  );
}
