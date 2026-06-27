"use client";

import { useEffect, useRef, useState } from "react";
import type { CaseRecord, EntityCase, SectorMarket, SectorSummary, SimilarMarket } from "@/lib/types";
import { getCase, getGraphMarket, getGraphSectorMarkets, getGraphSectors, getGraphSimilarMarkets } from "@/features/cases/api";
import { CaseSidePanel } from "./CaseSidePanel";

// ─── Nav state ────────────────────────────────────────────────────────────────

type NavState =
  | { kind: "sectors" }
  | { kind: "sector_markets"; sector: string }
  | { kind: "market_detail"; marketName: string };

// ─── Colors ───────────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, { bg: string; border: string }> = {
  defined:    { bg: "#059669", border: "#047857" },
  left_open:  { bg: "#d97706", border: "#b45309" },
  discussed:  { bg: "#64748b", border: "#475569" },
  segmented:  { bg: "#3b82f6", border: "#2563eb" },
  considered: { bg: "#8b5cf6", border: "#7c3aed" },
};

const OUTCOME_COLORS: Record<string, string> = {
  cleared:                 "#059669",
  cleared_with_conditions: "#d97706",
  cleared_with_remedies:   "#d97706",
  blocked:                 "#dc2626",
  abandoned:               "#64748b",
  pending:                 "#64748b",
  unknown:                 "#64748b",
};

const SECTOR_BG = "#0369a1";
const SECTOR_BORDER = "#075985";
const MARKET_CENTER_BG = "#1e40af";
const MARKET_CENTER_BORDER = "#1e3a8a";

function statusStyle(status: string) {
  return STATUS_COLORS[status] ?? { bg: "#64748b", border: "#475569" };
}

