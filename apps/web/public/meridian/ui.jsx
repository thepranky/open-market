// ui.jsx — Meridian design-system atoms + shared UI context
const { useState, useEffect, useRef, useContext, createContext, useMemo } = React;

// ------------------------------------------------------------------ context
// Provides tweak values (cardStyle, badgeStyle, …), navigation + active route.
const UIContext = createContext({ t: {}, navigate: () => {}, route: { page: 'home' } });
const useUI = () => useContext(UIContext);

// ------------------------------------------------------------------ icons
const I = {
  arrowR: 'M4 10h12M11 5l5 5-5 5',
  arrowL: 'M16 10H4M9 5l-5 5 5 5',
  chevR: 'M7 4l6 6-6 6',
  chevD: 'M4 7l6 6 6-6',
  ext: 'M7 13L13 7M8 7h5v5',
  check: 'M4 10.5l4 4 8-9',
  search: 'M9 16a7 7 0 100-14 7 7 0 000 14zm6 2l-3.5-3.5',
  sun: 'M10 3v2M10 15v2M3 10h2M15 10h2M5 5l1.5 1.5M13.5 13.5L15 15M15 5l-1.5 1.5M6.5 13.5L5 15',
  moon: 'M16 11.5A6.5 6.5 0 018.5 4 6.5 6.5 0 1016 11.5z',
  graph: 'M10 3v4M10 13v4M5.5 6.5L8 9M12 11l2.5 2.5M5 14a2 2 0 100-4 2 2 0 000 4zm10 0a2 2 0 100-4 2 2 0 000 4zM10 11a2 2 0 100-4 2 2 0 000 4z',
  layers: 'M10 3l7 4-7 4-7-4 7-4zM3 11l7 4 7-4M3 14l7 4 7-4',
  doc: 'M6 3h5l4 4v10H6V3zM11 3v4h4',
  link: 'M8 12a3 3 0 004 0l2-2a3 3 0 00-4-4M12 8a3 3 0 00-4 0l-2 2a3 3 0 004 4',
  x: 'M5 5l10 10M15 5L5 15',
  plus: 'M10 4v12M4 10h12',
  reset: 'M5 9a5 5 0 119 3M5 9V5M5 9h4',
  filter: 'M4 5h12M6 10h8M9 15h2',
  spark: 'M10 3l1.6 4.4L16 9l-4.4 1.6L10 15l-1.6-4.4L4 9l4.4-1.6L10 3z',
};
function Icon({ d, size = 18, sw = 1.6, className = '', style }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none"
      stroke="currentColor" strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"
      className={className} style={style} aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

// ------------------------------------------------------------------ wordmark
function Logo({ onClick, size = 'md' }) {
  const big = size === 'lg';
  return (
    <button onClick={onClick} className="focus-ring flex items-center gap-2.5 group rounded-sm">
      <span className="relative inline-flex items-center justify-center" style={{ width: big ? 26 : 20, height: big ? 26 : 20 }}>
        <span className="absolute inset-0 rounded-full border-2 border-brand" />
        <span className="absolute bg-brand" style={{ width: 2, height: big ? 26 : 20 }} />
        <span className="absolute bg-brand rounded-full" style={{ width: big ? 7 : 5.5, height: big ? 7 : 5.5 }} />
      </span>
      <span className="font-serif font-medium tracking-tight text-ink"
        style={{ fontSize: big ? 24 : 19, letterSpacing: '-0.01em' }}>Meridian</span>
    </button>
  );
}

// ------------------------------------------------------------------ badges
const TONE = {
  brand: { soft: 'bg-brand-soft text-brand-ink', solid: 'bg-brand text-brand-fg', outline: 'border border-brand text-brand-ink bg-transparent' },
  pos: { soft: 'bg-pos-soft text-pos-ink', solid: 'bg-pos text-white dark:text-[#08121E]', outline: 'border border-pos text-pos-ink bg-transparent' },
  ai: { soft: 'bg-ai-soft text-ai-ink', solid: 'bg-ai text-white dark:text-[#08121E]', outline: 'border border-ai text-ai-ink bg-transparent' },
  neg: { soft: 'bg-neg-soft text-neg-ink', solid: 'bg-neg text-white dark:text-[#08121E]', outline: 'border border-neg text-neg-ink bg-transparent' },
  seg: { soft: 'bg-seg-soft text-seg-ink', solid: 'bg-seg text-white dark:text-[#08121E]', outline: 'border border-seg text-seg-ink bg-transparent' },
  slatey: { soft: 'bg-slatey-soft text-slatey-ink', solid: 'bg-slatey text-white dark:text-[#08121E]', outline: 'border border-slatey text-slatey-ink bg-transparent' },
};

function Badge({ tone = 'slatey', children, dot = false, className = '', styleOverride }) {
  const { t } = useUI();
  const style = styleOverride || t.badgeStyle || 'soft';
  const cls = (TONE[tone] || TONE.slatey)[style];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-[5px] px-2 py-[3px] text-[12px] font-medium leading-none whitespace-nowrap ${cls} ${className}`}>
      {dot && <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: 'currentColor' }} />}
      {children}
    </span>
  );
}

const OUTCOME_TONE = { cleared: 'pos', conditions: 'ai', blocked: 'neg', abandoned: 'slatey' };
const OUTCOME_LABEL = { cleared: 'Cleared', conditions: 'Cleared w/ conditions', blocked: 'Blocked', abandoned: 'Abandoned' };
function OutcomeBadge({ outcome, ...rest }) {
  return <Badge tone={OUTCOME_TONE[outcome] || 'slatey'} dot {...rest}>{OUTCOME_LABEL[outcome] || outcome}</Badge>;
}

const DEFN_TONE = { defined: 'pos', left_open: 'ai', segmented: 'seg', discussed: 'slatey' };
const DEFN_LABEL = { defined: 'Defined', left_open: 'Left open', segmented: 'Segmented', discussed: 'Discussed' };
function DefinitionBadge({ status, ...rest }) {
  return <Badge tone={DEFN_TONE[status] || 'slatey'} {...rest}>{DEFN_LABEL[status] || status}</Badge>;
}

// ------------------------------------------------------------------ jurisdiction
const JLABEL = window.MERIDIAN_DATA.JURIS;
function Juris({ code, withAuthority = false, className = '' }) {
  const j = JLABEL[code] || { code, authority: '' };
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <span className="font-mono text-[11px] font-semibold tracking-[0.08em] text-ink/80 border border-line-strong rounded-[4px] px-1.5 py-[2px] leading-none">{j.code}</span>
      {withAuthority && <span className="text-[13px] text-muted">{j.authority}</span>}
    </span>
  );
}

// ------------------------------------------------------------------ source chip
function SourceChip({ p, para, onClick }) {
  return (
    <button onClick={onClick}
      title={`Open source — page ${p}, paragraph ${para}`}
      className="focus-ring group inline-flex items-center gap-1 rounded-[4px] border border-brand/25 bg-brand-soft px-1.5 py-[2px] font-mono text-[11px] font-medium text-brand-ink leading-none hover:border-brand/60 transition-colors">
      <span>p.{p}</span>
      <span className="text-brand-ink/55">¶{para}</span>
      <Icon d={I.arrowR} size={11} sw={2} className="opacity-0 -ml-1 group-hover:opacity-100 group-hover:ml-0 transition-all" />
    </button>
  );
}

// ------------------------------------------------------------------ buttons
function Button({ children, variant = 'primary', size = 'md', icon, iconR, onClick, className = '', type = 'button' }) {
  const sizes = { sm: 'text-[13px] px-3 py-1.5 gap-1.5', md: 'text-[14px] px-4 py-2 gap-2', lg: 'text-[15px] px-5 py-2.5 gap-2' };
  const variants = {
    primary: 'bg-brand text-brand-fg hover:bg-brand-hover shadow-sm',
    secondary: 'bg-surface text-ink border border-line-strong hover:border-faint hover:bg-canvas/60',
    ghost: 'text-muted hover:text-ink hover:bg-slatey-soft',
    quiet: 'bg-slatey-soft text-ink hover:bg-line',
  };
  return (
    <button type={type} onClick={onClick}
      className={`focus-ring inline-flex items-center justify-center whitespace-nowrap font-medium rounded-[7px] transition-colors ${sizes[size]} ${variants[variant]} ${className}`}>
      {icon && <Icon d={icon} size={16} />}
      {children}
      {iconR && <Icon d={iconR} size={16} />}
    </button>
  );
}

// ------------------------------------------------------------------ segmented control
function Segmented({ options, value, onChange, size = 'md' }) {
  const pad = size === 'sm' ? 'text-[12.5px] py-1.5' : 'text-[13.5px] py-2';
  return (
    <div className="inline-grid rounded-[8px] bg-canvas border border-line p-[3px]"
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0,1fr))` }}>
      {options.map((o) => {
        const v = typeof o === 'string' ? o : o.value;
        const lbl = typeof o === 'string' ? o : o.label;
        const active = v === value;
        return (
          <button key={v} onClick={() => onChange(v)}
            className={`focus-ring rounded-[6px] px-3 font-medium transition-all ${pad} ${active ? 'bg-surface text-ink shadow-sm' : 'text-muted hover:text-ink'}`}>
            {lbl}
          </button>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ panel / surface
function Panel({ children, className = '', pad = true }) {
  return <div className={`bg-surface border border-line rounded-xl ${pad ? 'p-5' : ''} ${className}`}>{children}</div>;
}

// labelled field group (AUTHORITY / DECISION DATE …)
function Field({ label, children, className = '' }) {
  return (
    <div className={className}>
      <div className="text-[11px] font-semibold uppercase tracking-[0.07em] text-faint mb-1">{label}</div>
      <div className="text-[15px] text-ink">{children}</div>
    </div>
  );
}

// small uppercase section eyebrow
function Eyebrow({ children, className = '' }) {
  return <div className={`text-[11px] font-semibold uppercase tracking-[0.09em] text-faint ${className}`}>{children}</div>;
}

// big stat
function Stat({ value, label, suffix }) {
  return (
    <div>
      <div className="font-serif text-ink leading-none" style={{ fontSize: 'clamp(28px, 3.4vw, 40px)' }}>
        {value}{suffix && <span className="text-brand">{suffix}</span>}
      </div>
      <div className="mt-2 text-[13px] text-muted">{label}</div>
    </div>
  );
}

// section heading used across pages
function PageHeader({ title, subtitle, children }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 mb-7">
      <div>
        <h1 className="font-sans font-semibold tracking-tight text-ink" style={{ fontSize: 'clamp(26px, 3vw, 34px)' }}>{title}</h1>
        {subtitle && <p className="mt-2 text-[15px] text-muted max-w-2xl" style={{ textWrap: 'pretty' }}>{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

// ------------------------------------------------------------------ top nav
function NavBar() {
  const { navigate, route } = useUI();
  const links = [
    { key: 'explore', label: 'Explore' },
    { key: 'graph', label: 'Graph' },
    { key: 'system', label: 'Design system' },
  ];
  return (
    <header className="sticky top-0 z-30 bg-surface/85 backdrop-blur-md border-b border-line">
      <div className="mx-auto max-w-content px-6 lg:px-8 h-[58px] flex items-center justify-between">
        <Logo onClick={() => navigate({ page: 'home' })} />
        <nav className="flex items-center gap-1">
          {links.map((l) => {
            const active = route.page === l.key || (l.key === 'explore' && route.page === 'case');
            return (
              <button key={l.key} onClick={() => navigate({ page: l.key })}
                className={`focus-ring rounded-[7px] px-3 py-1.5 text-[14px] font-medium whitespace-nowrap transition-colors ${active ? 'text-ink bg-slatey-soft' : 'text-muted hover:text-ink hover:bg-slatey-soft/60'}`}>
                {l.label}
              </button>
            );
          })}
          <div className="w-px h-5 bg-line mx-2" />
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}

function ThemeToggle() {
  const { t, navigate } = useUI();
  // theme is a tweak; expose a quick toggle in the nav for convenience
  const dark = t.theme === 'dark';
  return (
    <button onClick={() => window.__meridianSetTheme && window.__meridianSetTheme(dark ? 'light' : 'dark')}
      title={dark ? 'Switch to light' : 'Switch to dark'}
      className="focus-ring rounded-[7px] p-2 text-muted hover:text-ink hover:bg-slatey-soft transition-colors">
      <Icon d={dark ? I.sun : I.moon} size={17} />
    </button>
  );
}

// theory-of-harm tag (subtle, outline-ish regardless of badge style)
function TheoryTag({ children }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-[6px] border border-line bg-canvas px-2.5 py-1 text-[12.5px] text-muted max-w-[280px]">
      <span className="w-1 h-1 rounded-full bg-faint shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  );
}

// reusable footer
function Footer() {
  return (
    <footer className="mt-20 border-t border-line">
      <div className="mx-auto max-w-content px-6 lg:px-8 py-8 flex flex-wrap items-center justify-between gap-4 text-[13px] text-faint">
        <div className="flex items-center gap-2">
          <span className="font-serif text-muted">Meridian</span>
          <span>·</span>
          <span>Market-definition research</span>
        </div>
        <div className="flex items-center gap-5">
          <span>EU · UK · US precedent</span>
          <span className="font-mono text-[12px]">v2.0</span>
        </div>
      </div>
    </footer>
  );
}

Object.assign(window, {
  UIContext, useUI, Icon, I, Logo, Badge, OutcomeBadge, DefinitionBadge,
  Juris, SourceChip, Button, Segmented, Panel, Field, Eyebrow, Stat,
  PageHeader, NavBar, ThemeToggle, TheoryTag, Footer,
  OUTCOME_LABEL, DEFN_LABEL,
});
