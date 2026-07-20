import { build } from "esbuild";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = path.dirname(fileURLToPath(import.meta.url));
const assetRoot = path.resolve(webRoot, "..", "llm_wiki_runtime", "assets", "graph");
const entries = [
  ["graph-app", path.join(webRoot, "src", "graph-app.js")],
  ["index-app", path.join(webRoot, "src", "index-app.js")],
];
const forbiddenPatterns = [
  /\bfetch\s*\(/,
  /\bXMLHttpRequest\b/,
  /\bWebSocket\b/,
  /(?:^|[=(:,;])\s*import\s*\(/m,
  /https?:\/\//,
  /["'`]\s*\/\/[^\s"'`]+/,
];

function packageNameFromInput(input) {
  const match = input.match(/[\\/]node_modules[\\/](@[^\\/]+[\\/])?([^\\/]+)/);
  return match ? `${match[1] || ""}${match[2]}`.replace(/\\/g, "/") : null;
}

function listedNoticePackages(notices) {
  return new Map(
    [...notices.matchAll(/^\|\s*`([^`]+)`\s*\|\s*`?([^|`\s]+)`?\s*\|/gm)].map((match) => [match[1], match[2]]),
  );
}

function assertOffline(label, text) {
  for (const pattern of forbiddenPatterns) {
    if (pattern.test(text)) {
      throw new Error(`${label} contains forbidden offline-runtime pattern ${pattern}`);
    }
  }
}

async function checksum(filePath) {
  const content = await readFile(filePath);
  return `sha256:${createHash("sha256").update(content).digest("hex")}`;
}

const sourceTexts = await Promise.all(entries.map(([, entry]) => readFile(entry, "utf8")));
sourceTexts.forEach((text, index) => assertOffline(entries[index][1], text));

const results = [];
for (const [name, entry] of entries) {
  const output = path.join(assetRoot, `${name}.bundle.js`);
  results.push(
    await build({
      entryPoints: [entry],
      outfile: output,
      bundle: true,
      minify: true,
      format: "iife",
      platform: "browser",
      target: ["es2020"],
      metafile: true,
      write: true,
      legalComments: "none",
    }),
  );
}

const notices = await readFile(path.join(assetRoot, "THIRD_PARTY_NOTICES.md"), "utf8");
const noticePackages = listedNoticePackages(notices);
const bundledPackages = new Set(
  results.flatMap((result) => Object.keys(result.metafile.inputs).map(packageNameFromInput).filter(Boolean)),
);
for (const packageName of [...bundledPackages].sort()) {
  if (!noticePackages.has(packageName)) {
    throw new Error(`runtime bundle package is missing from notices: ${packageName}`);
  }
}

const assets = {};
for (const [name] of entries) {
  const fileName = `${name}.bundle.js`;
  const filePath = path.join(assetRoot, fileName);
  const contents = await readFile(filePath, "utf8");
  assertOffline(fileName, contents);
  assets[fileName] = await checksum(filePath);
}
await writeFile(
  path.join(assetRoot, "ASSET_CHECKSUMS.json"),
  `${JSON.stringify({ algorithm: "sha256", assets: Object.fromEntries(Object.entries(assets).sort()) }, null, 2)}\n`,
  "utf8",
);
