---
name: llm-wiki-maintain
description: Use when diagnosing or auditing LLM Wiki configuration, SCP registration, ingest mappings, profile snapshots, context access, or runtime health.
---

# LLM Wiki Maintain

Maintenance checks contracts and storage state. It does not invent domain mappings,
merge business identities, or rewrite semantic records.

## Checks

1. Run `resolve-config` for the requested profile and report binding status.
2. Verify `.llm-wiki/.meta/profile.yml` exists for an enabled scope.
3. Run `scan-scp` for installed first-party SCP files and report warnings.
4. Run `validate-mapping` for each installed domain mapping.
5. Verify source and artifact registries are valid JSON with referenced files.
6. Run a narrowly filtered `load-context-pack` to verify read policy and profile
   includes/excludes without loading sensitive originals.

Report each check as pass, warning, or failure with exact paths and next actions.
Automatic repair is limited to deterministic runtime operations that the user
explicitly confirms. Semantic mapping/profile changes belong to the domain
package and require its normal design review.

Do not write directly inside .llm-wiki. Never bypass a failed runtime check with
a raw filesystem edit.
