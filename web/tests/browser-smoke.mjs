import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { chromium } from "playwright";

const testRoot = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(testRoot, "..");
const repoRoot = path.resolve(webRoot, "..");
const resultsRoot = path.join(webRoot, "test-results");
const python = process.env.PYTHON;
const installedBrowsers = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
];

if (!python) {
  throw new Error("Browser smoke requires PYTHON to point at the project test interpreter.");
}

async function launchBrowser() {
  try {
    return await chromium.launch({ headless: true });
  } catch (bundledError) {
    for (const executablePath of installedBrowsers) {
      if (!existsSync(executablePath)) continue;
      try {
        return await chromium.launch({ executablePath, headless: true });
      } catch {
        // Try the next deterministic local browser candidate.
      }
    }
    throw new Error(
      `No Playwright Chromium binary or compatible installed Chrome/Edge executable is available. Bundled launch: ${bundledError.message}; checked: ${installedBrowsers.join(", ")}`,
    );
  }
}

function overlaps(left, right) {
  return left.x < right.x + right.width && left.x + left.width > right.x && left.y < right.y + right.height && left.y + left.height > right.y;
}

async function stableCanvas(page, viewport) {
  await page.setViewportSize(viewport);
  await page.waitForTimeout(150);
  const canvas = page.locator("#graph-canvas canvas").first();
  await canvas.waitFor({ state: "visible" });
  const first = await canvas.boundingBox();
  await page.waitForTimeout(150);
  const second = await canvas.boundingBox();
  assert.ok(first && second, "Sigma canvas has a bounding box");
  assert.ok(first.width > 100 && first.height > 100, "Sigma canvas has nonzero desktop/mobile dimensions");
  assert.deepEqual(second, first, "Sigma canvas dimensions remain stable after rendering");
  return canvas;
}

async function nonBackgroundPixels(page) {
  return page.evaluate(() => {
    const renderer = window.__LLM_WIKI_GRAPH_RENDERER__;
    if (!renderer) throw new Error("graph renderer test hook is unavailable");
    renderer.render();
    return Math.max(0, ...[...document.querySelectorAll("#graph-canvas canvas")].map((element) => {
    const context = element.getContext("webgl2") || element.getContext("webgl");
    if (!context) return 0;
    const pixels = new Uint8Array(element.width * element.height * 4);
    context.readPixels(0, 0, element.width, element.height, context.RGBA, context.UNSIGNED_BYTE, pixels);
    let count = 0;
    for (let index = 0; index < pixels.length; index += 4) {
      if (pixels[index] !== 0 || pixels[index + 1] !== 0 || pixels[index + 2] !== 0) count += 1;
    }
    return count;
    }));
  });
}

async function selectAnyNode(page, canvas) {
  const box = await canvas.boundingBox();
  assert.ok(box, "Canvas has an actionable box");
  const point = await page.evaluate(() => {
    const renderer = window.__LLM_WIKI_GRAPH_RENDERER__;
    if (!renderer) throw new Error("graph renderer test hook is unavailable");
    const data = renderer.getNodeDisplayData("candidate-a");
    if (!data) throw new Error("fixture node display data is unavailable");
    return renderer.framedGraphToViewport({ x: data.x, y: data.y });
  });
  await page.mouse.click(box.x + point.x, box.y + point.y);
  await page.getByRole("heading", { name: "Node details" }).waitFor();
}

await mkdir(resultsRoot, { recursive: true });
const fixtureRoot = await mkdtemp(path.join(resultsRoot, "graph-fixture-"));
execFileSync(python, [path.join(testRoot, "make_fixture.py"), fixtureRoot], {
  cwd: repoRoot,
  stdio: "inherit",
});

