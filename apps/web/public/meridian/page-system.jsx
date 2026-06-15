// page-system.jsx — the design system reference / style tile
function Swatch({ name, tone, meaning }) {
  return (
    <div className="rounded-xl border border-line bg-surface overflow-hidden">
      <div className="h-16 flex items-stretch">
        <div className="flex-1" style={{ background: `var(--${tone})` }} />
        <div className="flex-1" style={{ background: `var(--${tone}-soft)` }} />
      </div>
      <div className="p-3">
        <div className="text-[13.5px] font-medium text-ink">{name}</div>
        <div className="text-[12px] text-muted mt-0.5" style={{ textWrap: 'pretty' }}>{meaning}</div>
        <div className="mt-2 font-mono text-[11px] text-faint">--{tone}</div>
      </div>
    </div>
  );
}

function Block({ title, desc, children }) {
  return (
    <section className="py-9 border-b border-line last:border-b-0">
      <div className="grid lg:grid-cols-[240px_1fr] gap-6">
        <div>
          <h2 className="text-[17px] font-semibold text-ink">{title}</h2>
          {desc && <p className="mt-1.5 text-[13.5px] text-muted max-w-xs" style={{ textWrap: 'pretty' }}>{desc}</p>}
        </div>
        <div>{children}</div>
      </div>
    </section>
  );
}

function SystemPage() {
  return (
    <div className="mx-auto max-w-content px-6 lg:px-8 py-10 anim-up">
      <PageHeader title="Design system"
        subtitle="The visual language behind Meridian — built for credibility and source-traceability. Tokens map directly to Tailwind utilities (text-ink, bg-brand, border-line)." />

      <Block title="Typography" desc="IBM Plex superfamily. Serif for case names & legal text, sans for the interface, mono for IDs and citations.">
        <div className="space-y-5">
          <div className="rounded-xl border border-line bg-surface p-5">
            <div className="text-[11px] uppercase tracking-[0.08em] text-faint mb-2 font-mono">Plex Serif · case names, headlines</div>
            <div className="font-serif text-ink" style={{ fontSize: 38, lineHeight: 1.1 }}>Broadcom / VMware</div>
          </div>
          <div className="rounded-xl border border-line bg-surface p-5">
            <div className="text-[11px] uppercase tracking-[0.08em] text-faint mb-2 font-mono">Plex Sans · interface</div>
            <div className="space-y-1.5">
              <div className="font-semibold text-ink text-[22px]">Product markets considered</div>
              <div className="text-ink text-[15px]">The Commission left the exact product market definition open but assessed on the narrowest plausible basis.</div>
              <div className="text-muted text-[13px]">Supporting / secondary text at 13px.</div>
            </div>
          </div>
          <div className="rounded-xl border border-line bg-surface p-5">
            <div className="text-[11px] uppercase tracking-[0.08em] text-faint mb-2 font-mono">Plex Mono · case IDs, citations</div>
            <div className="flex flex-wrap items-center gap-3 font-mono text-[14px] text-ink">
              <span>M.10806</span><span className="text-line-strong">·</span>
              <span>ME/6980/22</span><span className="text-line-strong">·</span>
              <span>p.24 ¶112</span>
            </div>
          </div>
        </div>
      </Block>

      <Block title="Colour" desc="A five-hue functional palette — each colour carries one consistent meaning across the product.">
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Swatch name="Navy — primary action" tone="brand" meaning="Links, buttons, the brand. Also: market segmentation." />
          <Swatch name="Green — positive / verified" tone="pos" meaning="Cleared, market defined, source-reviewed." />
          <Swatch name="Amber — caution" tone="ai" meaning="AI-generated, cleared-with-conditions, left open." />
          <Swatch name="Red — negative" tone="neg" meaning="Blocked / prohibited; theories of harm." />
          <Swatch name="Blue — informational" tone="seg" meaning="Segmented markets, neutral emphasis." />
          <Swatch name="Slate — neutral" tone="slatey" meaning="Indexed records, discussed, unknown." />
        </div>
      </Block>

      <Block title="Status badges" desc="Outcome and definition-status are the two badge families. Their style (soft / solid / outline) is set globally — try the Tweaks panel.">
        <div className="space-y-5">
          <div>
            <Eyebrow className="mb-2.5">Case outcome</Eyebrow>
            <div className="flex flex-wrap gap-2">
              <OutcomeBadge outcome="cleared" /><OutcomeBadge outcome="conditions" />
              <OutcomeBadge outcome="blocked" /><OutcomeBadge outcome="abandoned" />
            </div>
          </div>
          <div>
            <Eyebrow className="mb-2.5">Market definition status</Eyebrow>
            <div className="flex flex-wrap gap-2">
              <DefinitionBadge status="defined" /><DefinitionBadge status="left_open" />
              <DefinitionBadge status="segmented" /><DefinitionBadge status="discussed" />
            </div>
          </div>
        </div>
      </Block>

      <Block title="Chips & labels" desc="Source citations are the most important trust signal. Jurisdiction is a restrained text label, never a flag emoji.">
        <div className="space-y-5">
          <div>
            <Eyebrow className="mb-2.5">Source citation (clickable)</Eyebrow>
            <div className="flex flex-wrap gap-2">
              <SourceChip p={24} para={112} onClick={() => {}} />
              <SourceChip p={38} para={171} onClick={() => {}} />
              <SourceChip p={52} para={233} onClick={() => {}} />
            </div>
          </div>
          <div>
            <Eyebrow className="mb-2.5">Jurisdiction</Eyebrow>
            <div className="flex flex-wrap items-center gap-4">
              <Juris code="EU" withAuthority /><Juris code="UK" withAuthority /><Juris code="US" withAuthority />
            </div>
          </div>
          <div>
            <Eyebrow className="mb-2.5">Theory of harm</Eyebrow>
            <div className="flex flex-wrap gap-2">
              <TheoryTag>Input foreclosure</TheoryTag><TheoryTag>Conglomerate effects</TheoryTag><TheoryTag>Data advantage</TheoryTag>
            </div>
          </div>
        </div>
      </Block>

      <Block title="Cards" desc="Three list styles, switchable globally. Bordered reads as a document; filled groups; divided maximises density.">
        <div className="grid sm:grid-cols-3 gap-3">
          {[['bordered', 'bg-surface border border-line'], ['filled', 'bg-surface shadow-card border border-transparent'], ['divided', 'bg-transparent border-b border-line rounded-none']].map(([k, cls]) => (
            <div key={k} className={`rounded-xl p-4 ${cls}`}>
              <div className="text-[11px] uppercase tracking-[0.07em] text-faint font-mono mb-2">{k}</div>
              <div className="font-serif text-[17px] text-ink">Apple / Shazam</div>
              <div className="text-[12.5px] text-muted mt-1">European Union · 2018</div>
            </div>
          ))}
        </div>
      </Block>

      <Footer />
    </div>
  );
}

window.SystemPage = SystemPage;
