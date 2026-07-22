function compareIds(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

const DETAIL_INTERNAL_FIELDS = new Set([
  "metadata",
  "evidence",
  "search_text",
  "forceLabel",
  "size",
  "color",
  "x",
  "y",
  "visualCategory",
]);

function humanizeIdentifier(value) {
  const normalized = String(value ?? "").replace(/[_-]+/g, " ").trim();
  return normalized ? normalized[0].toUpperCase() + normalized.slice(1) : "Unknown";
}

export function nodeVisualCategory(node) {
  if (node?.type === "record" && node.subtype) {
    return `record:${node.subtype}`;
  }
  return node?.type || "unknown";
}

export function nodeDisplayKind(node) {
  return humanizeIdentifier(node?.type === "record" && node.subtype ? node.subtype : node?.type);
}

export function detailEntries(item) {
  const entries = [];
  const seen = new Set();
  for (const [key, value] of Object.entries(item ?? {})) {
    if (DETAIL_INTERNAL_FIELDS.has(key) || value == null) {
      continue;
    }
    entries.push([key, value]);
    seen.add(key);
  }
  for (const [key, value] of Object.entries(item?.metadata ?? {}).sort(([left], [right]) => compareIds(left, right))) {
    if (!seen.has(key) && value != null) {
      entries.push([key, value]);
    }
  }
  return entries;
}

function selectedValues(values) {
  if (values == null) {
    return null;
  }
  return values instanceof Set ? values : new Set(values);
}

function orderedNeighbors(graph, nodeId) {
  return [...graph.neighbors(nodeId)].sort(compareIds);
}

function validateDepth(depth) {
  if (!Number.isInteger(depth) || depth < 1 || depth > 3) {
    throw new RangeError("depth must be an integer from 1 through 3");
  }
}

export function neighborsWithinDepth(graph, start, depth) {
  validateDepth(depth);
  if (!graph.hasNode(start)) {
    return new Set();
  }

  const visible = new Set([start]);
  const queue = [[start, 0]];

  for (let index = 0; index < queue.length; index += 1) {
    const [nodeId, distance] = queue[index];
    if (distance === depth) {
      continue;
    }
    for (const neighborId of orderedNeighbors(graph, nodeId)) {
      if (!visible.has(neighborId)) {
        visible.add(neighborId);
        queue.push([neighborId, distance + 1]);
      }
    }
  }

  return new Set([...visible].sort(compareIds));
}

export function shortestPath(graph, source, target) {
  if (!graph.hasNode(source) || !graph.hasNode(target)) {
    return null;
  }
  if (source === target) {
    return [source];
  }

  const predecessor = new Map([[source, null]]);
  const queue = [source];

  for (let index = 0; index < queue.length; index += 1) {
    const nodeId = queue[index];
    for (const neighborId of orderedNeighbors(graph, nodeId)) {
      if (predecessor.has(neighborId)) {
        continue;
      }
      predecessor.set(neighborId, nodeId);
      if (neighborId === target) {
        const path = [];
        for (let current = target; current !== null; current = predecessor.get(current)) {
          path.push(current);
        }
        return path.reverse();
      }
      queue.push(neighborId);
    }
  }

  return null;
}

export function edgeKeysForPath(graph, path) {
  const edgeKeys = [];
  for (let index = 1; index < path.length; index += 1) {
    edgeKeys.push(...graph.edges(path[index - 1], path[index]).sort(compareIds));
  }
  return new Set(edgeKeys);
}

function hasEnabledIncidentEdge(graph, nodeId, edgeTypes) {
  const edgeIds = graph.edges(nodeId);
  if (edgeIds.length === 0) {
    return true;
  }
  return edgeIds.some((edgeId) => edgeTypes.has(graph.getEdgeAttribute(edgeId, "type")));
}

export function filterVisibleNodeIds(graph, query, nodeTypes, edgeTypes, recordSubtypes) {
  const normalizedQuery = String(query ?? "").trim().toLowerCase();
  const selectedNodeTypes = selectedValues(nodeTypes);
  const selectedEdgeTypes = selectedValues(edgeTypes);
  const selectedRecordSubtypes = selectedValues(recordSubtypes);

  return new Set(
    [...graph.nodes()]
      .sort(compareIds)
      .filter((nodeId) => {
        const attributes = graph.getNodeAttributes(nodeId);
        const searchText = String(attributes.search_text ?? "").toLowerCase();
        return (
          searchText.includes(normalizedQuery) &&
          (selectedNodeTypes === null || selectedNodeTypes.has(attributes.type)) &&
          (selectedRecordSubtypes === null || attributes.type !== "record" || selectedRecordSubtypes.has(attributes.subtype)) &&
          (selectedEdgeTypes === null || hasEnabledIncidentEdge(graph, nodeId, selectedEdgeTypes))
        );
      }),
  );
}
