import Graph from "graphology";
import Sigma from "sigma";

import { filterVisibleNodeIds, neighborsWithinDepth, shortestPath } from "./graph-state.js";

const TYPE_COLORS = ["#0f766e", "#2563eb", "#b45309", "#be123c", "#6d28d9", "#047857"];

function readPayload() {
  const element = document.getElementById("graph-data");
  if (element?.textContent) {
    return JSON.parse(element.textContent);
  }
  if (window.__LLM_WIKI_GRAPH__) {
    return window.__LLM_WIKI_GRAPH__;
  }
  throw new Error("graph data is missing");
}

function compareText(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function titleCase(value) {
  return String(value).replace(/[_-]+/g, " ");
}

function injectStyles() {
  const style = document.createElement("style");
  style.textContent = `
    #graph-app { color: #172033; font: 14px/1.4 system-ui, sans-serif; height: 100vh; min-height: 520px; }
    .lw-shell { display: grid; grid-template-columns: minmax(0, 1fr) 320px; grid-template-rows: auto minmax(0, 1fr); height: 100%; background: #f7fafc; }
    .lw-toolbar { grid-column: 1 / -1; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; min-height: 48px; padding: 8px 12px; border-bottom: 1px solid #cbd5e1; background: #ffffff; }
    .lw-toolbar input, .lw-toolbar select, .lw-toolbar button { box-sizing: border-box; height: 32px; border: 1px solid #94a3b8; border-radius: 4px; background: #ffffff; color: #172033; padding: 0 8px; }
    .lw-toolbar button { cursor: pointer; font-weight: 600; }
    .lw-toolbar button:hover { background: #e2e8f0; }
    .lw-search { min-width: 176px; flex: 1 1 220px; }
    .lw-filter { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
    .lw-filter input { height: auto; margin: 0; }
    .lw-canvas { grid-column: 1; min-height: 0; position: relative; }
    .lw-canvas canvas { display: block; }
    .lw-details { grid-column: 2; min-height: 0; overflow: auto; padding: 16px; border-left: 1px solid #cbd5e1; background: #ffffff; }
    .lw-details h2 { font-size: 16px; margin: 0 0 8px; }
    .lw-details h3 { font-size: 13px; margin: 18px 0 6px; }
    .lw-details p, .lw-details dd { overflow-wrap: anywhere; }
    .lw-details dl { margin: 0; }
    .lw-details dt { color: #475569; font-size: 12px; margin-top: 8px; }
    .lw-details dd { margin: 2px 0; }
    .lw-path-controls { display: grid; grid-template-columns: 1fr 1fr auto; gap: 6px; margin-top: 14px; }
    .lw-path-controls input { min-width: 0; height: 32px; border: 1px solid #94a3b8; border-radius: 4px; padding: 0 8px; }
    .lw-path-controls button, .lw-detail-actions button { min-height: 32px; border: 1px solid #94a3b8; border-radius: 4px; background: #ffffff; cursor: pointer; }
    .lw-status { color: #475569; font-size: 12px; margin: 10px 0 0; }
    .lw-detail-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 14px; }
    @media (max-width: 720px) { .lw-shell { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(280px, 1fr) auto; } .lw-canvas { grid-row: 2; } .lw-details { grid-column: 1; grid-row: 3; max-height: 42vh; border-left: 0; border-top: 1px solid #cbd5e1; } }
  `;
  document.head.append(style);
}

function createGraph(payload) {
  const graph = new Graph({ multi: true, type: "directed", allowSelfLoops: true });
  for (const node of payload.nodes ?? []) {
    graph.addNode(node.id, {
      ...node,
      label: node.label || node.id,
      x: Number.isFinite(node.x) ? node.x : 0,
      y: Number.isFinite(node.y) ? node.y : 0,
      size: 9,
    });
  }
  for (const edge of payload.edges ?? []) {
    if (graph.hasNode(edge.source) && graph.hasNode(edge.target)) {
      graph.addDirectedEdgeWithKey(edge.id, edge.source, edge.target, { ...edge, size: 1.5 });
    }
  }
  return graph;
}

function uniqueValues(items, field) {
  return [...new Set(items.map((item) => item[field]).filter(Boolean))].sort(compareText);
}

function addCheckboxes(container, label, values, selected, onChange) {
  for (const value of values) {
    const item = document.createElement("label");
    item.className = "lw-filter";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = true;
    input.value = value;
    input.addEventListener("change", () => {
      input.checked ? selected.add(value) : selected.delete(value);
      onChange();
    });
    item.append(input, document.createTextNode(`${label}: ${titleCase(value)}`));
    container.append(item);
  }
}

function detailContent(item, heading) {
  const fragment = document.createDocumentFragment();
  const title = document.createElement("h2");
  title.textContent = heading;
  fragment.append(title);
  if (!item) {
    const empty = document.createElement("p");
    empty.textContent = "Select a node or edge to inspect its evidence and paths.";
    fragment.append(empty);
    return fragment;
  }
  const details = document.createElement("dl");
  for (const [key, value] of Object.entries(item)) {
    if (["metadata", "evidence", "search_text", "x", "y"].includes(key) || value == null) continue;
    const name = document.createElement("dt");
    name.textContent = titleCase(key);
    const content = document.createElement("dd");
    content.textContent = Array.isArray(value) ? value.join(", ") : String(value);
    details.append(name, content);
  }
  fragment.append(details);
  if (item.evidence?.length) {
    const evidenceTitle = document.createElement("h3");
    evidenceTitle.textContent = "Evidence";
    const evidence = document.createElement("ul");
    for (const entry of item.evidence) {
      const row = document.createElement("li");
      row.textContent = entry.path || JSON.stringify(entry);
      evidence.append(row);
    }
    fragment.append(evidenceTitle, evidence);
  }
  return fragment;
}

function copyText(value) {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(value);
  }
  const area = document.createElement("textarea");
  area.value = value;
  document.body.append(area);
  area.select();
  document.execCommand("copy");
  area.remove();
  return Promise.resolve();
}

