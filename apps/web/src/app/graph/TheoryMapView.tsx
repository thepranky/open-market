"use client";

import { useEffect, useRef, useState } from "react";
import { getGraphTheories, getGraphTheory } from "@/lib/api";
import type { EntityCase, TheorySummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { EntityDetailPanel } from "./EntityDetailPanel";

const OUTCOME_COLORS: Record<string, string> = {
  blocked: "#dc2626",
  cleared_with_conditions: "#d97706",
  cleared_with_remedies: "#d97706",
  cleared: "#059669",
  abandoned: "#94a3b8",
  referred: "#3b82f6",
  pending: "#94a3b8",
};

const ALL_SECTORS = ["digital", "pharma", "airlines", "energy", "telecoms", "retail", "AI"];

function nodeSize(count: number): number {
  return Math.min(40 + count * 14, 130);
}

function truncate(s: string, max = 24) {
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

function dominantOutcome(breakdown: Record<string, number>): string {
  if (!breakdown || Object.keys(breakdown).length === 0) return "pending";
  return Object.entries(breakdown).sort(([, a], [, b]) => b - a)[0][0];
}

export function TheoryMapView() {
  const cyContainerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<import("cytoscape").Core | null>(null);

  const [theories, setTheories] = useState<TheorySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [activeSector, setActiveSector] = useState<string | null>(null);
  const [selectedTheory, setSelectedTheory] = useState<TheorySummary | null>(null);
  const [entityCases, setEntityCases] = useState<EntityCase[]>([]);
  const [panelLoading, setPanelLoading] = useState(false);
  const [expandLoading, setExpandLoading] = useState(false);

  useEffect(() => {
    getGraphTheories()
      .then((data) => {
        setTheories(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(String(err));
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (!theories.length || !cyContainerRef.current) return;

    const visible = activeSector
      ? theories.filter((t) => t.sectors.includes(activeSector))
      : theories;

    import("cytoscape").then(({ default: Cytoscape }) => {
      cyRef.current?.destroy();
      cyRef.current = null;

      if (!cyContainerRef.current) return;

      const elements = visible.map((t) => {
        const dom = dominantOutcome(t.outcome_breakdown);
        const color = OUTCOME_COLORS[dom] ?? "#94a3b8";
        const size = nodeSize(t.case_count);
        return {
          data: {
            id: `theory:${t.theory_name}`,
            label: truncate(t.theory_name),
            fullLabel: t.theory_name,
            caseCount: t.case_count,
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
        ],
        layout: {
          name: "cose",
          animate: false,
          nodeRepulsion: () => 14000,
          idealEdgeLength: () => 80,
          fit: true,
          padding: 30,
          randomize: true,
        } as import("cytoscape").CoseLayoutOptions,
      });

      cyRef.current = cy;

      cy.on("tap", "node", async (evt) => {
        const name: string = evt.target.data("fullLabel");
        const theory = theories.find((t) => t.theory_name === name);
        if (!theory) return;

        setSelectedTheory(theory);
        setEntityCases([]);
        setPanelLoading(true);
        try {
          const data = await getGraphTheory(name, false);
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
  }, [theories, activeSector]);

  function handleExpand() {
    if (!cyRef.current || !selectedTheory || entityCases.length === 0) return;
    setExpandLoading(true);
    const cy = cyRef.current;
    const theoryNodeId = `theory:${selectedTheory.theory_name}`;

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
              id: `${theoryNodeId}->${caseNodeId}`,
              source: theoryNodeId,
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
        Loading theory map…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg bg-red-50 border border-red-200 p-4 text-red-700 text-sm">
        Failed to load theories: {error}
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

      {/* Outcome legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {Object.entries(OUTCOME_COLORS).map(([outcome, color]) => (
          <span key={outcome} className="flex items-center gap-1.5">
            <span
              className="inline-block w-3 h-3 rounded-full shrink-0"
              style={{ background: color }}
            />
            <span className="text-slate-600">{outcome.replace(/_/g, " ")}</span>
          </span>
        ))}
        <span className="text-slate-400 ml-2">Node color = most common outcome · size = case frequency</span>
      </div>

      {/* Canvas + panel */}
      <div className="flex border border-slate-200 rounded-xl overflow-hidden bg-slate-50">
        <div
          ref={cyContainerRef}
          className="flex-1"
          style={{ height: 520 }}
        />
        {selectedTheory && (
          <EntityDetailPanel
            title={selectedTheory.theory_name}
            subtitle={
              panelLoading
                ? "Loading cases…"
                : `${entityCases.length} case${entityCases.length !== 1 ? "s" : ""} applied this theory`
            }
            statusBreakdown={selectedTheory.outcome_breakdown}
            entityType="theory"
            cases={entityCases}
            onExpand={handleExpand}
            expandLoading={expandLoading}
            expandLabel="Expand cases in graph"
            onClose={() => {
              setSelectedTheory(null);
              setEntityCases([]);
            }}
          />
        )}
      </div>

      <p className="text-xs text-slate-400">
        {activeSector
          ? `Showing theories in ${activeSector} sector · `
          : `${theories.length} unique theories of harm · `}
        Click a theory node to see which cases raised it.
      </p>
    </div>
  );
}