const browser = await launchBrowser();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const externalRequests = [];
  page.on("request", (request) => {
    if (/^https?:/i.test(request.url())) externalRequests.push(request.url());
  });

  await page.goto(pathToFileURL(path.join(fixtureRoot, "index.html")).href);
  await page.getByRole("link", { name: "Human Resources" }).click();
  await page.waitForURL(/\/hr\/graph\.html$/);
  assert.deepEqual(externalRequests, [], "file:// graph pages make no HTTP(S) requests");

  const desktopCanvas = await stableCanvas(page, { width: 1440, height: 900 });
  assert.ok((await nonBackgroundPixels(page)) > 100, "desktop WebGL canvas contains rendered graph pixels");
  await page.screenshot({ path: path.join(resultsRoot, "graph-desktop.png"), fullPage: true });

  await page.getByLabel("Search graph").fill("alice");
  assert.equal(await page.getByLabel("Search graph").inputValue(), "alice");
  await page.getByLabel("Node: document").uncheck();
  assert.equal(await page.getByLabel("Node: document").isChecked(), false);
  await page.getByLabel("Neighbor depth").selectOption("2");
  assert.equal(await page.getByLabel("Neighbor depth").inputValue(), "2");
  await selectAnyNode(page, desktopCanvas);
  await page.getByPlaceholder("Path source ID").fill("candidate-a");
  await page.getByPlaceholder("Path target ID").fill("brief-c");
  await page.getByRole("button", { name: "Find path" }).click();
  await assertStatus(page, "Shortest path: candidate-a -> role-b -> brief-c");
  await page.getByRole("button", { name: "Reset" }).click();
  assert.equal(await page.getByLabel("Search graph").inputValue(), "");
  assert.equal(await page.getByLabel("Node: document").isChecked(), true);
  assert.equal(await page.getByLabel("Neighbor depth").inputValue(), "1");
  assert.equal(await page.getByPlaceholder("Path source ID").inputValue(), "");
  assert.equal(await page.getByPlaceholder("Path target ID").inputValue(), "");
  assert.equal(await page.locator(".lw-status").textContent(), "");
  await page.getByRole("heading", { name: "Graph details" }).waitFor();

  const toolbar = await page.locator(".lw-toolbar").boundingBox();
  const canvasBox = await desktopCanvas.boundingBox();
  const details = await page.locator(".lw-details").boundingBox();
  assert.ok(toolbar && canvasBox && details, "desktop graph regions have bounding boxes");
  assert.equal(overlaps(toolbar, canvasBox), false, "toolbar and canvas do not overlap");
  assert.equal(overlaps(toolbar, details), false, "toolbar and detail panel do not overlap");
  assert.equal(overlaps(canvasBox, details), false, "canvas and detail panel do not overlap");

  const mobileCanvas = await stableCanvas(page, { width: 390, height: 844 });
  assert.ok((await nonBackgroundPixels(page)) > 100, "mobile WebGL canvas contains rendered graph pixels");
  const rightNode = await page.evaluate(() => {
    const renderer = window.__LLM_WIKI_GRAPH_RENDERER__;
    const data = renderer.getNodeDisplayData("role-b");
    const point = renderer.framedGraphToViewport({ x: data.x, y: data.y });
    return { canvasWidth: document.querySelector("#graph-canvas canvas").clientWidth, x: point.x };
  });
  assert.ok(rightNode.x <= rightNode.canvasWidth - 120, "right-side node leaves room for its canvas label");
  const mobileToolbar = await page.locator(".lw-toolbar").boundingBox();
  const mobileDetails = await page.locator(".lw-details").boundingBox();
  assert.ok(mobileToolbar && mobileDetails, "mobile graph regions have bounding boxes");
  assert.equal(overlaps(mobileToolbar, mobileDetails), false, "mobile detail drawer does not overlap the toolbar");
  await page.screenshot({ path: path.join(resultsRoot, "graph-mobile.png"), fullPage: true });
} finally {
  await browser.close();
  await rm(fixtureRoot, { recursive: true, force: true });
}

async function assertStatus(page, expected) {
  await page.locator(".lw-status").getByText(expected).waitFor();
  assert.equal(await page.locator(".lw-status").textContent(), expected);
}
