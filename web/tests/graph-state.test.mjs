import assert from "node:assert/strict";
import test from "node:test";
import Graph, { MultiDirectedGraph, MultiUndirectedGraph } from "graphology";

import {
  edgeKeysForPath,
  filterVisibleNodeIds,
  neighborsWithinDepth,
  shortestPath,
} from "../src/graph-state.js";

function addNodes(graph, ids) {
  ids.forEach((id) => graph.addNode(id, { search_text: id, type: "record" }));
  return graph;
}

test("shortestPath returns one deterministic BFS path", () => {
  const graph = addNodes(new Graph(), ["a", "b", "c", "d"]);
  graph.addEdgeWithKey("ab", "a", "b", { type: "reference" });
  graph.addEdgeWithKey("bd", "b", "d", { type: "reference" });
  graph.addEdgeWithKey("ac", "a", "c", { type: "reference" });
  graph.addEdgeWithKey("cd", "c", "d", { type: "reference" });

  assert.deepEqual(shortestPath(graph, "a", "d"), ["a", "b", "d"]);
});

test("neighborsWithinDepth stops at the requested depth", () => {
  const graph = addNodes(new Graph(), ["a", "b", "c", "d"]);
  graph.addEdge("a", "b");
  graph.addEdge("b", "c");
  graph.addEdge("c", "d");

  assert.deepEqual([...neighborsWithinDepth(graph, "a", 2)], ["a", "b", "c"]);
});

test("neighborsWithinDepth rejects invalid depths and returns an empty set for a missing node", () => {
  const graph = addNodes(new Graph(), ["a"]);

  assert.deepEqual([...neighborsWithinDepth(graph, "missing", 1)], []);
  for (const depth of [0, 4, 1.5, "2", null]) {
    assert.throws(() => neighborsWithinDepth(graph, "a", depth), RangeError);
  }
});

test("state helpers preserve directed multi-graphs and return stable neighbor order", () => {
  const graph = addNodes(new MultiDirectedGraph(), ["a", "b", "c", "d"]);
  graph.addDirectedEdgeWithKey("ac-1", "a", "c", { type: "reference" });
  graph.addDirectedEdgeWithKey("ac-2", "a", "c", { type: "reference" });
  graph.addDirectedEdgeWithKey("ba", "b", "a", { type: "reference" });
  graph.addDirectedEdgeWithKey("ad", "a", "d", { type: "reference" });
  graph.addDirectedEdgeWithKey("db", "d", "b", { type: "reference" });

  const before = graph.export();
  assert.deepEqual([...neighborsWithinDepth(graph, "a", 1)], ["a", "b", "c", "d"]);
  assert.deepEqual(shortestPath(graph, "a", "b"), ["a", "b"]);
  assert.deepEqual(graph.export(), before);
});

test("edgeKeysForPath highlights an incoming-only edge found by undirected path exploration", () => {
  const graph = addNodes(new MultiDirectedGraph(), ["a", "b"]);
  graph.addDirectedEdgeWithKey("ba", "b", "a", { type: "reference" });

  assert.deepEqual(shortestPath(graph, "a", "b"), ["a", "b"]);
  assert.deepEqual([...edgeKeysForPath(graph, ["a", "b"])], ["ba"]);
});

test("edgeKeysForPath deterministically highlights parallel directed edges in both directions", () => {
  const graph = addNodes(new MultiDirectedGraph(), ["a", "b", "c"]);
  graph.addDirectedEdgeWithKey("ab-z", "a", "b", { type: "reference" });
  graph.addDirectedEdgeWithKey("ab-a", "a", "b", { type: "reference" });
  graph.addDirectedEdgeWithKey("ba-z", "b", "a", { type: "reference" });
  graph.addDirectedEdgeWithKey("ba-a", "b", "a", { type: "reference" });
  graph.addDirectedEdgeWithKey("bc", "b", "c", { type: "reference" });

  assert.deepEqual(
    [...edgeKeysForPath(graph, ["a", "b", "c"])],
    ["ab-a", "ab-z", "ba-a", "ba-z", "bc"],
  );
});

test("edgeKeysForPath highlights every parallel undirected edge", () => {
  const graph = addNodes(new MultiUndirectedGraph(), ["a", "b"]);
  graph.addUndirectedEdgeWithKey("ab-z", "a", "b", { type: "reference" });
  graph.addUndirectedEdgeWithKey("ab-a", "a", "b", { type: "reference" });

  assert.deepEqual([...edgeKeysForPath(graph, ["a", "b"])], ["ab-a", "ab-z"]);
});

test("shortestPath returns null for missing or disconnected endpoints", () => {
  const graph = addNodes(new Graph(), ["a", "b", "c"]);
  graph.addEdge("a", "b");

  assert.equal(shortestPath(graph, "a", "missing"), null);
  assert.equal(shortestPath(graph, "a", "c"), null);
  assert.deepEqual(shortestPath(graph, "b", "b"), ["b"]);
});

test("filterVisibleNodeIds matches search text, node types, and enabled edge types", () => {
  const graph = new Graph();
  graph.addNode("a", { search_text: "Alpha candidate", type: "candidate" });
  graph.addNode("b", { search_text: "Beta opening", type: "opening" });
  graph.addNode("c", { search_text: "Alpha archive", type: "candidate" });
  graph.addEdgeWithKey("ab", "a", "b", { type: "reference" });

  assert.deepEqual(
    [...filterVisibleNodeIds(graph, "alpha", new Set(["candidate"]), new Set(["reference"]))],
    ["a", "c"],
  );
  assert.deepEqual(
    [...filterVisibleNodeIds(graph, "", new Set(["candidate", "opening"]), new Set())],
    ["c"],
  );
});

test("filterVisibleNodeIds accepts absent filters and does not mutate graph attributes", () => {
  const graph = new Graph();
  graph.addNode("b", { search_text: "Beta", type: "opening" });
  graph.addNode("a", { search_text: "Alpha", type: "candidate" });
  graph.addEdge("a", "b", { type: "reference" });
  const before = graph.export();

  assert.deepEqual([...filterVisibleNodeIds(graph, "", null, null)], ["a", "b"]);
  assert.deepEqual(graph.export(), before);
});

test("filterVisibleNodeIds uses deterministic Unicode case normalization", () => {
  const graph = new Graph();
  graph.addNode("istanbul", { search_text: "ISTANBUL", type: "place" });

  assert.deepEqual([...filterVisibleNodeIds(graph, "istanbul", null, null)], ["istanbul"]);
});
