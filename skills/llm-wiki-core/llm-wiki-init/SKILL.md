---
name: llm-wiki-init
description: Use when initializing or enabling an LLM Wiki domain, choosing its first local storage binding, or restoring a missing profile snapshot.
---

# LLM Wiki Init

Initialize dynamic runtime state for one domain. Domain packages provide the
profile; runtime owns storage and snapshots. Do not modify any scp.yml.

## Runtime Availability Gate

1. Run `llm-wiki version` before resolving a profile.
2. If the command is unavailable, explain that the Core Skill is installed but
   its Python runtime is missing, then ask one plain-language confirmation.
3. Only after confirmation, use Python 3.10+ to run
   `python -m pip install "git+https://github.com/huajiexiewenfeng/llm-wiki-runtime.git"`.
4. Run `llm-wiki version` again and continue only when it reports success.

Do not install packages silently. If the user declines, Python is unavailable,
installation fails, or the command still cannot run, return
`runtime_unavailable` and let the calling Domain Skill continue through its
documented fallback.

## Inputs

Resolve the domain and profile from an explicit user choice or the calling
Skill's SCP. Locate that domain package's `llm-wiki-profile.yml`. Storage mode
comes from runtime/host configuration, not from SCP.

## Workflow

1. Run `llm-wiki resolve-config --profile PROFILE_ID`.
2. For `enabled`, report the existing `scope_id`, `scope_root`, and profile
   snapshot; do not initialize again.
3. For `disabled`, respect the remembered choice and use the caller's fallback.
4. For `missing_config`, show the domain, storage location, and privacy default,
   then ask one plain-language confirmation before creating anything.
5. When home storage has no configured root, run
   `llm-wiki init-home --home HOME_PATH` after confirmation.
6. Run `llm-wiki init-profile --scope-root SCOPE_ROOT --profile-path PROFILE_PATH
   --storage-mode STORAGE_MODE --scope-id SCOPE_ID`.
7. Run `resolve-config` again and require `enabled` before reporting success.

If the user declines, call `init-profile --decline` so the choice is remembered.
For `profile_mismatch`, `io_error`, `runtime_unavailable`, or `unexpected_error`,
do not claim initialization; return the status and a concrete next action.

Do not write directly inside .llm-wiki. Every initialization write goes through
the runtime CLI.
