// page-case.jsx
function CasePage() {
  const { navigate, route } = useUI();
  const D = window.MERIDIAN_DATA;
  const c = D.CASE_BY_ID[route.id] || D.CASES[0];
  const [src, setSrc] = useState(null); // {p, para, market}

  const J = D.JURIS[c.juris];
  const cites = c.markets.reduce((n, m) => n + (m.sources ? m.sources.length : 0), 0);

  return (
    <div className="mx-auto max-w-content px-6 lg:px-8 py-8 anim-up">
      {/* breadcrumb */}
      <button onClick={() => navigate({ page: 'explore' })}
        className="focus-ring inline-flex items-center gap-1.5 text-[13.5px] text-muted hover:text-ink mb-6 transition-colors">
        <Icon d={I.arrowL} size={15} /> Explore
      </button>

      {/* header */}
      <div className="flex flex-wrap items-start justify-between gap-5 pb-7 border-b border-line">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5 mb-3">
            <Juris code={c.juris} />
            <span className="font-mono text-[12px] text-faint">{c.caseNo}</span>
            <span className="inline-flex items-center gap-1 whitespace-nowrap text-[11.5px] font-medium text-pos-ink">
              <Icon d={I.check} size={13} sw={2.2} /> Source-reviewed
            </span>
          </div>
          <h1 className="font-serif text-ink" style={{ fontSize: 'clamp(30px, 4vw, 44px)', lineHeight: 1.05, letterSpacing: '-0.01em' }}>{c.name}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <OutcomeBadge outcome={c.outcome} />
            <span className="text-[14px] text-muted">{J.authority} · {c.date}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" icon={I.graph} onClick={() => navigate({ page: 'graph' })}>View in graph</Button>
        </div>
      </div>

      <div className="grid lg:grid-cols-[1fr_350px] gap-8 mt-8">
        {/* main */}
        <main className="space-y-9 min-w-0">
          {/* case details */}
          <section>
            <SectionH>Case details</SectionH>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-5 mt-4">
              <Field label="Authority">{J.authority}</Field>
              <Field label="Decision date">{c.date}</Field>
              <Field label="Jurisdiction"><Juris code={c.juris} /></Field>
              <Field label="Stage">{c.stage}</Field>
              <Field label="Sector">{c.sector}</Field>
              <Field label="Case type">{c.caseType}</Field>
            </div>
          </section>

          {/* parties */}
          <section>
            <SectionH>Parties</SectionH>
            <div className="flex flex-wrap gap-3 mt-4">
              {c.parties.map((p, i) => (
                <div key={i} className="flex items-center gap-3 rounded-[10px] border border-line bg-surface pl-4 pr-3 py-2.5">
                  <span className="text-[15px] font-medium text-ink whitespace-nowrap">{p.name}</span>
                  <span className="text-[11px] font-medium uppercase tracking-[0.06em] text-muted bg-slatey-soft rounded-[5px] px-2 py-[3px]">{p.role}</span>
                </div>
              ))}
            </div>
          </section>

          {/* theories of harm */}
          <section>
            <SectionH>Theories of harm</SectionH>
            <div className="mt-4 space-y-2.5">
              {c.theories.map((th, i) => (
                <div key={i} className="flex items-start gap-3 rounded-[10px] border border-line bg-surface px-4 py-3">
                  <span className="mt-1 w-1.5 h-1.5 rounded-full bg-neg shrink-0" />
                  <div>
                    <div className="text-[15px] text-ink leading-snug">{th.label}</div>
                    <div className="mt-0.5 text-[12px] font-mono uppercase tracking-[0.05em] text-faint">{th.type}</div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* product markets */}
          <section>
            <div className="flex items-center justify-between">
              <SectionH>Product markets considered</SectionH>
              <span className="text-[12.5px] text-faint font-mono">{c.markets.length} markets · {cites} citations</span>
            </div>
            <div className="mt-4 space-y-3">
              {c.markets.map((m, i) => (
                <div key={i} className="rounded-xl border border-line bg-surface p-5">
                  <div className="flex items-start justify-between gap-4">
                    <h3 className="text-[16.5px] font-semibold text-ink leading-snug">{m.name}</h3>
                    <DefinitionBadge status={m.status} />
                  </div>
                  <p className="mt-2.5 text-[14.5px] leading-relaxed text-muted" style={{ textWrap: 'pretty' }}>{m.defn}</p>
                  {m.sources && m.sources.length > 0 && (
                    <div className="mt-3.5 flex flex-wrap items-center gap-2">
                      <span className="text-[11px] font-semibold uppercase tracking-[0.07em] text-faint mr-0.5">Source</span>
                      {m.sources.map((s, j) => (
                        <SourceChip key={j} p={s.p} para={s.para} onClick={() => setSrc({ ...s, market: m.name })} />
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        </main>

        {/* sidebar */}
        <aside className="space-y-5 lg:sticky lg:top-[74px] self-start">
          {/* AI summary */}
          <div className="rounded-xl border border-ai/30 bg-ai-soft/50 p-5">
            <div className="flex items-center justify-between mb-2.5">
              <div className="flex items-center gap-2 text-ai-ink">
                <Icon d={I.spark} size={16} />
                <span className="text-[13px] font-semibold">Summary</span>
              </div>
              <span className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-ai-ink border border-ai/40 rounded-[4px] px-1.5 py-[2px]">AI-generated</span>
            </div>
            <p className="text-[14px] leading-relaxed text-ink/90" style={{ textWrap: 'pretty' }}>{c.aiSummary}</p>
            <p className="mt-3 text-[11.5px] text-ai-ink/80">Generated from the decision text. Verify against the source before relying on it.</p>
          </div>

          {/* source documents */}
          <Panel>
            <Eyebrow className="mb-3">Source documents</Eyebrow>
            <div className="space-y-1">
              {c.sourceDocs.map((d, i) => (
                <a key={i} href="#" onClick={(e) => e.preventDefault()}
                  className="focus-ring group flex items-center gap-3 rounded-[8px] -mx-2 px-2 py-2 hover:bg-slatey-soft/60 transition-colors">
                  <span className="text-muted group-hover:text-brand-ink"><Icon d={d.kind === 'pdf' ? I.doc : I.link} size={17} /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13.5px] font-medium text-ink group-hover:text-brand-ink transition-colors truncate">{d.label}</span>
                    <span className="block text-[11.5px] text-faint font-mono">{d.meta}</span>
                  </span>
                  <Icon d={I.ext} size={14} className="text-faint" />
                </a>
              ))}
            </div>
          </Panel>

          {/* case history */}
          <Panel>
            <Eyebrow className="mb-3.5">Case history</Eyebrow>
            <ol className="relative space-y-4 pl-4">
              <span className="absolute left-[3px] top-1.5 bottom-1.5 w-px bg-line" />
              {c.history.map((h, i) => (
                <li key={i} className="relative">
                  <span className={`absolute -left-4 top-1 w-[7px] h-[7px] rounded-full ring-2 ring-surface ${i === c.history.length - 1 ? 'bg-brand' : 'bg-line-strong'}`} />
                  <div className="text-[11.5px] font-mono text-faint">{h.date}</div>
                  <div className="text-[13.5px] text-ink leading-snug mt-0.5">{h.label}</div>
                </li>
              ))}
            </ol>
          </Panel>

          {/* graph neighbourhood */}
          {c.related && c.related.length > 0 && (
            <Panel>
              <div className="flex items-center justify-between mb-3">
                <Eyebrow>Related cases</Eyebrow>
                <Icon d={I.graph} size={15} className="text-faint" />
              </div>
              <div className="space-y-1">
                {c.related.map((rid) => {
                  const r = D.CASE_BY_ID[rid] || D.ALL_INDEXED_BY_ID[rid];
                  if (!r) return null;
                  return (
                    <button key={rid} onClick={() => r.markets ? navigate({ page: 'case', id: rid }) : null}
                      className="focus-ring group flex items-center justify-between gap-3 w-full text-left rounded-[8px] -mx-2 px-2 py-2 hover:bg-slatey-soft/60 transition-colors">
                      <span className="flex items-center gap-2 min-w-0">
                        <Juris code={r.juris} />
                        <span className="text-[13.5px] text-ink truncate group-hover:text-brand-ink transition-colors">{r.name}</span>
                      </span>
                      <Icon d={I.arrowR} size={14} className="text-faint shrink-0" />
                    </button>
                  );
                })}
              </div>
            </Panel>
          )}
        </aside>
      </div>

      {/* source passage drawer */}
      <SourceDrawer src={src} caseName={c.name} onClose={() => setSrc(null)} />
    </div>
  );
}

function SectionH({ children }) {
  return <h2 className="text-[19px] font-semibold text-ink tracking-tight">{children}</h2>;
}

function SourceDrawer({ src, caseName, onClose }) {
  return (
    <>
      <div onClick={onClose}
        className={`fixed inset-0 z-40 bg-ink/30 backdrop-blur-[1px] transition-opacity duration-200 ${src ? 'opacity-100' : 'opacity-0 pointer-events-none'}`} />
      <div className={`fixed top-0 right-0 z-50 h-full w-full max-w-[460px] bg-surface border-l border-line shadow-raised transition-transform duration-300 ease-out ${src ? 'translate-x-0' : 'translate-x-full'}`}>
        {src && (
          <div className="flex flex-col h-full">
            <div className="flex items-center justify-between px-5 py-4 border-b border-line">
              <div className="flex items-center gap-2 text-[13px] text-muted">
                <Icon d={I.doc} size={16} /> Source passage
              </div>
              <button onClick={onClose} className="focus-ring rounded-[7px] p-1.5 text-muted hover:text-ink hover:bg-slatey-soft transition-colors"><Icon d={I.x} size={16} /></button>
            </div>
            <div className="px-5 py-5 overflow-y-auto thin-scroll">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-mono text-[12px] font-semibold text-brand-ink bg-brand-soft rounded-[4px] px-1.5 py-[2px]">p.{src.p}</span>
                <span className="font-mono text-[12px] text-faint">¶{src.para}</span>
              </div>
              <div className="text-[12.5px] text-faint mb-4">{caseName} — Decision</div>
              <div className="rounded-xl border border-line bg-canvas/60 p-4">
                <div className="text-[11px] font-semibold uppercase tracking-[0.07em] text-faint mb-2">{src.market}</div>
                <p className="text-[14.5px] leading-relaxed text-ink font-serif" style={{ textWrap: 'pretty' }}>
                  “The Commission considers that the relevant product market should be assessed on the narrowest plausible
                  basis. On the evidence before it, demand-side substitution is limited and the parties’ activities
                  overlap to a material degree within the candidate market identified at paragraph {src.para}.”
                </p>
              </div>
              <div className="placeholder-stripe mt-4 rounded-xl border border-line h-44 flex items-center justify-center">
                <span className="font-mono text-[11.5px] text-faint">decision page p.{src.p} · facsimile</span>
              </div>
              <div className="mt-4 flex items-center gap-2">
                <Button variant="secondary" size="sm" iconR={I.ext}>Open full decision</Button>
                <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

window.CasePage = CasePage;
