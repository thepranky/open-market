"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { EntityCase, GraphNeighborhoodResponse, GraphNode } from "@/lib/types";
import { getGraphMarket, getGraphTheory } from "@/features/cases/api";
import { cn } from "@/lib/utils";
import { EntityDetailPanel } from "./EntityDetailPanel";
import { MarketMapView } from "./MarketMapView";
import { TheoryMapView } from "./TheoryMapView";

// ─── colours ──────────────────────────────────────────────────────────────
const NODE_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  case_canonical:    { bg: "#1d4ed8", border: "#1e40af", text: "#ffffff" },
  case_indexed:      { bg: "#d97706", border: "#b45309", text: "#ffffff" },
  authority:         { bg: "#6b7280", border: "#4b5563", text: "#ffffff" },
  sector:            { bg: "#059669", border: "#047857", text: "#ffffff" },
  outcome:           { bg: "#7c3aed", border: "#6d28d9", text: "#ffffff" },
  party:             { bg: "#0891b2", border: "#0e7490", text: "#ffffff" },
  product_market:    { bg: "#0369a1", border: "#075985", text: "#ffffff" },
  geographic_market: { bg: "#4f46e5", border: "#4338ca", text: "#ffffff" },
  theory_of_harm:    { bg: "#be185d", border: "#9d174d", text: "#ffffff" },
  concept:           { bg: "#92400e", border: "#78350f", text: "#ffffff" },
  default:           { bg: "#94a3b8", border: "#64748b", text: "#ffffff" },
};

const FILTERABLE_TYPES = ["party", "sector", "geographic_market", "theory_of_harm", "product_market"] as const;
type FilterableType = (typeof FILTERABLE_TYPES)[number];

function nodeColor(node: GraphNode) {
  if (node.type === "case") {
    return node.data_layer === "indexed"
      ? NODE_COLORS.case_indexed
      : NODE_COLORS.case_canonical;
  }
  return NODE_COLORS[node.type] ?? NODE_COLORS.default;
}

