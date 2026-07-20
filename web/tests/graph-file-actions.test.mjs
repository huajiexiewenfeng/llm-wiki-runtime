import assert from "node:assert/strict";
import test from "node:test";

import { resolveLocalFileAction } from "../src/graph-file-actions.js";

test("resolveLocalFileAction derives a safe absolute Windows path from the fixed graph location", () => {
  const action = resolveLocalFileAction(
    "file:///C:/wiki/.llm-wiki/.meta/graph/hr/graph.html",
    "records/candidates/alice.md",
  );

  assert.deepEqual(action, {
    absolutePath: "C:\\wiki\\.llm-wiki\\records\\candidates\\alice.md",
    absoluteUrl: "file:///C:/wiki/.llm-wiki/records/candidates/alice.md",
  });
});

test("resolveLocalFileAction disables absolute actions for unsafe paths and moved or non-file pages", () => {
  const graphUrl = "file:///C:/wiki/.llm-wiki/.meta/graph/hr/graph.html";

  assert.equal(resolveLocalFileAction(graphUrl, "../secrets.txt"), null);
  assert.equal(resolveLocalFileAction(graphUrl, "/secrets.txt"), null);
  assert.equal(resolveLocalFileAction(graphUrl, "records\\alice.md"), null);
  assert.equal(resolveLocalFileAction("file:///C:/wiki/graph.html", "records/alice.md"), null);
  assert.equal(resolveLocalFileAction("https://example.test/graph.html", "records/alice.md"), null);
});
