"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { JurisdictionSummary } from "@/lib/types";
import { getBaseUrl } from "@/lib/api-client";

interface CitationRef {
  n: number;
  jurisdiction_id: string;
  section_id: string;
  label: string;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: CitationRef[];
}

function renderWithCitations(
  text: string,
  citations: CitationRef[],
  onCite: (c: CitationRef) => void
): React.ReactNode[] {
  const parts = text.split(/(\[\d+\])/g);
  return parts.map((part, i) => {
    const match = part.match(/^\[(\d+)\]$/);
    if (!match) return part;
    const n = parseInt(match[1], 10);
    const ref = citations.find((c) => c.n === n);
    if (!ref) return part;
    return (
      <button
        key={i}
        onClick={() => onCite(ref)}
        title={ref.label}
        className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-brand text-white text-[9px] font-bold leading-none mx-0.5 hover:bg-brand/70 transition-colors align-super"
      >
        {n}
      </button>
    );
  });
}

interface JurisdictionChatProps {
  jurisdictions: JurisdictionSummary[];
}

const API_BASE = getBaseUrl();

export function JurisdictionChat({ jurisdictions }: JurisdictionChatProps) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [includeCases, setIncludeCases] = useState(false);
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);

  const pathname = usePathname();
  const router = useRouter();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const handleCitationClick = useCallback((ref: CitationRef) => {
    const url = `/jurisdictions/${ref.jurisdiction_id}#${ref.section_id}`;
    router.push(url);
  }, [router]);

  // Auto-detect current jurisdiction from URL
  const currentId = pathname.match(/\/jurisdictions\/([^/]+)/)?.[1];

  // When panel opens, scope to the current jurisdiction by default
  useEffect(() => {
    if (open && currentId && selectedIds.length === 0) {
      setSelectedIds([currentId]);
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // Update scope when navigating to a different jurisdiction while panel is open
  useEffect(() => {
    if (open && currentId && !selectedIds.includes(currentId)) {
      setSelectedIds([currentId]);
    }
  }, [currentId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (open) messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, open]);

  const addJurisdiction = useCallback(
    (id: string) => {
      if (!selectedIds.includes(id)) setSelectedIds((prev) => [...prev, id]);
      setInput((prev) => prev.replace(/@[^\s]*$/, ""));
      setMentionQuery(null);
      setMentionIndex(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    },
    [selectedIds]
  );

  const removeJurisdiction = useCallback((id: string) => {
    setSelectedIds((prev) => prev.filter((x) => x !== id));
  }, []);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setInput(val);

    const atIdx = val.lastIndexOf("@");
    if (atIdx !== -1 && (atIdx === 0 || /\s/.test(val[atIdx - 1]))) {
      const query = val.slice(atIdx + 1).toLowerCase();
      setMentionQuery(query);
      setMentionIndex(0);
    } else {
      setMentionQuery(null);
    }
  };

  const mentionResults =
    mentionQuery !== null
      ? jurisdictions
          .filter(
            (j) =>
              j.jurisdiction_name.toLowerCase().includes(mentionQuery) ||
              j.jurisdiction_id.toLowerCase().includes(mentionQuery)
          )
          .slice(0, 8)
      : [];

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMentionQuery(null);

    const history = [...messages];
    const next: Message[] = [...history, { role: "user", content: text }];
    setMessages(next);
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/jurisdictions/knowledge-chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          jurisdiction_ids: selectedIds,
          include_cases: includeCases,
          history: history.map((m) => ({ role: m.role, content: m.content })),
        }),
      });

      if (!res.ok) {
        const detail = await res.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(detail.detail ?? `API ${res.status}`);
      }

      const data = await res.json();
      setMessages([...next, { role: "assistant", content: data.response, citations: data.citations ?? [] }]);
    } catch (err) {
      setMessages([
        ...next,
        { role: "assistant", content: `Error: ${err instanceof Error ? err.message : "Something went wrong"}` },
      ]);
    } finally {
      setLoading(false);
    }
  }, [input, loading, messages, selectedIds, includeCases]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mentionResults.length > 0) {
      if (e.key === "ArrowDown") { e.preventDefault(); setMentionIndex((i) => Math.min(i + 1, mentionResults.length - 1)); return; }
      if (e.key === "ArrowUp")   { e.preventDefault(); setMentionIndex((i) => Math.max(i - 1, 0)); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); addJurisdiction(mentionResults[mentionIndex].jurisdiction_id); return; }
      if (e.key === "Escape") { setMentionQuery(null); return; }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const selectedJurisdictions = jurisdictions.filter((j) => selectedIds.includes(j.jurisdiction_id));
  const isAllJurisdictions = selectedIds.length === 0;

  return (
    <>
      {/* Floating button */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-40 flex items-center gap-2 rounded-full bg-ink text-canvas px-4 py-2.5 text-[13px] font-medium shadow-lg hover:bg-ink/80 transition-all"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M14 1H2C1.45 1 1 1.45 1 2v9c0 .55.45 1 1 1h2v3l3-3h7c.55 0 1-.45 1-1V2c0-.55-.45-1-1-1z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/>
          </svg>
          Ask AI
        </button>
      )}

      {/* Drawer */}
      {open && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40 bg-black/10 backdrop-blur-[1px]"
            onClick={() => setOpen(false)}
          />

          {/* Panel */}
          <div className="fixed top-0 right-0 bottom-0 z-50 w-[400px] bg-canvas border-l border-line flex flex-col shadow-2xl">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-line flex-shrink-0">
              <div>
                <h2 className="text-[14px] font-semibold text-ink">Jurisdiction AI</h2>
                <p className="text-[11px] text-faint">Ask about merger control rules</p>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="w-7 h-7 flex items-center justify-center rounded-full text-faint hover:text-ink hover:bg-slatey-soft transition-colors text-[16px]"
              >
                ×
              </button>
            </div>

            {/* Scope bar */}
            <div className="px-4 py-2.5 border-b border-line bg-surface/60 flex-shrink-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[10px] font-medium uppercase tracking-wide text-faint mr-0.5">Scope</span>

                {isAllJurisdictions ? (
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-brand-soft text-brand">
                    All jurisdictions
                  </span>
                ) : (
                  selectedJurisdictions.map((j) => (
                    <button
                      key={j.jurisdiction_id}
                      onClick={() => removeJurisdiction(j.jurisdiction_id)}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-brand text-white hover:bg-brand/80 transition-colors"
                    >
                      {j.jurisdiction_name}
                      <span className="text-[10px] opacity-70">×</span>
                    </button>
                  ))
                )}

                {!isAllJurisdictions && (
                  <button
                    onClick={() => setSelectedIds([])}
                    className="px-2 py-0.5 rounded-full text-[11px] text-faint hover:text-ink hover:bg-slatey-soft transition-colors"
                  >
                    Switch to all
                  </button>
                )}
              </div>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
              {messages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-center px-6">
                  <p className="text-[13px] font-medium text-ink mb-1">
                    {isAllJurisdictions
                      ? "Ask about any jurisdiction"
                      : `Asking about ${selectedJurisdictions.map((j) => j.jurisdiction_name).join(", ")}`}
                  </p>
                  <p className="text-[12px] text-faint">
                    Try: &quot;What are the filing thresholds?&quot; or &quot;How does mandatory filing work here?&quot;
                  </p>
                  <p className="text-[11px] text-faint mt-3">
                    Type @ to switch jurisdiction mid-conversation
                  </p>
                </div>
              )}

              {messages.map((m, i) => (
                <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  {m.role === "user" ? (
                    <div className="bg-brand text-white rounded-2xl rounded-tr-sm px-3 py-2 text-[13px] max-w-[85%] leading-relaxed">
                      {m.content}
                    </div>
                  ) : (
                    <div className="bg-surface border border-line rounded-2xl rounded-tl-sm px-3 py-2 text-[13px] text-ink max-w-[90%] leading-relaxed">
                      <p className="whitespace-pre-wrap">
                        {m.citations && m.citations.length > 0
                          ? renderWithCitations(m.content, m.citations, handleCitationClick)
                          : m.content}
                      </p>
                      {m.citations && m.citations.length > 0 && (
                        <div className="mt-2 pt-2 border-t border-line space-y-1">
                          {m.citations.map((c) => (
                            <button
                              key={c.n}
                              onClick={() => handleCitationClick(c)}
                              className="flex items-center gap-1.5 text-left w-full hover:text-brand transition-colors group"
                            >
                              <span className="flex-shrink-0 w-4 h-4 rounded-full bg-brand/10 text-brand text-[9px] font-bold flex items-center justify-center group-hover:bg-brand group-hover:text-white transition-colors">
                                {c.n}
                              </span>
                              <span className="text-[11px] text-faint group-hover:text-brand transition-colors truncate">
                                {c.label}
                              </span>
                              <span className="ml-auto text-[10px] text-faint flex-shrink-0">↗</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}

              {loading && (
                <div className="flex justify-start">
                  <div className="bg-surface border border-line rounded-2xl rounded-tl-sm px-3 py-2 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-faint animate-bounce [animation-delay:0ms]" />
                    <span className="w-1.5 h-1.5 rounded-full bg-faint animate-bounce [animation-delay:150ms]" />
                    <span className="w-1.5 h-1.5 rounded-full bg-faint animate-bounce [animation-delay:300ms]" />
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Input area */}
            <div className="px-4 py-3 border-t border-line flex-shrink-0 relative">
              {/* @mention dropdown */}
              {mentionResults.length > 0 && (
                <div className="absolute bottom-full left-4 right-4 mb-1 bg-canvas border border-line rounded-xl shadow-lg overflow-hidden z-10">
                  <p className="px-3 py-1.5 text-[10px] font-medium uppercase tracking-wide text-faint border-b border-line">
                    Add jurisdiction
                  </p>
                  {mentionResults.map((j, idx) => (
                    <button
                      key={j.jurisdiction_id}
                      onClick={() => addJurisdiction(j.jurisdiction_id)}
                      className={`w-full text-left px-3 py-2 text-[13px] flex items-center gap-2 transition-colors ${
                        idx === mentionIndex ? "bg-brand-soft text-brand" : "hover:bg-surface text-ink"
                      }`}
                    >
                      <span
                        className="flex-shrink-0 w-5 h-5 rounded-[3px] flex items-center justify-center text-[9px] font-bold"
                        style={{ background: "var(--line)", color: "var(--slatey)" }}
                      >
                        {j.jurisdiction_id.slice(0, 2).toUpperCase()}
                      </span>
                      {j.jurisdiction_name}
                      <span className="ml-auto text-[11px] text-faint">{j.authority}</span>
                    </button>
                  ))}
                </div>
              )}

              <textarea
                ref={inputRef}
                value={input}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                placeholder="Ask a question… (@ to tag a jurisdiction)"
                rows={2}
                className="w-full resize-none rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand transition-colors"
              />

              <div className="flex items-center justify-between mt-2">
                <label className="flex items-center gap-1.5 text-[11px] text-faint cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={includeCases}
                    onChange={(e) => setIncludeCases(e.target.checked)}
                    className="rounded"
                  />
                  Include case database
                </label>
                <button
                  onClick={sendMessage}
                  disabled={!input.trim() || loading}
                  className="px-3 py-1.5 bg-brand text-white rounded-lg text-[12px] font-medium disabled:opacity-40 hover:bg-brand/80 transition-colors"
                >
                  Send
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
