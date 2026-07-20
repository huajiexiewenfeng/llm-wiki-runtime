# Task 2 Report: Graph Contracts, Safe Paths, And Frontmatter

## Summary

Implemented stdlib-only, frozen graph contracts with deterministic serialization and SHA-256 IDs, strict scope-relative POSIX path normalization, and a bounded leading-frontmatter parser. The work is limited to the graph contracts and parsing utilities required by later tasks; it does not add collection, extraction, layout, export, CLI, or UI behavior.

## Files Changed

- `llm_wiki_runtime/graph_models.py` (new): graph dataclasses, canonical IDs, safe path normalization, and deterministic graph serialization.
- `llm_wiki_runtime/frontmatter.py` (new): restricted leading-frontmatter parser with scalar and shallow flow-list support only.
- `tests/test_graph_models.py` (new): frozen-contract, deterministic ordering/IDs, POSIX normalization, and unsafe-path coverage.
- `tests/test_frontmatter.py` (new): scalar coercion, offsets, duplicate keys, malformed delimiter, and unsupported YAML-form coverage.

## RED/GREEN Evidence

### RED: Graph Models

Command:

```powershell
$env:UV_CACHE_DIR=(Resolve-Path '.uv-cache'); $env:PIP_CACHE_DIR=(Resolve-Path '.pip-cache'); uv run --offline --python 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' --with pytest==9.1.1 --no-project python -m pytest -q -p no:cacheprovider --basetemp '.test-tmp' tests/test_graph_models.py
```

Exact result: exit 1, collection error in 0.32s: `ModuleNotFoundError: No module named 'llm_wiki_runtime.graph_models'`.

### GREEN: Graph Models

The same command passed: `15 passed in 0.07s`.

### RED: Frontmatter

Command:

```powershell
$env:UV_CACHE_DIR=(Resolve-Path '.uv-cache'); $env:PIP_CACHE_DIR=(Resolve-Path '.pip-cache'); uv run --offline --python 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' --with pytest==9.1.1 --no-project python -m pytest -q -p no:cacheprovider --basetemp '.test-tmp' tests/test_frontmatter.py
```

Exact result: exit 1, collection error in 0.33s: `ModuleNotFoundError: No module named 'llm_wiki_runtime.frontmatter'`.

### GREEN: Frontmatter

The same command passed: `21 passed in 0.06s`.

## Focused Suite

Command:

```powershell
$env:UV_CACHE_DIR=(Resolve-Path '.uv-cache'); $env:PIP_CACHE_DIR=(Resolve-Path '.pip-cache'); uv run --offline --python 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' --with pytest==9.1.1 --no-project python -m pytest -q -p no:cacheprovider --basetemp '.test-tmp' tests/test_graph_models.py tests/test_frontmatter.py tests/test_paths.py
```

Exact result: `45 passed in 0.40s`.

## Full Suite

Command:

```powershell
$env:UV_CACHE_DIR=(Resolve-Path '.uv-cache'); $env:PIP_CACHE_DIR=(Resolve-Path '.pip-cache'); uv run --offline --python 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' --with pytest==9.1.1 --no-project python -m pytest -q -p no:cacheprovider --basetemp '.test-tmp'
```

Exact result: `153 passed in 19.93s`.

## Commit

- Commit: `ee1842a`
- Message: `feat: define deterministic graph contracts`

## Self-Review

- IDs use UTF-8 SHA-256 digests with stable `node_` and `edge_` prefixes and 16 lowercase hexadecimal characters.
- `DomainGraph.to_dict()` sorts nodes, edges, metadata keys, tags, and diagnostics according to the required keys.
- Path handling rejects absolute, drive-letter, UNC, empty, dot, and `..` traversal inputs while converting accepted separators to POSIX form.
- The frontmatter parser never imports YAML or evaluates tags, aliases, constructors, nested values, block lists, or multiline scalars.
- No dependency, packaging, collection, relation, layout, export, CLI, or UI files changed.

## Deviations And Residual Risks

- No deviations from the brief.
- The parser intentionally accepts a small plain-scalar/key syntax rather than general YAML; metadata needing punctuation-sensitive values should quote them.

## Important Review Fixes (2026-07-20)

### Summary And Files Changed

- Corrected `stable_node_id(domain_id, node_type, path)` to include all three canonical inputs and emit `<node_type>:<16 lowercase hex>`; record IDs now begin `record:`.
- Replaced delimiter-joined ID framing with compact canonical JSON UTF-8 arrays and changed edge IDs to `edge:<16 lowercase hex>`.
- Deep-froze node/edge metadata, edge evidence, and graph domain/stats mappings with defensive copies; serializers return fresh JSON-compatible dictionaries and lists.
- Added public `GraphNode.to_dict()` and `GraphEdge.to_dict()`, deterministic nested metadata/evidence ordering, and the Task 5 JSON envelope defaults: `schema_version`, `domain`, `stats`, `nodes`, `edges`, `diagnostics`.
- Allowed brackets and braces inside quoted frontmatter scalars without widening the restricted parser for unquoted or nested YAML structures.
- Changed: `llm_wiki_runtime/graph_models.py`, `llm_wiki_runtime/frontmatter.py`, `tests/test_graph_models.py`, and `tests/test_frontmatter.py`.

### Regression RED

Command:

```powershell
$env:UV_CACHE_DIR=(Resolve-Path '.uv-cache'); $env:PIP_CACHE_DIR=(Resolve-Path '.pip-cache'); uv run --offline --python 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' --with pytest==9.1.1 --no-project python -m pytest -q -p no:cacheprovider --basetemp '.test-tmp' tests/test_graph_models.py tests/test_frontmatter.py
```

Exact result before the fix: exit 1, `6 failed, 34 passed in 5.29s`. The failures demonstrated caller-mutable nested collections, the missing three-argument node-ID API, delimiter collisions, the absent Task 5 envelope, missing domain/stats support, and rejection of quoted brackets/braces.

### Focused GREEN And Full Suite

- Focused GREEN, same graph/frontmatter command: `40 passed in 0.13s`.
- Requested focused suite (`tests/test_graph_models.py tests/test_frontmatter.py tests/test_paths.py`): `49 passed in 0.47s`.
- Full suite: `157 passed in 18.56s`.

### Design Decisions

- Canonical JSON arrays are unambiguous for arbitrary UTF-8 identity values and preserve the readable ID prefix outside the hash.
- `MappingProxyType` plus tuple conversion stops mutations through both the original caller-owned objects and the frozen model fields; `to_dict()` deliberately recreates only plain JSON collections.
- `DomainGraph` appends schema fields after its original positional fields so prior `DomainGraph(nodes, edges, diagnostics)` callers remain valid, with defaults of `v0.1`, `{}`, and `{}` until Task 5 supplies analysis data.
- Evidence is sorted by sorted key/value pairs, and each emitted evidence mapping has sorted keys. Metadata/domain/stats keys are likewise sorted at serialization time.
- The frontmatter parser dispatches quoted scalars before syntax rejection, so quoted text may include brackets/braces while aliases, tags, constructors, flow objects, and nested structures remain rejected.

### Commit

- Code: `0afd947` (`fix: harden deterministic graph contracts`).
- This ignored evidence file is recorded separately because repository rules exclude `.superpowers` from ordinary staging.
