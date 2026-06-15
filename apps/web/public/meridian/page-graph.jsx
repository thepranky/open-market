// page-graph.jsx
const STATUS_COLOR = {
  defined: 'var(--pos)', left_open: 'var(--ai)', segmented: 'var(--seg)', discussed: 'var(--slatey)', sector: 'var(--brand)',
};

function genMarkets(sectorKey, label) {
  const base = ['Wholesale supply', 'Retail distribution', 'Licensing & IP', 'Equipment & systems', 'Aftermarket services', 'Cross-border logistics'];
  const st = ['defined', 'left_open', 'segmented', 'discussed', 'defined', 'left_open'];
  return base.map((b, i) => ({ id: `${sectorKey}_m${i}`, name: `${b} — ${label}`, status: st[i % st.length], cases: ((i * 3 + 2) % 6) + 1 }));
}

function GraphLegend() {
  const items = [['defined', 'defined'], ['left_open', 'left open'], ['segmented', 'segmented'], ['discussed', 'discussed']];
  return (
    <div className="flex items-center gap-4">
      {items.map(([k, label]) => (
        <span key={k} className="flex items-center gap-1.5 text-[12.5px] text-muted">
          <span className="w-2.5 h-2.5 rounded-full" style={{ background: STATUS_COLOR[k] }} />{label}
        </span>
      ))}
    </div>
  );
}

