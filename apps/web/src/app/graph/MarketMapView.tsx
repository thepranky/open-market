"use client";

import { useEffect, useRef, useState } from "react";
import { getGraphMarket, getGraphMarkets } from "@/lib/api";
import type { EntityCase, MarketSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { EntityDetailPanel } from "./EntityDetailPanel";

const STATUS_COLORS: Record<string, string> = {
  defined: "#059669",
  left_open: "#d97706",
  discussed: "#94a3b8",
  segmented: "#3b82f6",
  considered: "#8b5cf6",
};

const ALL_SECTORS = ["digital", "pharma", "airlines", "energy", "telecoms", "retail", "AI"];

function nodeSize(count: number): number {
  return Math.min(40 + count * 12, 120);
}

function truncate(s: string, max = 22) {
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

export function MarketMapView() {
  const cyContainerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<import("cytoscape").Core | null>(null);

  const [markets, setMarkets] = useState<MarketSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [activeSector, setActiveSector] = useState<string | null>(null);
  const [selectedMarket, setSelectedMarket] = useState<MarketSummary | null>(null);
  const [entityCases, setEntityCases] = useState<EntityCase[]>([]);
  const [panelLoading, setPanelLoading] = useState(false);
  const [expandLoading, setExpandLoading] = useState(false);

  // Load all markets on mount
  useEffect(() => {
    getGraphMarkets()
      .then((data) => {
        setMarkets(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(String(err));
        setLoading(false);
      });
  }, []);

  // Build/rebuild the Cytoscape graph when markets or active sector changes
  useEffect(() => {
    if (!markets.length || !cyContainerRef.current) return;

    const visibleMarkets = activeSector
      ? markets.filter((m) => m.sectors.includes(activeSector))
      : markets;

    import("cytoscape").then(({ default: Cytoscape }) => {
      cyRef.current?.destroy();
      cyRef.current = null;

      if (!cyContainerRef.current) return;

      const elements = visibleMarkets.map((m) => {
        const size = nodeSize(m.case_count);
        const color = STATUS_COLORS[m.dominant_status] ?? STATUS_COLORS.discussed;
        return {
          data: {
            id: `market:${m.market_name}`,
            label: truncate(m.market_name),
            fullLabel: m.market_name,
            caseCount: m.case_count,
            dominantStatus: m.dominant_status,
            sectors: m.sectors,
            color,
            size,
          },
        };
      });

      const cy = Cytoscape({
        container: cyContainerRef.current,
        elements,
        style: [
          {
            selector: "node",
            style: {
              "background-color": "data(color)",
              "border-color": "data(color)",
              "border-width": 2,
              label: "data(label)",
              color: "#ffffff",
              "text-valign": "center",
              "text-halign": "center",
              "font-size": "9px",
              "font-family": "ui-sans-serif, system-ui, sans-serif",
              width: "data(size)",
              height: "data(size)",
              shape: "ellipse",
              "text-wrap": "wrap",
              "text-max-width": "data(size)",
              padding: "4px",
            },
          },
          {
            selector: "node:selected",
            style: { "border-width": 4, "border-color": "#f59e0b" },
          },
          {
            selector: "node.dimmed",
            style: { opacity: 0.25 },
          },
        ],
        layout: {
          name: "cose",
          animate: false,
          nodeRepulsion: () => 12000,
          idealEdgeLength: () => 80,
          fit: true,
          padding: 30,
          randomize: true,
        } as import("cytoscape").CoseLayoutOptions,
      });

      cyRef.current = cy;

      cy.on("tap", "node", async (evt) => {
        const name: string = evt.target.data("fullLabel");
        const market = markets.find(
          (m) => m.market_name === name
        );
        if (!market) return;

        setSelectedMarket(market);
        setEntityCases([]);
        setPanelLoading(true);
        try {
          const data = await getGraphMarket(name, false);
          setEntityCases(data.cases);
        } catch {
          setEntityCases([]);
        } finally {
          setPanelLoading(false);
        }
      });
    });

    return () => {
      cyRef.current?.destroy();
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markets, activeSector]);

  function handleExpand() {
    if (!cyRef.current || !selectedMarket || entityCases.length === 0) return;
    setExpandLoading(true);
    const cy = cyRef.current;
    const marketNodeId = `market:${selectedMarket.market_name}`;

    entityCases.forEach((ec) => {
      const caseNodeId = `case:${ec.case_id}`;
      if (!cy.getElementById(caseNodeId).length) {
        cy.add([
          {
            data: {
              id: caseNodeId,
              label: truncate(ec.case_name),
              fullLabel: ec.case_name,
              color: "#1d4ed8",
              size: 48,
            },
          },
          {
            data: {
              id: `${marketNodeId}->${caseNodeId}`,
              source: marketNodeId,
              target: caseNodeId,
            },
          },
        ]);
      }
    });

    cy.layout({
      name: "cose",
      animate: true,
      animationDuration: 600,
      fit: true,
      padding: 30,
      nodeRepulsion: () => 10000,
    } as import("cytoscape").CoseLayoutOptions).run();

    setExpandLoading(false);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400 text-sm animate-pulse">
        Loading market map…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg bg-red-50 border border-red-200 p-4 text-red-700 text-sm">
        Failed to load markets: {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Sector filter chips */}
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-xs text-slate-500 font-medium">Sector:</span>
        <button
          onClick={() => setActiveSector(null)}
          className={cn(
            "text-xs px-3 py-1 rounded-full border transition-colors",
            activeSector === null
              ? "bg-slate-800 text-white border-slate-800"
              : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
          )}
        >
          All
        </button>
        {ALL_SECTORS.map((s) => (
          <button
            key={s}
            onClick={() => setActiveSector(activeSector === s ? null : s)}
            className={cn(
              "text-xs px-3 py-1 rounded-full border transition-colors capitalize",
              activeSector === s
                ? "bg-slate-800 text-white border-slate-800"
                : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
            )}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Status legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {Object.entries(STATUS_COLORS).map(([status, color]) => (
          <span key={status} className="flex items-center gap-1.5">
            <span
              className="inline-block w-3 h-3 rounded-full shrink-0"
              style={{ background: color }}
            />
            <span className="text-slate-600 capitalize">{status.replace(/_/g, " ")}</span>
          </span>
        ))}
        <span className="text-slate-400 ml-2">Node size = case frequency</span>
      </div>

      {/* Canvas + panel */}
      <div className="flex border border-slate-200 rounded-xl overflow-hidden bg-slate-50">
        <div
          ref={cyContainerRef}
          className="flex-1"
          style={{ height: 520 }}
        />
        {selectedMarket && (
          <EntityDetailPanel
            title={selectedMarket.market_name}
            subtitle={
              panelLoading
                ? "Loading cases…"
                : `${entityCases.length} case${entityCases.length !== 1 ? "s" : ""} considered this market`
            }
            statusBreakdown={selectedMarket.definition_status_breakdown}
            entityType="market"
            cases={entityCases}
            onExpand={handleExpand}
            expandLoading={expandLoading}
            expandLabel="Expand cases in graph"
            onClose={() => {
              setSelectedMarket(null);
              setEntityCases([]);
            }}
          />
        )}
      </div>

      <p className="text-xs text-slate-400">
        {activeSector
          ? `Showing markets in ${activeSector} sector · `
          : `${markets.length} unique product markets · `}
        Click a market node to see which cases considered it.
      </p>
    </div>
  );
}