function truncate(s: string, max = 26) {
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

class GraphError extends Error {
  url: string;
  status?: number;
  bodyExcerpt?: string;
  constructor(msg: string, url: string, status?: number, bodyExcerpt?: string) {
    super(msg);
    this.name = "GraphError";
    this.url = url;
    this.status = status;
    this.bodyExcerpt = bodyExcerpt;
  }
}

function getApiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

async function fetchNeighborhood(caseId: string): Promise<GraphNeighborhoodResponse> {
  const url = `${getApiBase()}/graph/neighborhood/${caseId}`;
  let res: Response;
  try {
    res = await fetch(url);
  } catch (e) {
    throw new GraphError(
      `Network error — is the API running? (${e instanceof Error ? e.message : String(e)})`,
      url
    );
  }
  if (!res.ok) {
    let body = "";
    try { body = (await res.text()).slice(0, 300); } catch { /* ignore */ }
    throw new GraphError(`HTTP ${res.status}`, url, res.status, body);
  }
  return res.json() as Promise<GraphNeighborhoodResponse>;
}

async function fetchFirstSearchResult(q: string): Promise<SearchHit | null> {
  const url = `${getApiBase()}/search/all?q=${encodeURIComponent(q)}`;
  let res: Response;
  try {
    res = await fetch(url);
  } catch (e) {
    throw new GraphError(
      `Network error on search (${e instanceof Error ? e.message : String(e)})`,
      url
    );
  }
  if (!res.ok) {
    let body = "";
    try { body = (await res.text()).slice(0, 300); } catch { /* ignore */ }
    throw new GraphError(`Search HTTP ${res.status}`, url, res.status, body);
  }
  const hits: SearchHit[] = await res.json();
  return (
    hits.find((h) => h.data_layer === "canonical") ??
    hits[0] ??
    null
  );
}

interface SearchHit {
  case_id: string;
  case_name: string;
  data_layer: string;
  record_status: string;
  jurisdiction: string;
  authority: string;
  decision_date: string;
}

interface ErrorInfo {
  msg: string;
  url: string;
  status?: number;
  bodyExcerpt?: string;
}

type GraphStatus = "idle" | "loading-default" | "loading" | "loaded" | "empty" | "error";
type Tab = "case" | "market" | "theory";

interface Props {
  initialCaseId?: string;
  initialTab?: Tab;
}

// ─── component ────────────────────────────────────────────────────────────
export function GraphView({ initialCaseId, initialTab = "case" }: Props) {
  const router = useRouter();
  const cyContainerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<import("cytoscape").Core | null>(null);

  const [tab, setTab] = useState<Tab>(initialTab);

  // Case neighborhood state
  const [query, setQuery]               = useState("");
  const [hits, setHits]                 = useState<SearchHit[]>([]);
  const [searching, setSearching]       = useState(false);
  const [noResults, setNoResults]       = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [activeCaseName, setActiveCaseName] = useState<string>("");

  const [neighborhood, setNeighborhood] = useState<GraphNeighborhoodResponse | null>(null);
  const [status, setStatus]             = useState<GraphStatus>("loading-default");
  const [errorInfo, setErrorInfo]       = useState<ErrorInfo | null>(null);
  const [tooltip, setTooltip]           = useState<{ node: GraphNode; x: number; y: number } | null>(null);

  // Entity detail panel state (for case neighborhood tab)
  const [selectedEntity, setSelectedEntity] = useState<{
    type: string;
    name: string;
    nodeId: string;
  } | null>(null);
  const [entityCases, setEntityCases] = useState<EntityCase[]>([]);
  const [expandLoading, setExpandLoading] = useState(false);

  // Node type visibility filters
  const [visibleTypes, setVisibleTypes] = useState<Set<FilterableType>>(
    new Set(FILTERABLE_TYPES)
  );

  function toggleType(type: FilterableType) {
    setVisibleTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  // Apply visibility to Cytoscape when visibleTypes changes
  useEffect(() => {
    if (!cyRef.current) return;
    FILTERABLE_TYPES.forEach((type) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const eles = cyRef.current!.nodes(`[nodeType = "${type}"]`) as any;
      if (visibleTypes.has(type)) eles.show();
      else eles.hide();
    });
  }, [visibleTypes]);

  function applyNeighborhood(data: GraphNeighborhoodResponse, name: string) {
    setNeighborhood(data);
    setActiveCaseName(name);
    setStatus(data.nodes.length === 0 ? "empty" : "loaded");
    setErrorInfo(null);
    setSelectedEntity(null);
    setEntityCases([]);
  }

  function applyError(e: unknown) {
    if (e instanceof GraphError) {
      setErrorInfo({ msg: e.message, url: e.url, status: e.status, bodyExcerpt: e.bodyExcerpt });
    } else {
      setErrorInfo({ msg: String(e), url: "" });
    }
    setStatus("error");
  }

  // Default load on mount (case tab only)
  useEffect(() => {
    if (tab !== "case") return;
    setStatus("loading-default");
    (async () => {
      try {
        if (initialCaseId) {
          const data = await fetchNeighborhood(initialCaseId);
          applyNeighborhood(data, data.center_case_id.replace(/_/g, " "));
          return;
        }
        const hit = await fetchFirstSearchResult("microsoft");
        if (!hit) throw new GraphError("No cases found for default query 'microsoft'", `${getApiBase()}/search/all?q=microsoft`);
        const data = await fetchNeighborhood(hit.case_id);
        applyNeighborhood(data, hit.case_name);
      } catch (e) {
        applyError(e);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Search debounce
  useEffect(() => {
    const q = query.trim();
    if (!q) { setHits([]); setNoResults(false); setDropdownOpen(false); return; }
    setNoResults(false);
    const tid = setTimeout(async () => {
      setSearching(true);
      try {
        const url = `${getApiBase()}/search/all?q=${encodeURIComponent(q)}`;
        const res = await fetch(url);
        if (res.ok) {
          const data: SearchHit[] = await res.json();
          setHits(data);
          setNoResults(data.length === 0);
          setDropdownOpen(true);
        }
      } finally {
        setSearching(false);
      }
    }, 280);
    return () => clearTimeout(tid);
  }, [query]);

  function selectCase(hit: SearchHit) {
    setDropdownOpen(false);
    setHits([]);
    setQuery(hit.case_name);
    setStatus("loading");
    setNeighborhood(null);
    setErrorInfo(null);
    setSelectedEntity(null);
    setEntityCases([]);
    fetchNeighborhood(hit.case_id)
      .then((data) => applyNeighborhood(data, hit.case_name))
      .catch(applyError);
  }

  async function fetchEntityCases(type: string, name: string) {
    try {
      if (type === "product_market") {
        const data = await getGraphMarket(name, false);
        setEntityCases(data.cases);
      } else if (type === "theory_of_harm") {
        const data = await getGraphTheory(name, false);
        setEntityCases(data.cases);
      } else {
        setEntityCases([]);
      }
    } catch {
      setEntityCases([]);
    }
  }

  function handleExpand() {
    if (!cyRef.current || entityCases.length === 0 || !selectedEntity) return;
    setExpandLoading(true);
    const cy = cyRef.current;

    entityCases.forEach((ec) => {
      const caseNodeId = `case:${ec.case_id}`;
      if (!cy.getElementById(caseNodeId).length) {
        const colors = NODE_COLORS.case_canonical;
        cy.add([
          {
            data: {
              id: caseNodeId,
              label: truncate(ec.case_name),
              fullLabel: ec.case_name,
              nodeType: "case",
              dataLayer: "canonical",
              recordStatus: "canonical_reviewed",
              href: `/cases/${ec.case_id}`,
              bg: colors.bg,
              border: colors.border,
              textColor: colors.text,
              isCenter: false,
            },
          },
          {
            data: {
              id: `${selectedEntity.nodeId}->${caseNodeId}:SHARES`,
              source: selectedEntity.nodeId,
              target: caseNodeId,
              edgeType: "SHARES_ENTITY",
              qualityLevel: "canonical_reviewed",
              isIndexedEdge: false,
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
      padding: 40,
      nodeRepulsion: () => 8000,
    } as import("cytoscape").CoseLayoutOptions).run();

    setExpandLoading(false);
  }

  // Build Cytoscape graph for case neighborhood
  useEffect(() => {
    if (!neighborhood || !cyContainerRef.current) return;

    const nodeMap = new Map<string, GraphNode>(
      neighborhood.nodes.map((n) => [n.id, n])
    );

    import("cytoscape").then(({ default: Cytoscape }) => {
      cyRef.current?.destroy();
      cyRef.current = null;

      const elements: import("cytoscape").ElementDefinition[] = [
        ...neighborhood.nodes.map((n) => {
          const colors = nodeColor(n);
          const isCenter = n.id === `case:${neighborhood.center_case_id}`;
          return {
            data: {
              id: n.id,
              label: truncate(n.label),
              fullLabel: n.label,
              nodeType: n.type,
              dataLayer: n.data_layer ?? null,
              recordStatus: n.record_status ?? null,
              href: n.href ?? null,
              bg: colors.bg,
              border: colors.border,
              textColor: colors.text,
              isCenter,
            },
          };
        }),
        ...neighborhood.edges.map((e) => ({
          data: {
            id: e.id,
            source: e.source,
            target: e.target,
            edgeType: e.type,
            qualityLevel: e.quality_level ?? null,
            isIndexedEdge:
              e.quality_level === "indexed_metadata" || e.quality_level === "indexed",
          },
        })),
      ];

      const cy = Cytoscape({
        container: cyContainerRef.current!,
        elements,
        style: [
          {
            selector: "node",
            style: {
              "background-color": "data(bg)",
              "border-color": "data(border)",
              "border-width": 2,
              label: "data(label)",
              color: "data(textColor)",
              "text-valign": "center",
              "text-halign": "center",
              "font-size": "10px",
              "font-family": "ui-sans-serif, system-ui, sans-serif",
              width: 100,
              height: 38,
              shape: "round-rectangle",
              "text-wrap": "wrap",
              "text-max-width": "88px",
              padding: "6px",
            },
          },
          {
            selector: "node[?isCenter]",
            style: { width: 140, height: 54, "font-size": "12px", "font-weight": "bold", "border-width": 4 },
          },
          {
            selector: 'node[dataLayer = "indexed"]',
            style: { "border-style": "dashed" },
          },
          {
            selector: "edge",
            style: {
              width: 1.5,
              "line-color": "#cbd5e1",
              "target-arrow-color": "#cbd5e1",
              "target-arrow-shape": "triangle",
              "curve-style": "bezier",
            },
          },
          {
            selector: "edge[?isIndexedEdge]",
            style: {
              "line-style": "dashed",
              "line-color": "#fbbf24",
              "target-arrow-color": "#fbbf24",
            },
          },
          {
            selector: "node:selected",
            style: { "border-width": 4, "border-color": "#f59e0b" },
          },
        ],
        layout: { name: "preset" },
      });

      cyRef.current = cy;

      const layout = cy.layout({
        name: "cose",
        animate: false,
        nodeRepulsion: () => 8000,
        idealEdgeLength: () => 110,
        nodeOverlap: 20,
        fit: false,
        padding: 40,
        randomize: true,
      } as import("cytoscape").CoseLayoutOptions);

      layout.one("layoutstop", () => cy.fit(cy.elements(), 40));
      layout.run();

      // Apply current visibility filters to new graph
      FILTERABLE_TYPES.forEach((type) => {
        if (!visibleTypes.has(type)) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (cy.nodes(`[nodeType = "${type}"]`) as any).hide();
        }
      });

      cy.on("tap", "node", async (evt) => {
        const nodeType: string = evt.target.data("nodeType");
        const href: string | null = evt.target.data("href");
        const nodeLabel: string = evt.target.data("fullLabel");
        const nodeId: string = evt.target.data("id");

        if (nodeType === "case") {
          if (href) router.push(href);
          return;
        }

        if (nodeType === "product_market" || nodeType === "theory_of_harm") {
          setSelectedEntity({ type: nodeType, name: nodeLabel, nodeId });
          setEntityCases([]);
          fetchEntityCases(nodeType, nodeLabel);
        }
      });

      cy.on("mouseover", "node", (evt) => {
        const nodeData = nodeMap.get(evt.target.data("id") as string);
        if (nodeData) {
          const pos = evt.renderedPosition;
          setTooltip({ node: nodeData, x: pos.x, y: pos.y });
        }
      });
      cy.on("mouseout", "node", () => setTooltip(null));
    });

    return () => {
      cyRef.current?.destroy();
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [neighborhood]);

  // ─── render ──────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-4">

      {/* ── Tab navigation ──────────────────────────────────────────────── */}
      <div className="flex border border-slate-200 rounded-lg overflow-hidden text-sm w-fit">
        {(["case", "market", "theory"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "px-4 py-2 transition-colors capitalize",
              tab === t
                ? "bg-slate-800 text-white"
                : "text-slate-600 hover:bg-slate-50"
            )}
          >
            {t === "case" ? "Case Neighborhood" : t === "market" ? "Market Map" : "Theory Map"}
          </button>
        ))}
      </div>

      {/* ── Market Map tab ──────────────────────────────────────────────── */}
      {tab === "market" && <MarketMapView />}

      {/* ── Theory Map tab ──────────────────────────────────────────────── */}
      {tab === "theory" && <TheoryMapView />}

      {/* ── Case Neighborhood tab ───────────────────────────────────────── */}
      {tab === "case" && (
        <>
          {/* Search */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Select a case to explore
            </label>
            <div className="relative">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onFocus={() => { if (hits.length > 0) setDropdownOpen(true); }}
                placeholder="Search by case name, party, sector…"
                className="w-full border border-slate-300 rounded-lg px-4 py-2 pr-28 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-2 pointer-events-none">
                {searching && <span className="text-xs text-slate-400 animate-pulse">Searching…</span>}
                {activeCaseName && !dropdownOpen && (
                  <span className="hidden sm:block text-xs bg-blue-50 text-blue-700 border border-blue-200 rounded px-1.5 py-0.5 max-w-[150px] truncate">
                    {activeCaseName}
                  </span>
                )}
              </div>
            </div>

            {dropdownOpen && (
              <div className="mt-1 border border-slate-200 rounded-lg shadow-md bg-white overflow-hidden">
                {noResults ? (
                  <p className="px-4 py-3 text-sm text-slate-500">
                    No cases found for &ldquo;{query}&rdquo;.
                  </p>
                ) : (
                  <ul className="max-h-72 overflow-y-auto divide-y divide-slate-100">
                    {hits.map((hit) => {
                      const isIndexed = hit.data_layer === "indexed";
                      return (
                        <li key={`${hit.case_id}-${hit.data_layer}`}>
                          <button
                            className="w-full text-left px-4 py-2.5 hover:bg-slate-50 transition-colors"
                            onClick={() => selectCase(hit)}
                          >
                            <div className="flex items-start gap-2">
                              <span className={cn(
                                "mt-0.5 shrink-0 inline-block text-xs px-1.5 py-0.5 rounded font-semibold",
                                isIndexed ? "bg-amber-100 text-amber-800" : "bg-blue-100 text-blue-800"
                              )}>
                                {isIndexed ? "indexed" : "reviewed"}
                              </span>
                              <div className="min-w-0">
                                <div className="text-sm font-medium text-slate-900 truncate">{hit.case_name}</div>
                                <div className="text-xs text-slate-500 mt-0.5">
                                  {hit.jurisdiction} · {hit.authority} · {hit.decision_date?.slice(0, 4)}
                                </div>
                              </div>
                            </div>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
                <div className="border-t border-slate-100 px-4 py-1.5">
                  <button className="text-xs text-slate-400 hover:text-slate-600" onClick={() => setDropdownOpen(false)}>
                    Close
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Node type filters */}
          <div className="flex flex-wrap gap-3 items-center text-xs">
            <span className="text-slate-500 font-medium">Show:</span>
            {FILTERABLE_TYPES.map((type) => (
              <label key={type} className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={visibleTypes.has(type)}
                  onChange={() => toggleType(type)}
                  className="rounded"
                />
                <span className="text-slate-600 capitalize">{type.replace(/_/g, " ")}</span>
              </label>
            ))}
          </div>

          {/* Legend */}
          <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs">
            {[
              { color: "#1d4ed8", label: "Canonical (source-reviewed)", dashed: false },
              { color: "#d97706", label: "Indexed (metadata only)",     dashed: true  },
              { color: "#6b7280", label: "Authority" },
              { color: "#059669", label: "Sector" },
              { color: "#7c3aed", label: "Outcome" },
              { color: "#0891b2", label: "Party" },
              { color: "#0369a1", label: "Product market" },
              { color: "#4f46e5", label: "Geographic market" },
              { color: "#be185d", label: "Theory of harm" },
            ].map((item) => (
              <span key={item.label} className="flex items-center gap-1.5">
                <span
                  className="inline-block w-3 h-3 rounded-sm shrink-0"
                  style={{
                    background: item.color,
                    outline: item.dashed ? `2px dashed ${item.color}` : undefined,
                    outlineOffset: item.dashed ? "1px" : undefined,
                  }}
                />
                <span className="text-slate-600">{item.label}</span>
              </span>
            ))}
          </div>

          {/* Trust banner */}
          <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2">
            <strong>Trust labels:</strong>{" "}
            <span className="font-semibold text-blue-700">canonical_reviewed</span> nodes are source-backed.{" "}
            <span className="font-semibold text-amber-700">indexed_metadata</span> nodes (dashed) are metadata only.
            Click a <span className="font-semibold">market</span> or <span className="font-semibold">theory</span> node to see all cases that share it.
          </div>

          {/* Canvas + entity panel */}
          <div
            className="relative border border-slate-200 rounded-xl overflow-hidden bg-slate-50 flex"
          >
            {/* Cytoscape canvas */}
            <div className="relative flex-1" style={{ minHeight: 520 }}>
              {status === "loading-default" && (
                <Overlay><Spinner /><span className="ml-2 text-slate-500 text-sm">Loading default graph…</span></Overlay>
              )}
              {status === "loading" && (
                <Overlay><Spinner /><span className="ml-2 text-slate-500 text-sm">Loading neighborhood…</span></Overlay>
              )}
              {status === "error" && errorInfo && (
                <Overlay>
                  <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 max-w-sm w-full mx-4">
                    <p className="font-medium text-sm mb-2">Could not load graph</p>
                    <dl className="text-xs space-y-1">
                      {errorInfo.status !== undefined && (
                        <div className="flex gap-2"><dt className="text-red-400 shrink-0">HTTP</dt><dd className="font-mono">{errorInfo.status}</dd></div>
                      )}
                      <div className="flex gap-2"><dt className="text-red-400 shrink-0">URL</dt><dd className="font-mono break-all text-red-600">{errorInfo.url}</dd></div>
                      <div className="flex gap-2"><dt className="text-red-400 shrink-0">Error</dt><dd>{errorInfo.msg}</dd></div>
                    </dl>
                    {errorInfo.bodyExcerpt && (
                      <pre className="mt-2 text-xs bg-red-100 rounded p-2 overflow-auto max-h-24 whitespace-pre-wrap break-all">{errorInfo.bodyExcerpt}</pre>
                    )}
                  </div>
                </Overlay>
              )}
              {status === "empty" && (
                <Overlay><p className="text-slate-400 text-sm">Graph loaded but no nodes returned.</p></Overlay>
              )}

              <div ref={cyContainerRef} className="w-full h-full" style={{ minHeight: 520 }} />

              {/* Hover tooltip */}
              {tooltip && (
                <div
                  className="absolute pointer-events-none z-10 bg-white border border-slate-200 rounded-lg shadow-lg px-3 py-2 text-xs max-w-xs"
                  style={{ left: tooltip.x + 14, top: tooltip.y - 12 }}
                >
                  <p className="font-semibold text-slate-900 mb-1 break-words">{tooltip.node.label}</p>
                  <p className="text-slate-500">Type: <span className="text-slate-700">{tooltip.node.type.replace(/_/g, " ")}</span></p>
                  {tooltip.node.data_layer && (
                    <p className="text-slate-500">
                      Trust:{" "}
                      <span className={tooltip.node.data_layer === "indexed" ? "text-amber-700 font-medium" : "text-blue-700 font-medium"}>
                        {tooltip.node.record_status ?? tooltip.node.data_layer}
                      </span>
                    </p>
                  )}
                  {(tooltip.node.type === "product_market" || tooltip.node.type === "theory_of_harm") && (
                    <p className="mt-1 text-slate-500">Click to see related cases →</p>
                  )}
                  {tooltip.node.type === "case" && tooltip.node.href && (
                    <p className="mt-1 text-blue-600">Click to open →</p>
                  )}
                </div>
              )}
            </div>

            {/* Entity detail panel */}
            {selectedEntity && (
              <EntityDetailPanel
                title={selectedEntity.name}
                subtitle={`${entityCases.length} case${entityCases.length !== 1 ? "s" : ""} share this ${selectedEntity.type.replace(/_/g, " ")}`}
                statusBreakdown={undefined}
                entityType={selectedEntity.type === "product_market" ? "market" : "theory"}
                cases={entityCases}
                onExpand={handleExpand}
                expandLoading={expandLoading}
                expandLabel="Expand in graph"
                onClose={() => { setSelectedEntity(null); setEntityCases([]); }}
              />
            )}
          </div>

          {/* Footer stats */}
          {neighborhood && status === "loaded" && (
            <div className="text-xs text-slate-400 flex gap-4 flex-wrap">
              <span>{neighborhood.nodes.length} nodes</span>
              <span>{neighborhood.edges.length} edges</span>
              <span>source: {neighborhood.source}</span>
              <span className="text-slate-300">|</span>
              <span className="text-slate-500 truncate">{activeCaseName}</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Overlay({ children }: { children: React.ReactNode }) {
  return (
    <div className="absolute inset-0 flex items-center justify-center z-10 bg-slate-50/80">
      <div className="flex items-center">{children}</div>
    </div>
  );
}

function Spinner() {
  return (
    <svg className="animate-spin h-4 w-4 text-slate-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
  );
}
