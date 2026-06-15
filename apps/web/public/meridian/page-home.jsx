// page-home.jsx
function HomePage() {
  const { navigate } = useUI();
  const D = window.MERIDIAN_DATA;
  const [q, setQ] = useState('');
  const [mode, setMode] = useState('Keyword');
  const recent = D.CASES.slice(0, 4);

  const go = () => navigate({ page: 'explore', query: q, mode });

  return (
    <div className="anim-up">
      {/* hero */}
      <section className="mx-auto max-w-content px-6 lg:px-8 pt-16 lg:pt-24 pb-12">
        <div className="max-w-reading">
          <div className="flex items-center gap-2.5 text-[12.5px] text-muted mb-6">
            <span className="font-semibold uppercase tracking-[0.08em] text-faint">Market-definition research</span>
            <span className="w-1 h-1 rounded-full bg-line-strong" />
            <span className="font-mono whitespace-nowrap">EU · UK · US</span>
          </div>
          <h1 className="font-serif text-ink" style={{ fontSize: 'clamp(36px, 5.4vw, 60px)', lineHeight: 1.04, letterSpacing: '-0.015em' }}>
            Every market definition,<br />traced to its source.
          </h1>
          <p className="mt-6 text-[18px] leading-relaxed text-muted max-w-2xl" style={{ textWrap: 'pretty' }}>
            Search merger precedent across the European Commission, CMA, and DOJ/FTC.
            Find how regulators defined a market, which theories of harm applied, and the exact paragraph that says so.
          </p>

          {/* search entry */}
          <div className="mt-9 max-w-2xl">
            <div className="flex items-center gap-3 mb-3">
              <Segmented options={['Keyword', 'Semantic']} value={mode} onChange={setMode} size="sm" />
              <span className="text-[12.5px] text-faint">
                {mode === 'Semantic' ? 'Concept search across definitions & reasoning' : 'Exact terms in parties, markets & theories'}
              </span>
            </div>
            <div className="flex items-stretch gap-2">
              <div className="relative flex-1">
                <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-faint">
                  <Icon d={I.search} size={18} />
                </span>
                <input value={q} onChange={(e) => setQ(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && go()}
                  placeholder="e.g. cloud gaming, input foreclosure, vegetable seeds…"
                  className="focus-ring w-full rounded-[9px] border border-line-strong bg-surface pl-11 pr-3 py-3 text-[15px] text-ink placeholder:text-faint" />
              </div>
              <Button size="lg" onClick={go} iconR={I.arrowR}>Search</Button>
            </div>
          </div>
        </div>

        {/* stats strip */}
        <div className="mt-14 grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-8 border-t border-line pt-8 max-w-3xl">
          <Stat value="1,284" label="Cases indexed" />
          <Stat value="3,961" label="Product markets" />
          <Stat value="263" suffix="" label="Source-reviewed cases" />
          <Stat value="3" label="Jurisdictions" />
        </div>
      </section>

      {/* entry points */}
      <section className="mx-auto max-w-content px-6 lg:px-8 pb-4">
        <Eyebrow className="mb-4">Start here</Eyebrow>
        <div className="grid md:grid-cols-3 gap-4">
          <EntryCard icon={I.search} title="Explore cases"
            body="Filter precedent by jurisdiction, sector, and outcome. Source-reviewed records carry full market definitions and citations."
            cta="Open explorer" onClick={() => navigate({ page: 'explore' })} primary />
          <EntryCard icon={I.graph} title="Market graph"
            body="Drill from sector to product market to the cases that defined it. Follow shared markets across transactions."
            cta="Open graph" onClick={() => navigate({ page: 'graph' })} />
          <EntryCard icon={I.layers} title="By definition status"
            body="See where a market was firmly defined, left open, segmented, or merely discussed — and how that varied by regulator."
            cta="Browse statuses" onClick={() => navigate({ page: 'explore' })} />
        </div>
      </section>

      {/* recent source-reviewed */}
      <section className="mx-auto max-w-content px-6 lg:px-8 pt-12">
        <div className="flex items-end justify-between mb-4">
          <div>
            <Eyebrow className="mb-1.5">Recently source-reviewed</Eyebrow>
            <p className="text-[14px] text-muted">Records checked against the underlying decision, paragraph by paragraph.</p>
          </div>
          <button onClick={() => navigate({ page: 'explore' })}
            className="focus-ring hidden sm:inline-flex items-center gap-1.5 text-[14px] font-medium text-brand-ink hover:gap-2.5 transition-all">
            All cases <Icon d={I.arrowR} size={15} />
          </button>
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          {recent.map((c) => (
            <button key={c.id} onClick={() => navigate({ page: 'case', id: c.id })}
              className="focus-ring group text-left bg-surface border border-line rounded-xl p-4 hover:border-line-strong hover:shadow-card transition-all">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1.5">
                    <Juris code={c.juris} />
                    <span className="font-mono text-[11.5px] text-faint">{c.caseNo}</span>
                  </div>
                  <div className="font-serif text-[18px] text-ink leading-snug group-hover:text-brand-ink transition-colors">{c.name}</div>
                </div>
                <OutcomeBadge outcome={c.outcome} />
              </div>
              <div className="mt-3 flex items-center gap-2 text-[12.5px] text-muted">
                <span>{c.sector}</span><span className="text-line-strong">·</span>
                <span>{c.date}</span><span className="text-line-strong">·</span>
                <span>{c.markets.length} markets</span>
              </div>
            </button>
          ))}
        </div>
      </section>

      <Footer />
    </div>
  );
}

function EntryCard({ icon, title, body, cta, onClick, primary }) {
  return (
    <button onClick={onClick}
      className={`focus-ring group text-left rounded-xl p-5 border transition-all flex flex-col h-full ${primary ? 'bg-brand text-brand-fg border-brand' : 'bg-surface border-line hover:border-line-strong hover:shadow-card'}`}>
      <span className={`inline-flex items-center justify-center w-9 h-9 rounded-[9px] mb-4 ${primary ? 'bg-white/15 text-brand-fg' : 'bg-brand-soft text-brand-ink'}`}>
        <Icon d={icon} size={19} />
      </span>
      <div className={`text-[16px] font-semibold mb-1.5 ${primary ? 'text-brand-fg' : 'text-ink'}`}>{title}</div>
      <p className={`text-[13.5px] leading-relaxed mb-4 flex-1 ${primary ? 'text-brand-fg/85' : 'text-muted'}`} style={{ textWrap: 'pretty' }}>{body}</p>
      <span className={`inline-flex items-center gap-1.5 text-[13.5px] font-medium ${primary ? 'text-brand-fg' : 'text-brand-ink'} group-hover:gap-2.5 transition-all`}>
        {cta} <Icon d={I.arrowR} size={15} />
      </span>
    </button>
  );
}

window.HomePage = HomePage;
