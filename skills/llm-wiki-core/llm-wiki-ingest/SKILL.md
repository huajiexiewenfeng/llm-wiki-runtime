---
name: llm-wiki-ingest
description: Use when importing durable knowledge from files, exported conversations, Codex tasks, or a domain Skill result into an enabled LLM Wiki.
---

# LLM Wiki Ingest

The generic ingest Skill orchestrates access. The domain-owned mapping and its
owner SCP define meaning; the active profile defines paths and write modes.

## Contract Gate

1. Resolve the explicit domain/profile or use the calling Skill's SCP.
2. Require `enabled` from `resolve-config`.
3. Locate the domain's `ingest-mapping.yml`, owner SCP, and active profile.
4. Run `validate-mapping` before interpreting or writing domain records.
5. For `domain_mapping_required`, stop structured ingest and use the domain's
   documented fallback. For `validation_error`, report the contract mismatch.

## Preview Gate

Acquire the source through a host adapter. For Codex history, read
`references/codex-thread-source.md`. Select exact source-backed ranges and show:

- proposed domain, record types, and identities,
- verbatim excerpts and stable message references,
- sensitive-data risk flags and skipped categories,
- possible duplicates that need user confirmation.

Do not call any write command before the user confirms the preview.

## Retry-Safe Write Order

After confirmation:

1. Capture an ISO-8601 confirmation timestamp and run `prepare-excerpt`.
2. Run `copy-source` with controlled excerpt metadata.
3. Run `write-record` for the immutable `jd_version`.
4. Use `load-context-pack --path-json` or `--glob-json` for the exact
   `job_profile`; update it only when it does not reference `jd_version_id`.
5. Run profile-aware `append-log` with
   `event_id=hr-jd-import:{source_id}:{job_id}:{jd_version_id}`.
6. Return per-step results, `context_refs`, and the next useful query.

`already_exists` is successful idempotency. On retry, continue missing steps but
never overwrite an immutable version or rewrite a job profile that already links
the version. If any write fails, report completed references and do not claim the
whole ingest succeeded.

Do not write directly inside .llm-wiki. Do not replace runtime writes with raw
Markdown writes, even during fallback.