function GraphPage() {
  const { navigate } = useUI();
  const D = window.MERIDIAN_DATA;
  const { t } = useUI();
  const layout = t.graphLayout || 'radial';

  const [hist, setHist] = useState([[]]);
  const [hi, setHi] = useState(0);
  const path = hist[hi];

  const navTo = (newPath) => {
    const h = hist.slice(0, hi + 1);
    h.push(newPath);
    setHist(h); setHi(h.length - 1);
  };
  const back = () => hi > 0 && setHi(hi - 1);
  const fwd = () => hi < hist.length - 1 && setHi(hi + 1);

  // resolve children of current path
  const children = useMemo(() => {
    if (path.length === 0) {
      return { kind: 'sector', items: D.SECTORS.map((s) => ({ key: s.key, label: s.label, status: 'sector', count: `${s.markets} markets`, sub: `${s.cases} cases` })) };
    }
    if (path.length === 1) {
      const ms = D.MARKETS[path[0].key] || genMarkets(path[0].key, path[0].label);
      return { kind: 'market', items: ms.map((m) => ({ key: m.id, label: m.name, status: m.status, count: `${m.cases} cases`, sub: DEFN_LABEL[m.status] })) };
    }
    const ids = D.MARKET_CASES[path[1].key] || [];
    let items = ids.map((id) => { const c = D.CASE_BY_ID[id] || D.ALL_INDEXED_BY_ID[id]; return c ? { key: id, label: c.name, status: c.markets ? 'defined' : 'discussed', count: c.juris, sub: OUTCOME_LABEL[c.outcome], real: !!c.markets, juris: c.juris } : null; }).filter(Boolean);
    if (items.length === 0) items = [{ key: 'placeholder', label: 'Indexed cases only', status: 'discussed', count: '—', sub: 'No source-reviewed record', real: false }];
    return { kind: 'case', items };
  }, [hi]);

  const onChild = (item) => {
    if (children.kind === 'sector') navTo([{ type: 'sector', key: item.key, label: item.label }]);
    else if (children.kind === 'market') navTo([path[0], { type: 'market', key: item.key, label: item.label }]);
    else if (item.real) navigate({ page: 'case', id: item.key });
  };

  const crumb = [{ type: 'root', key: 'root', label: 'Sectors' }, ...path];
  const goCrumb = (idx) => navTo(path.slice(0, idx));

  const countLabel = children.kind === 'sector' ? `${D.SECTORS.length} sectors`
    : children.kind === 'market' ? `${children.items.length} markets in ${path[0].label.toLowerCase()}`
      : `${children.items.length} case${children.items.length !== 1 ? 's' : ''} for ${path[path.length - 1].label}`;

  return (
    <div className="mx-auto max-w-content px-6 lg:px-8 py-10 anim-up">
      <PageHeader title="Market graph"
        subtitle="Browse by sector, drill into product markets, and discover the cases that defined them. Use back / forward to retrace your path." />

      {/* nav chrome toolbar */}
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <div className="flex items-center gap-1 rounded-[9px] border border-line bg-surface p-1">
          <button onClick={back} disabled={hi === 0}
            className="focus-ring rounded-[6px] p-1.5 text-muted enabled:hover:bg-slatey-soft enabled:hover:text-ink disabled:opacity-35 transition-colors" title="Back">
            <Icon d={I.arrowL} size={17} />
          </button>
          <button onClick={fwd} disabled={hi >= hist.length - 1}
            className="focus-ring rounded-[6px] p-1.5 text-muted enabled:hover:bg-slatey-soft enabled:hover:text-ink disabled:opacity-35 transition-colors" title="Forward">
            <Icon d={I.arrowR} size={17} />
          </button>
        </div>

        {/* breadcrumb */}
        <nav className="flex items-center gap-1 text-[14px] min-w-0">
          {crumb.map((b, i) => (
            <span key={i} className="flex items-center gap-1 min-w-0">
              {i > 0 && <Icon d={I.chevR} size={14} className="text-line-strong shrink-0" />}
              <button onClick={() => goCrumb(i)}
                className={`focus-ring rounded-[6px] px-2 py-1 truncate transition-colors ${i === crumb.length - 1 ? 'text-ink font-medium bg-slatey-soft' : 'text-muted hover:text-ink hover:bg-slatey-soft/60'}`}>
                {b.label}
              </button>
            </span>
          ))}
        </nav>

        <div className="ml-auto hidden md:flex items-center gap-4">
          <GraphLegend />
        </div>
      </div>

      {/* canvas / chrome */}
      <div className="rounded-xl border border-line bg-surface overflow-hidden">
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-line bg-canvas/40">
          <span className="text-[12.5px] text-muted">Click a node to drill in{children.kind === 'case' ? ' · cases open the full record' : ''}</span>
          <span className="font-mono text-[12px] text-faint">{layout}</span>
        </div>

        {layout === 'columns'
          ? <ColumnsView D={D} path={path} navTo={navTo} navigate={navigate} />
          : layout === 'grid'
            ? <GridView children={children} onChild={onChild} />
            : <RadialView children={children} path={path} onChild={onChild} />}
      </div>

      <div className="mt-3 flex items-center justify-between">
        <span className="text-[13px] text-muted">{countLabel}</span>
        <div className="md:hidden"><GraphLegend /></div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- radial
function RadialView({ children, path, onChild }) {
  const ref = useRef(null);
  const [w, setW] = useState(960);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const ro = new ResizeObserver((es) => setW(es[0].contentRect.width));
    ro.observe(el); return () => ro.disconnect();
  }, []);
  const H = 440, cx = w / 2, cy = 78;
  const items = children.items;
  const n = items.length;
  const margin = Math.min(120, w * 0.1);
  const bottomY = 300;
  const pos = items.map((it, i) => {
    const x = n === 1 ? cx : margin + i * (w - 2 * margin) / (n - 1);
    const u = (x - cx) / (w / 2 || 1);
    const y = bottomY - (1 - u * u) * 34;
    return { x, y, it };
  });
  const parentLabel = path.length === 0 ? 'Sectors' : path[path.length - 1].label;

  return (
    <div ref={ref} className="relative w-full" style={{ height: H }}>
      <svg className="absolute inset-0 w-full h-full" style={{ pointerEvents: 'none' }}>
        {pos.map((p, i) => (
          <line key={i} x1={cx} y1={cy + 30} x2={p.x} y2={p.y - 30}
            stroke="var(--line-strong)" strokeWidth="1" />
        ))}
      </svg>
      {/* center node */}
      <div className="absolute -translate-x-1/2 -translate-y-1/2 flex flex-col items-center" style={{ left: cx, top: cy }}>
        <div className="rounded-full flex items-center justify-center text-center px-3 shadow-card"
          style={{ width: 88, height: 88, background: 'var(--brand)', color: 'var(--brand-fg)' }}>
          <span className="text-[12.5px] font-medium leading-tight line-clamp-3">{parentLabel}</span>
        </div>
      </div>
      {/* children */}
      {pos.map((p, i) => (
        <button key={i} onClick={() => onChild(p.it)}
          className="focus-ring group absolute -translate-x-1/2 -translate-y-1/2 transition-transform hover:scale-[1.06]"
          style={{ left: p.x, top: p.y }}>
          <span className="flex items-center justify-center rounded-full text-center px-2 shadow-card ring-2 ring-surface"
            style={{ width: 76, height: 76, background: STATUS_COLOR[p.it.status], color: '#fff' }}>
            <span className="text-[10.5px] font-medium leading-tight line-clamp-3" style={{ color: '#fff' }}>{p.it.label}</span>
          </span>
          <span className="block text-center text-[10.5px] text-faint mt-1.5 max-w-[88px] truncate mx-auto">{p.it.count}</span>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- columns (Miller)
function ColumnsView({ D, path, navTo, navigate }) {
  const sectorKey = path[0] ? path[0].key : null;
  const marketKey = path[1] ? path[1].key : null;
  const markets = sectorKey ? (D.MARKETS[sectorKey] || genMarkets(sectorKey, path[0].label)) : [];
  const caseIds = marketKey ? (D.MARKET_CASES[marketKey] || []) : [];

  const Col = ({ title, children, muted }) => (
    <div className="flex-1 min-w-0 flex flex-col border-r border-line last:border-r-0">
      <div className="px-3.5 py-2.5 border-b border-line"><Eyebrow>{title}</Eyebrow></div>
      <div className="overflow-y-auto thin-scroll p-1.5 space-y-0.5" style={{ maxHeight: 420 }}>{children}</div>
    </div>
  );
  const Row = ({ active, status, label, sub, onClick, chev = true, juris }) => (
    <button onClick={onClick}
      className={`focus-ring group w-full text-left rounded-[8px] px-2.5 py-2 flex items-center gap-2.5 transition-colors ${active ? 'bg-brand-soft' : 'hover:bg-slatey-soft/70'}`}>
      {juris ? <Juris code={juris} /> : <span className="w-2 h-2 rounded-full shrink-0" style={{ background: STATUS_COLOR[status] }} />}
      <span className="min-w-0 flex-1">
        <span className={`block text-[13.5px] truncate ${active ? 'text-brand-ink font-medium' : 'text-ink'}`}>{label}</span>
        {sub && <span className="block text-[11.5px] text-faint truncate">{sub}</span>}
      </span>
      {chev && <Icon d={I.chevR} size={14} className={active ? 'text-brand-ink' : 'text-line-strong group-hover:text-faint'} />}
    </button>
  );

  return (
    <div className="flex divide-line" style={{ minHeight: 460 }}>
      <Col title="Sectors">
        {D.SECTORS.map((s) => (
          <Row key={s.key} active={sectorKey === s.key} status="sector" label={s.label} sub={`${s.markets} markets · ${s.cases} cases`}
            onClick={() => navTo([{ type: 'sector', key: s.key, label: s.label }])} />
        ))}
      </Col>
      <Col title={sectorKey ? `Markets · ${path[0].label}` : 'Markets'}>
        {!sectorKey ? <Empty>Select a sector</Empty> : markets.map((m) => (
          <Row key={m.id} active={marketKey === m.id} status={m.status} label={m.name} sub={`${DEFN_LABEL[m.status]} · ${m.cases} cases`}
            onClick={() => navTo([path[0], { type: 'market', key: m.id, label: m.name }])} />
        ))}
      </Col>
      <Col title={marketKey ? 'Cases' : 'Cases'}>
        {!marketKey ? <Empty>Select a market</Empty>
          : caseIds.length === 0 ? <Empty>Indexed cases only — no source-reviewed record</Empty>
            : caseIds.map((id) => {
              const c = D.CASE_BY_ID[id] || D.ALL_INDEXED_BY_ID[id]; if (!c) return null;
              return <Row key={id} juris={c.juris} status="defined" label={c.name} sub={OUTCOME_LABEL[c.outcome]} chev={!!c.markets}
                onClick={() => c.markets && navigate({ page: 'case', id })} />;
            })}
      </Col>
    </div>
  );
}
function Empty({ children }) {
  return <div className="px-3 py-8 text-center text-[12.5px] text-faint">{children}</div>;
}

// ---------------------------------------------------------------- grid
function GridView({ children, onChild }) {
  return (
    <div className="p-5">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {children.items.map((it, i) => (
          <button key={i} onClick={() => onChild(it)}
            className="focus-ring group text-left rounded-xl border border-line bg-surface p-4 hover:border-line-strong hover:shadow-card transition-all">
            <div className="flex items-center justify-between mb-3">
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: STATUS_COLOR[it.status] }} />
              <Icon d={children.kind === 'case' ? I.arrowR : I.chevR} size={15} className="text-line-strong group-hover:text-faint" />
            </div>
            <div className="text-[14px] font-medium text-ink leading-snug line-clamp-2 group-hover:text-brand-ink transition-colors" style={{ minHeight: 38 }}>{it.label}</div>
            <div className="mt-2 flex items-center justify-between text-[12px] text-faint">
              <span>{it.sub}</span><span className="font-mono">{it.count}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

window.GraphPage = GraphPage;
