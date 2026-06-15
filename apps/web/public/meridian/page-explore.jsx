// page-explore.jsx
const { useState: useStateX } = React;

function StyledSelect({ label, value, onChange, options }) {
  return (
    <label className="block">
      <Eyebrow className="mb-2">{label}</Eyebrow>
      <div className="relative">
        <select value={value} onChange={(e) => onChange(e.target.value)}
          className="focus-ring w-full appearance-none rounded-[8px] border border-line-strong bg-surface pl-3 pr-9 py-2.5 text-[14px] text-ink cursor-pointer hover:border-faint transition-colors">
          {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-faint">
          <Icon d={I.chevD} size={16} />
        </span>
      </div>
    </label>
  );
}

function cardShell(style, hover) {
  if (style === 'filled') return `bg-surface shadow-card rounded-xl border border-transparent ${hover ? 'hover:shadow-raised' : ''}`;
  if (style === 'divided') return 'bg-transparent border-b border-line rounded-none';
  return `bg-surface border border-line rounded-xl ${hover ? 'hover:border-line-strong hover:shadow-card' : ''}`;
}

// rich, source-reviewed case
function CaseCard({ c, onOpen, compact }) {
  const { t } = useUI();
  const shell = cardShell(t.cardStyle || 'bordered', true);
  const pad = (t.cardStyle === 'divided') ? 'py-6' : 'p-5';
  const shown = c.markets.slice(0, compact ? 2 : 3);
  const moreM = c.markets.length - shown.length;
  const cites = c.markets.reduce((n, m) => n + (m.sources ? m.sources.length : 0), 0);

  return (
    <button onClick={onOpen} className={`focus-ring group block w-full text-left transition-all ${shell} ${pad}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5 mb-1.5">
            <Juris code={c.juris} />
            <span className="font-mono text-[11.5px] text-faint">{c.caseNo}</span>
            <span className="inline-flex items-center gap-1 whitespace-nowrap text-[11.5px] font-medium text-pos-ink">
              <Icon d={I.check} size={13} sw={2.2} /> Source-reviewed
            </span>
          </div>
          <h3 className="font-serif text-[21px] text-ink leading-snug group-hover:text-brand-ink transition-colors">{c.name}</h3>
        </div>
        <OutcomeBadge outcome={c.outcome} />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px] text-muted">
        <span>{window.MERIDIAN_DATA.JURIS[c.juris].authority}</span>
        <span className="text-line-strong">·</span><span>{c.date}</span>
        <span className="text-line-strong">·</span><span>{c.sector}</span>
        <span className="text-line-strong">·</span><span>{c.stage}</span>
      </div>

      {!compact && (
        <div className="mt-4 space-y-1.5">
          {shown.map((m, i) => (
            <div key={i} className="flex items-center gap-2.5 rounded-[7px] bg-canvas border border-line/70 px-3 py-2">
              <span className="text-[13.5px] text-ink truncate flex-1">{m.name}</span>
              <DefinitionBadge status={m.status} />
            </div>
          ))}
          {moreM > 0 && <div className="text-[12.5px] text-faint pl-1">+{moreM} more product market{moreM > 1 ? 's' : ''}</div>}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {c.theories.slice(0, compact ? 1 : 2).map((th, i) => (
            <TheoryTag key={i}>{th.label.length > 46 ? th.label.slice(0, 44) + '…' : th.label}</TheoryTag>
          ))}
        </div>
        <span className="inline-flex items-center gap-1.5 text-[12px] font-mono text-faint whitespace-nowrap">
          {c.markets.length} markets · {cites} citations
        </span>
      </div>
    </button>
  );
}

// indexed (metadata-only) row — visually recessed
function IndexedRow({ c, onOpen }) {
  return (
    <button onClick={onOpen}
      className="focus-ring group grid grid-cols-[auto_1fr_auto] items-center gap-4 w-full text-left rounded-[9px] border border-dashed border-line bg-canvas/40 px-4 py-3 hover:border-line-strong hover:bg-canvas transition-all">
      <Juris code={c.juris} />
      <div className="min-w-0">
        <div className="flex items-center gap-2.5">
          <span className="text-[15px] font-medium text-ink truncate group-hover:text-brand-ink transition-colors">{c.name}</span>
          <span className="hidden sm:inline text-[11px] font-medium uppercase tracking-[0.06em] text-faint border border-line rounded-[4px] px-1.5 py-[1px]">Indexed</span>
        </div>
        <div className="mt-0.5 text-[12.5px] text-muted flex items-center gap-2">
          <span>{c.sector}</span><span className="text-line-strong">·</span>
          <span>{c.date}</span><span className="text-line-strong">·</span>
          <span>{c.marketCount} markets</span>
        </div>
      </div>
      <OutcomeBadge outcome={c.outcome} />
    </button>
  );
}

function ExplorePage() {
  const { navigate, route } = useUI();
  const D = window.MERIDIAN_DATA;
  const [mode, setMode] = useState(route.mode || 'Keyword');
  const [q, setQ] = useState(route.query || '');
  const [juris, setJuris] = useState('all');
  const [sector, setSector] = useState('all');
  const [outcome, setOutcome] = useState('all');

  const sectors = useMemo(() => {
    const s = new Set();
    [...D.CASES, ...D.INDEXED].forEach((c) => s.add(c.sector));
    return ['all', ...[...s].sort()];
  }, []);

  const matchText = (c) => {
    if (!q.trim()) return true;
    const hay = [c.name, c.sector, ...(c.markets || []).map((m) => m.name), ...(c.theories || []).map((t) => t.label)].join(' ').toLowerCase();
    return hay.includes(q.toLowerCase());
  };
  const matchFilters = (c) => (juris === 'all' || c.juris === juris) && (sector === 'all' || c.sector === sector) && (outcome === 'all' || c.outcome === outcome);

  const rich = D.CASES.filter((c) => matchText(c) && matchFilters(c));
  const indexed = D.INDEXED.filter((c) => matchText(c) && matchFilters(c));
  const reset = () => { setQ(''); setJuris('all'); setSector('all'); setOutcome('all'); };
  const anyFilter = q || juris !== 'all' || sector !== 'all' || outcome !== 'all';

  const open = (id) => navigate({ page: 'case', id });
  const { t } = useUI();
  const layout = t.exploreLayout || 'tiered';
  const divided = (t.cardStyle || 'bordered') === 'divided';

  return (
    <div className="mx-auto max-w-content px-6 lg:px-8 py-10 anim-up">
      <PageHeader title="Explore cases"
        subtitle="Search merger precedent by keyword or semantics, then filter by jurisdiction, sector, and outcome. Source-reviewed records carry full market definitions; indexed records carry metadata only." />

      <div className="grid lg:grid-cols-[268px_1fr] gap-8">
        {/* sidebar */}
        <aside className="lg:sticky lg:top-[74px] self-start space-y-6">
          <div>
            <Eyebrow className="mb-2">Search mode</Eyebrow>
            <Segmented options={['Keyword', 'Semantic']} value={mode} onChange={setMode} size="sm" />
          </div>
          <label className="block">
            <Eyebrow className="mb-2">Search</Eyebrow>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-faint"><Icon d={I.search} size={16} /></span>
              <input value={q} onChange={(e) => setQ(e.target.value)}
                placeholder="wearables, foreclosure…"
                className="focus-ring w-full rounded-[8px] border border-line-strong bg-surface pl-9 pr-3 py-2.5 text-[14px] text-ink placeholder:text-faint" />
            </div>
          </label>
          <StyledSelect label="Jurisdiction" value={juris} onChange={setJuris}
            options={[{ value: 'all', label: 'All jurisdictions' }, { value: 'EU', label: 'European Union' }, { value: 'UK', label: 'United Kingdom' }, { value: 'US', label: 'United States' }]} />
          <StyledSelect label="Sector" value={sector} onChange={setSector}
            options={sectors.map((s) => ({ value: s, label: s === 'all' ? 'All sectors' : s }))} />
          <StyledSelect label="Outcome" value={outcome} onChange={setOutcome}
            options={[{ value: 'all', label: 'All outcomes' }, { value: 'cleared', label: 'Cleared' }, { value: 'conditions', label: 'Cleared with conditions' }, { value: 'blocked', label: 'Blocked' }, { value: 'abandoned', label: 'Abandoned' }]} />
          {anyFilter && (
            <button onClick={reset} className="focus-ring inline-flex items-center gap-1.5 text-[13px] font-medium text-brand-ink hover:underline">
              <Icon d={I.reset} size={14} /> Reset filters
            </button>
          )}

          <div className="pt-2 border-t border-line">
            <Eyebrow className="mb-3">Definition status</Eyebrow>
            <div className="space-y-2">
              {[['defined', 'Market firmly defined'], ['left_open', 'Definition left open'], ['segmented', 'Segmented into sub-markets'], ['discussed', 'Discussed, not delineated']].map(([k, label]) => (
                <div key={k} className="flex items-center gap-2.5 text-[13px] text-muted">
                  <DefinitionBadge status={k} /><span>{label}</span>
                </div>
              ))}
            </div>
          </div>
        </aside>

        {/* results */}
        <div>
          <div className="flex items-center justify-between mb-5 pb-3 border-b border-line">
            <div className="flex items-baseline gap-2.5 whitespace-nowrap">
              <span className="text-[15px] font-semibold text-ink">{rich.length} source-reviewed</span>
              <span className="text-faint">·</span>
              <span className="text-[15px] text-muted">{indexed.length} indexed</span>
            </div>
            <span className="hidden sm:inline text-[12.5px] text-faint font-mono">layout · {layout}</span>
          </div>

          {rich.length === 0 && indexed.length === 0 ? (
            <div className="text-center py-20 text-muted">
              <p className="text-[15px]">No cases match those filters.</p>
              <button onClick={reset} className="focus-ring mt-3 text-[14px] font-medium text-brand-ink hover:underline">Reset filters</button>
            </div>
          ) : layout === 'compact' ? (
            <div className="space-y-2">
              {rich.map((c) => <CaseCard key={c.id} c={c} onOpen={() => open(c.id)} compact />)}
              {indexed.map((c) => <IndexedRow key={c.id} c={c} onOpen={() => open(c.id)} />)}
            </div>
          ) : layout === 'unified' ? (
            <div className={divided ? 'border-t border-line' : 'space-y-3'}>
              {interleave(rich, indexed).map((c) => c._indexed
                ? <div key={c.id} className="py-2"><IndexedRow c={c} onOpen={() => open(c.id)} /></div>
                : <CaseCard key={c.id} c={c} onOpen={() => open(c.id)} />)}
            </div>
          ) : (
            <>
              <div className={divided ? 'border-t border-line' : 'space-y-3'}>
                {rich.map((c) => <CaseCard key={c.id} c={c} onOpen={() => open(c.id)} />)}
              </div>
              {indexed.length > 0 && (
                <div className="mt-9">
                  <div className="flex items-center gap-3 mb-3">
                    <span className="text-[12px] font-semibold uppercase tracking-[0.08em] text-faint">Indexed · metadata only</span>
                    <span className="flex-1 h-px bg-line" />
                    <span className="text-[12px] text-faint">{indexed.length}</span>
                  </div>
                  <div className="space-y-2">
                    {indexed.map((c) => <IndexedRow key={c.id} c={c} onOpen={() => open(c.id)} />)}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function interleave(rich, indexed) {
  const out = [];
  const maxLen = Math.max(rich.length, indexed.length);
  for (let i = 0; i < maxLen; i++) {
    if (rich[i]) out.push(rich[i]);
    if (indexed[i]) out.push({ ...indexed[i], _indexed: true });
  }
  return out;
}

window.ExplorePage = ExplorePage;
window.CaseCard = CaseCard;
window.IndexedRow = IndexedRow;
window.StyledSelect = StyledSelect;
window.cardShell = cardShell;