function truncate(s: string, max = 24) {
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

function sectorSize(caseCount: number) {
  return Math.max(80, Math.min(160, 50 + caseCount * 18));
}

function marketSize(caseCount: number) {
  return Math.max(60, Math.min(130, 40 + caseCount * 14));
}

// ─── Component ────────────────────────────────────────────────────────────────

export function NavigationGraph() {
  const cyContainerRef = useRef<HTMLDivElement>(null);
  const cyRef          = useRef<import("cytoscape").Core | null>(null);

  // Navigation history
  const [history, setHistory]   = useState<NavState[]>([{ kind: "sectors" }]);
  const [histIdx, setHistIdx]   = useState(0);
  const current = history[histIdx];

  // Data caches
  const [sectors,           setSectors]           = useState<SectorSummary[]>([]);
  const [sectorMktsCache,   setSectorMktsCache]   = useState<Record<string, SectorMarket[]>>({});
  const [mktDetailCache,    setMktDetailCache]    = useState<Record<string, { cases: EntityCase[]; similar: SimilarMarket[] }>>({});

  // Loading / error
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  // Case side panel
  const [panelCaseId,  setPanelCaseId]  = useState<string | null>(null);
  const [panelCase,    setPanelCase]    = useState<CaseRecord | null>(null);
  const [panelLoading, setPanelLoading] = useState(false);

  // Stable callback refs so Cytoscape tap handlers never have stale closures
  const pushRef     = useRef<(s: NavState) => void>(() => {});
  const openCaseRef = useRef<(id: string) => void>(() => {});

  function push(state: NavState) {
    setHistory(prev => [...prev.slice(0, histIdx + 1), state]);
    setHistIdx(prev => prev + 1);
    closeCasePanel();
  }
  pushRef.current = push;

  function go(delta: number) {
    setHistIdx(prev => Math.max(0, Math.min(prev + delta, history.length - 1)));
    closeCasePanel();
  }

  function jumpTo(idx: number) {
    setHistIdx(idx);
    closeCasePanel();
  }

  function closeCasePanel() {
    setPanelCaseId(null);
    setPanelCase(null);
  }

  function openCasePanel(caseId: string) {
    setPanelCaseId(caseId);
    setPanelCase(null);
    setPanelLoading(true);
    getCase(caseId)
      .then(setPanelCase)
      .catch(() => setPanelCase(null))
      .finally(() => setPanelLoading(false));
  }
  openCaseRef.current = openCasePanel;

  // ─── Load sectors once ──────────────────────────────────────────────────────
  useEffect(() => {
    setLoading(true);
    getGraphSectors()
      .then(setSectors)
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  // ─── Load data when nav state changes ───────────────────────────────────────
  useEffect(() => {
    if (current.kind === "sectors") return;

    if (current.kind === "sector_markets") {
      const { sector } = current;
      if (sectorMktsCache[sector]) return;
      setLoading(true);
      getGraphSectorMarkets(sector)
        .then(data => setSectorMktsCache(prev => ({ ...prev, [sector]: data })))
        .catch(e => setError(String(e)))
        .finally(() => setLoading(false));
    }

    if (current.kind === "market_detail") {
      const { marketName } = current;
      if (mktDetailCache[marketName]) return;
      setLoading(true);
      Promise.all([
        getGraphMarket(marketName, false),
        getGraphSimilarMarkets(marketName),
      ])
        .then(([mkData, similar]) => {
          setMktDetailCache(prev => ({
            ...prev,
            [marketName]: { cases: mkData.cases, similar },
          }));
        })
        .catch(e => setError(String(e)))
        .finally(() => setLoading(false));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);

  // ─── Build Cytoscape graph ──────────────────────────────────────────────────
  useEffect(() => {
    if (!cyContainerRef.current) return;

    type CyElem = import("cytoscape").ElementDefinition;
    type CyLayout = import("cytoscape").LayoutOptions;

    let elements: CyElem[] = [];
    let layout: CyLayout   = { name: "cose" };
    let ready = false;

    if (current.kind === "sectors" && sectors.length) {
      elements = sectors.map(s => ({
        data: {
          id:         `sector:${s.sector}`,
          label:      truncate(s.sector, 22),
          fullLabel:  s.sector,
          kind:       "sector",
          size:       sectorSize(s.case_count),
          bg:         SECTOR_BG,
          border:     SECTOR_BORDER,
        },
      }));
      layout  = { name: "circle", fit: true, padding: 50 } as import("cytoscape").CircleLayoutOptions;
      ready   = true;
    }

    else if (current.kind === "sector_markets") {
      const markets = sectorMktsCache[current.sector];
      if (markets) {
        const sId = `sector:${current.sector}`;
        elements = [
          {
            data: {
              id: sId, label: truncate(current.sector, 22), fullLabel: current.sector,
              kind: "sector_center", size: 80, bg: SECTOR_BG, border: SECTOR_BORDER,
            },
          },
          ...markets.map(m => {
            const st = statusStyle(m.dominant_status);
            return {
              data: {
                id:        `market:${m.market_name}`,
                label:     truncate(m.market_name),
                fullLabel: m.market_name,
                kind:      "market",
                size:      marketSize(m.case_count),
                bg:        st.bg,
                border:    st.border,
              },
            };
          }),
          ...markets.map(m => ({
            data: {
              id:     `e:${sId}->market:${m.market_name}`,
              source: sId,
              target: `market:${m.market_name}`,
            },
          })),
        ];
        layout = {
          name:          "breadthfirst",
          roots:         [sId],
          fit:           true,
          padding:       50,
          spacingFactor: 1.6,
          directed:      false,
        } as import("cytoscape").BreadthFirstLayoutOptions;
        ready = true;
      }
    }

    else if (current.kind === "market_detail") {
      const detail = mktDetailCache[current.marketName];
      if (detail) {
        const mId = `market_center:${current.marketName}`;
        elements = [
          {
            data: {
              id: mId, label: truncate(current.marketName), fullLabel: current.marketName,
              kind: "market_center", size: 110, bg: MARKET_CENTER_BG, border: MARKET_CENTER_BORDER,
            },
          },
          ...detail.cases.map(c => ({
            data: {
              id:       `case:${c.case_id}`,
              label:    truncate(c.case_name, 20),
              fullLabel: c.case_name,
              kind:     "case",
              caseId:   c.case_id,
              outcome:  c.outcome,
              defStatus: c.definition_status,
              size:     76,
              bg:       OUTCOME_COLORS[c.outcome] ?? "#64748b",
              border:   OUTCOME_COLORS[c.outcome] ?? "#64748b",
            },
          })),
          ...detail.similar.map(s => {
            const st = statusStyle(s.dominant_status);
            return {
              data: {
                id:        `sim_market:${s.market_name}`,
                label:     truncate(s.market_name),
                fullLabel: s.market_name,
                kind:      "similar_market",
                size:      marketSize(s.case_count),
                bg:        st.bg,
                border:    st.border,
              },
            };
          }),
          ...detail.cases.map(c => ({
            data: {
              id:     `e:${mId}->case:${c.case_id}`,
              source: mId,
              target: `case:${c.case_id}`,
              edgeLabel: c.definition_status?.replace(/_/g, " ") ?? "",
            },
          })),
          ...detail.similar.map(s => ({
            data: {
              id:     `e:${mId}->sim:${s.market_name}`,
              source: mId,
              target: `sim_market:${s.market_name}`,
            },
          })),
        ];
        layout = {
          name:           "cose",
          animate:        false,
          nodeRepulsion:  () => 14000,
          idealEdgeLength: () => 130,
          fit:            true,
          padding:        50,
          randomize:      true,
        } as import("cytoscape").CoseLayoutOptions;
        ready = true;
      }
    }

    if (!ready) return;

    import("cytoscape").then(({ default: Cytoscape }) => {
      if (!cyContainerRef.current) return;
      cyRef.current?.destroy();
      cyRef.current = null;

      const cy = Cytoscape({
        container: cyContainerRef.current,
        elements,
        style: [
          {
            selector: "node",
            style: {
              "background-color": "data(bg)",
              "border-color":     "data(border)",
              "border-width":     2,
              label:              "data(label)",
              color:              "#ffffff",
              "text-valign":      "center",
              "text-halign":      "center",
              "font-size":        "9px",
              "font-family":      "ui-sans-serif, system-ui, sans-serif",
              width:              "data(size)",
              height:             "data(size)",
              shape:              "ellipse",
              "text-wrap":        "wrap",
              "text-max-width":   "data(size)",
              padding:            "6px",
            },
          },
          {
            selector: 'node[kind = "market_center"]',
            style: {
              shape:         "round-rectangle",
              "font-size":   "11px",
              "font-weight": "bold",
              "border-width": 4,
            },
          },
          {
            selector: 'node[kind = "case"]',
            style: { shape: "round-rectangle" },
          },
          {
            selector: "node:selected",
            style: { "border-width": 4, "border-color": "#f59e0b" },
          },
          {
            selector: "edge",
            style: {
              width:                 1,
              "line-color":          "#cbd5e1",
              "target-arrow-color":  "#cbd5e1",
              "target-arrow-shape":  "triangle",
              "curve-style":         "bezier",
              "font-size":           "7px",
              label:                 "data(edgeLabel)",
              color:                 "#94a3b8",
              "text-rotation":       "autorotate",
              "text-background-color": "#f8fafc",
              "text-background-opacity": 0.8,
              "text-background-padding": "1px",
            },
          },
        ],
        layout: { name: "preset" },
      });

      cyRef.current = cy;
      cy.layout(layout).run();

      cy.on("tap", "node", (evt) => {
        const kind:      string = evt.target.data("kind");
        const fullLabel: string = evt.target.data("fullLabel");
        const caseId:    string = evt.target.data("caseId");

        if (kind === "sector" || kind === "sector_center") {
          pushRef.current({ kind: "sector_markets", sector: fullLabel });
        } else if (kind === "market" || kind === "similar_market") {
          pushRef.current({ kind: "market_detail", marketName: fullLabel });
        } else if (kind === "case") {
          openCaseRef.current(caseId);
        }
      });
    });

    return () => {
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, sectors, sectorMktsCache, mktDetailCache]);

  // ─── Breadcrumb helpers ─────────────────────────────────────────────────────
  function stateLabel(s: NavState): string {
    if (s.kind === "sectors")        return "Sectors";
    if (s.kind === "sector_markets") return s.sector;
    return s.marketName;
  }

  const canBack    = histIdx > 0;
  const canForward = histIdx < history.length - 1;

  // ─── Legend per view ────────────────────────────────────────────────────────
  const statusLegend = [
    { color: STATUS_COLORS.defined.bg,    label: "defined" },
    { color: STATUS_COLORS.left_open.bg,  label: "left open" },
    { color: STATUS_COLORS.segmented.bg,  label: "segmented" },
    { color: STATUS_COLORS.discussed.bg,  label: "discussed" },
  ];

  const caseLegend = [
    { color: OUTCOME_COLORS.cleared,                 label: "cleared" },
    { color: OUTCOME_COLORS.cleared_with_conditions, label: "cleared w/ conditions" },
    { color: OUTCOME_COLORS.blocked,                 label: "blocked" },
    { color: "#64748b",                              label: "other" },
  ];

  return (
    <div className="flex flex-col gap-3">

      {/* ── Navigation bar ──────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => go(-1)}
          disabled={!canBack}
          className="p-1.5 rounded border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-30 disabled:cursor-not-allowed text-sm leading-none"
          aria-label="Back"
        >
          ←
        </button>
        <button
          onClick={() => go(1)}
          disabled={!canForward}
          className="p-1.5 rounded border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-30 disabled:cursor-not-allowed text-sm leading-none"
          aria-label="Forward"
        >
          →
        </button>

        {/* Breadcrumb */}
        <nav className="flex items-center gap-1 text-xs text-slate-500 flex-wrap">
          {history.slice(0, histIdx + 1).map((state, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span className="text-slate-300 select-none">›</span>}
              <button
                onClick={() => jumpTo(i)}
                className={
                  i === histIdx
                    ? "font-semibold text-slate-800 cursor-default"
                    : "hover:text-slate-700 max-w-[120px] truncate text-left"
                }
                disabled={i === histIdx}
                title={stateLabel(state)}
              >
                {truncate(stateLabel(state), 22)}
              </button>
            </span>
          ))}
        </nav>
      </div>

      {/* ── Legend ──────────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {current.kind === "sectors" && (
          <span className="text-slate-500">Click a sector to explore its markets · Node size = case count</span>
        )}
        {current.kind === "sector_markets" && (
          <>
            <span className="text-slate-500">Click a market to see cases and related markets</span>
            {statusLegend.map(l => (
              <span key={l.label} className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full inline-block shrink-0" style={{ background: l.color }} />
                <span className="text-slate-600">{l.label}</span>
              </span>
            ))}
          </>
        )}
        {current.kind === "market_detail" && (
          <>
            <span className="text-slate-500">
              <span className="inline-block w-2.5 h-2.5 rounded inline-block mr-1" style={{ background: MARKET_CENTER_BG }} />
              selected market
            </span>
            {caseLegend.map(l => (
              <span key={l.label} className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded inline-block shrink-0" style={{ background: l.color }} />
                <span className="text-slate-600">{l.label}</span>
              </span>
            ))}
            {statusLegend.map(l => (
              <span key={l.label} className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full inline-block shrink-0" style={{ background: l.color }} />
                <span className="text-slate-600">related: {l.label}</span>
              </span>
            ))}
            <span className="text-slate-400">Click a case for details · Click a related market to explore it</span>
          </>
        )}
      </div>

      {/* ── Canvas + case panel ──────────────────────────────────────────────── */}
      <div
        className="flex border border-slate-200 rounded-xl overflow-hidden bg-slate-50"
        style={{ minHeight: 520 }}
      >
        <div className="relative flex-1">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center z-10 bg-slate-50/80">
              <span className="text-sm text-slate-400 animate-pulse">Loading…</span>
            </div>
          )}
          {error && !loading && (
            <div className="absolute inset-0 flex items-center justify-center z-10">
              <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm max-w-xs">
                {error}
              </div>
            </div>
          )}
          <div ref={cyContainerRef} className="w-full h-full" style={{ minHeight: 520 }} />
        </div>

        {panelCaseId && (
          <CaseSidePanel
            caseId={panelCaseId}
            caseRecord={panelCase}
            loading={panelLoading}
            onClose={closeCasePanel}
          />
        )}
      </div>

      {/* ── Footer stats ─────────────────────────────────────────────────────── */}
      <p className="text-xs text-slate-400">
        {current.kind === "sectors" && `${sectors.length} sector${sectors.length !== 1 ? "s" : ""}`}
        {current.kind === "sector_markets" && (() => {
          const ms = sectorMktsCache[current.sector];
          return ms ? `${ms.length} market${ms.length !== 1 ? "s" : ""} in ${current.sector}` : "";
        })()}
        {current.kind === "market_detail" && (() => {
          const d = mktDetailCache[current.marketName];
          return d
            ? `${d.cases.length} case${d.cases.length !== 1 ? "s" : ""} · ${d.similar.length} related market${d.similar.length !== 1 ? "s" : ""}`
            : "";
        })()}
      </p>
    </div>
  );
}