function graphApp() {
  injectStyles();
  const payload = readPayload();
  const graph = createGraph(payload);
  const root = document.getElementById("graph-app") || document.body;
  root.id = "graph-app";
  root.replaceChildren();

  const shell = document.createElement("main");
  shell.className = "lw-shell";
  const toolbar = document.createElement("section");
  toolbar.className = "lw-toolbar";
  const canvas = document.createElement("section");
  canvas.id = "graph-canvas";
  canvas.className = "lw-canvas";
  const details = document.createElement("aside");
  details.className = "lw-details";
  shell.append(toolbar, canvas, details);
  root.append(shell);

  const search = document.createElement("input");
  search.className = "lw-search";
  search.type = "search";
  search.placeholder = "Search graph";
  search.setAttribute("aria-label", "Search graph");
  const depth = document.createElement("select");
  depth.setAttribute("aria-label", "Neighbor depth");
  for (const value of [1, 2, 3]) {
    const option = new Option(`${value} hop${value === 1 ? "" : "s"}`, String(value));
    depth.add(option);
  }
  const reset = document.createElement("button");
  reset.type = "button";
  reset.textContent = "Reset";
  toolbar.append(search, depth, reset);

  const nodeTypes = new Set(uniqueValues(payload.nodes ?? [], "type"));
  const edgeTypes = new Set(uniqueValues(payload.edges ?? [], "type"));
  addCheckboxes(toolbar, "Node", [...nodeTypes], nodeTypes, apply);
  addCheckboxes(toolbar, "Edge", [...edgeTypes], edgeTypes, apply);

  const pathControls = document.createElement("div");
  pathControls.className = "lw-path-controls";
  const pathSource = document.createElement("input");
  pathSource.placeholder = "Path source ID";
  const pathTarget = document.createElement("input");
  pathTarget.placeholder = "Path target ID";
  const findPath = document.createElement("button");
  findPath.type = "button";
  findPath.textContent = "Find path";
  pathControls.append(pathSource, pathTarget, findPath);
  const status = document.createElement("p");
  status.className = "lw-status";
  const actions = document.createElement("div");
  actions.className = "lw-detail-actions";
  details.append(pathControls, status, actions);

  const renderer = new Sigma(graph, canvas, { renderEdgeLabels: false, zIndex: true });
  let selectedNode = null;
  let selectedItem = null;
  let pathNodes = new Set();
  let pathEdges = new Set();

  function visibleNodes() {
    const base = filterVisibleNodeIds(graph, search.value, nodeTypes, edgeTypes);
    if (!selectedNode || !graph.hasNode(selectedNode)) {
      return base;
    }
    const focused = neighborsWithinDepth(graph, selectedNode, Number(depth.value));
    return new Set([...base].filter((nodeId) => focused.has(nodeId)));
  }

  function showDetails(item, heading) {
    selectedItem = item;
    details.replaceChildren();
    details.append(detailContent(item, heading), pathControls, status, actions);
    actions.replaceChildren();
    if (item?.path) {
      const copy = document.createElement("button");
      copy.type = "button";
      copy.textContent = "Copy relative path";
      copy.addEventListener("click", () => copyText(item.path));
      const absolute = document.createElement("button");
      absolute.type = "button";
      absolute.textContent = "Copy absolute path";
      absolute.addEventListener("click", () => copyText(`${window.__LLM_WIKI_SCOPE_PATH__ || ""}${item.path}`));
      const open = document.createElement("button");
      open.type = "button";
      open.textContent = "Open local file";
      open.addEventListener("click", () => {
        const candidate = String(window.__LLM_WIKI_FILE_URL__ || "");
        if (candidate.startsWith("file:")) {
          window.open(candidate, "_blank", "noopener");
        }
      });
      actions.append(copy, absolute, open);
    }
  }

  function apply() {
    const visible = visibleNodes();
    renderer.setSettings({
      nodeReducer: (nodeId, data) => ({
        ...data,
        hidden: !visible.has(nodeId),
        highlighted: nodeId === selectedNode || pathNodes.has(nodeId),
        color: pathNodes.has(nodeId) ? "#d97706" : data.color,
      }),
      edgeReducer: (edgeId, data) => ({
        ...data,
        hidden:
          !visible.has(graph.source(edgeId)) ||
          !visible.has(graph.target(edgeId)) ||
          !edgeTypes.has(data.type),
        highlighted: pathEdges.has(edgeId),
        color: pathEdges.has(edgeId) ? "#d97706" : data.color,
      }),
    });
    renderer.refresh();
  }

  for (const [index, type] of uniqueValues(payload.nodes ?? [], "type").entries()) {
    graph.forEachNode((nodeId, attributes) => {
      if (attributes.type === type) {
        graph.mergeNodeAttributes(nodeId, { color: TYPE_COLORS[index % TYPE_COLORS.length] });
      }
    });
  }
  graph.forEachEdge((edgeId) => graph.mergeEdgeAttributes(edgeId, { color: "#94a3b8" }));

  renderer.on("clickNode", ({ node }) => {
    selectedNode = node;
    pathNodes = new Set();
    pathEdges = new Set();
    showDetails(graph.getNodeAttributes(node), "Node details");
    apply();
  });
  renderer.on("clickEdge", ({ edge }) => {
    selectedNode = null;
    pathNodes = new Set();
    pathEdges = new Set();
    showDetails(graph.getEdgeAttributes(edge), "Edge details");
    apply();
  });
  search.addEventListener("input", apply);
  depth.addEventListener("change", apply);
  reset.addEventListener("click", () => {
    selectedNode = null;
    selectedItem = null;
    pathNodes = new Set();
    pathEdges = new Set();
    search.value = "";
    nodeTypes.clear();
    edgeTypes.clear();
    uniqueValues(payload.nodes ?? [], "type").forEach((value) => nodeTypes.add(value));
    uniqueValues(payload.edges ?? [], "type").forEach((value) => edgeTypes.add(value));
    toolbar.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.checked = true;
    });
    showDetails(null, "Graph details");
    apply();
  });
  findPath.addEventListener("click", () => {
    const path = shortestPath(graph, pathSource.value, pathTarget.value);
    pathNodes = new Set(path || []);
    pathEdges = new Set();
    if (path) {
      for (let index = 1; index < path.length; index += 1) {
        const edge = graph.edge(path[index - 1], path[index]);
        if (edge) pathEdges.add(edge);
      }
      status.textContent = `Shortest path: ${path.join(" -> ")}`;
    } else {
      status.textContent = "No path found.";
    }
    apply();
  });

  showDetails(null, "Graph details");
  apply();
}

graphApp();
