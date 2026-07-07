# llm-wiki-runtime Workspace Design

## Status

This is the approved design for introducing `llm-wiki-runtime` as an independent top-level skill workspace inside `role-copilot-skills`.

The goal is to make `llm-wiki-runtime` a reusable local knowledge-base runtime and `.llm-wiki` access layer for domain skills. It is not an HR, DevOps, Project, Learning, or AI Radar business module.

## Naming

Public GitHub project name:

```text
llm-wiki-runtime
```

Skill package directory:

```text
llm-wiki-runtime
```

User-facing CLI:

```text
llm-wiki
```

Python entry file:

```text
llm_wiki.py
```

The implementation may still contain an internal core access layer, but the public project should use `llm-wiki-runtime`.

## Repository Placement

`llm-wiki-runtime` should be created as a top-level skill package:

```text
D:\tmp\github\role-copilot-skills\
  llm-wiki-runtime\
  hr-agent-copilot\
  devops-agent-copilot\
  project-agent-copilot\
```

This placement makes `llm-wiki-runtime` a horizontal foundation skill, peer to the domain skill groups.

`project-agent-copilot` is not a V0.1 migration target. It already has its own project-local wiki lifecycle and should be treated as a source of experience, not as a first integration target.

## V0.1 Goals

1. Each domain skill declares its own `llm-wiki-profile.yml`.
2. All reusable, valuable domain data is written into the corresponding domain `.llm-wiki`.
3. Each skill execution can load a domain context pack from `.llm-wiki` before generating answers.
4. `llm-wiki-runtime` does not interpret business semantics.
5. `llm-wiki-runtime` owns safe access, source registration, artifact registration, logs, checksums, and fallback status.
6. If `llm-wiki-runtime` is unavailable, disabled, or misconfigured, the domain skill keeps its original output behavior.

## Runtime Home, Scope, and Profile Model

V0.1 has two levels:

```text
LLM Wiki Home
  The runtime-level local root used to store shared domain scopes.

Domain Wiki Scope
  A concrete HR, DevOps, Learning, or AI Radar knowledge base.
```

On install or first use, `llm-wiki-runtime` should guide the user to choose an `LLM_WIKI_HOME`.

If the user does not choose one, platform defaults are:

```text
Windows: C:\Users\<user>\Documents\LLM Wiki
macOS:   ~/Documents/LLM Wiki
Linux:   ~/.local/share/llm-wiki-runtime
```

The runtime home may contain:

```text
LLM Wiki/
  config.yml
  scopes/
    hr-default/
      .llm-wiki/
    learning-default/
      .llm-wiki/
    ai-radar-default/
      .llm-wiki/
  logs/
```

The runtime config may also record profile-level declines so home-scope domains do not ask again from a different working directory:

```yaml
profiles:
  hr:
    default_storage_mode: home
    default_scope_id: hr-default
    enabled: false
    declined_at: 2026-07-06T10:30:00+08:00
```

`LLM_WIKI_HOME` is resolved in this order:

1. `LLM_WIKI_HOME` environment variable.
2. Runtime user config.
3. Platform default path.

Runtime user config locations:

```text
Windows: %APPDATA%\llm-wiki-runtime\config.yml
macOS:   ~/Library/Application Support/llm-wiki-runtime/config.yml
Linux:   ~/.config/llm-wiki-runtime/config.yml
```

V0.1 supports two storage modes:

```text
local
  wiki_root = scope_root / storage

home
  wiki_root = LLM_WIKI_HOME / scopes / scope_id / .llm-wiki
```

Local scope config:

```yaml
llm_wiki:
  enabled: true
  storage_mode: local
  storage: .llm-wiki
  primary_profile: hr
```

Home scope config:

```yaml
llm_wiki:
  enabled: true
  storage_mode: home
  scope_id: hr-default
  primary_profile: hr
```

For home scopes, the scope config lives at:

```text
LLM_WIKI_HOME/scopes/{scope_id}/.llm-wiki.yml
```

and the wiki root lives at:

```text
LLM_WIKI_HOME/scopes/{scope_id}/.llm-wiki
```

Default storage strategy by domain:

```text
hr        -> home
devops    -> local
learning  -> home
ai-radar  -> home
```

`resolve-config` discovers the active scope in this order:

1. Resolve `LLM_WIKI_HOME`.
2. If `--scope <path>` is provided, use that path as the local scope root unless its config says `storage_mode: home`.
3. Otherwise, walk upward from `--cwd` until a `.llm-wiki.yml` file is found.
4. If a local config is found, resolve `wiki_root` from its `storage_mode`.
5. If no local config is found, check runtime user config for a profile-level disable or decline record. If the requested profile is disabled, return `disabled`.
6. If no local config is found and the caller provides `--profile <id>` with a default home strategy, use the profile default home scope only if that home scope already has an initialized `.llm-wiki.yml`.
7. If the default home scope does not exist yet, return `missing_config` so the domain skill can ask the first-run enablement question.
8. If no config and no default home strategy applies, return `missing_config` with `scope_root` set to `--cwd`.

A profile-level decline in runtime user config applies only to the default home strategy. It must not disable an explicit local scope with its own `.llm-wiki.yml`.

Home scopes must not be silently created by `resolve-config`. They are created only through explicit first-run enablement, normally by calling `init-home` and `init-profile` after the user confirms.

Although domain paths use prefixes such as `domains/hr/...`, V0.1 still treats the scope as a single-primary-profile workspace. The prefix is used to make paths explicit and to leave room for future multi-profile support. V0.1 must not let HR write into a DevOps scope, or DevOps write into an HR scope.

Multi-profile coexistence in the same `.llm-wiki` is deferred. A future version may support explicit `profiles:` configuration, but V0.1 `profile_mismatch` means the current directory already belongs to another primary profile and the caller must fall back.

## First Integration Targets

Deep first-party integrations:

- `hr-agent-copilot`
- `devops-agent-copilot`

Light external-skill integration examples:

- `learning-companion-skills`
- `ai-radar-harness`

Not in V0.1:

- `project-agent-copilot`

## Core Principle

```text
domain owns the instructions;
core owns the access.

domain decides what is valuable;
core reliably stores it.

domain owns business meaning;
core owns filesystem and index trust.
```

`llm-wiki-runtime` enhances domain skills, but it must not become their single point of failure.

## Division of Responsibility

`llm-wiki-runtime` owns:

- `init-home`
- `resolve-config`
- `init-profile`
- `copy-source`
- `write-record`
- `load-context-pack`
- `register-artifact`
- `append-log`
- path-boundary checks
- checksum calculation and recording
- source registry writes
- artifact index writes
- append-only log writes
- deterministic fallback status

Domain skills own:

- `llm-wiki-profile.yml`
- deciding which data is valuable
- generating file content
- generating business IDs
- interpreting loaded context
- deciding how context affects business judgment
- user-facing confirmation wording
- business reports and conclusions

The agent shell, such as Codex or Claude Code, owns natural-language interaction, skill routing, and result presentation.

## V0.1 CLI Surface

The first public CLI surface should be:

```text
init-home
resolve-config
init-profile
copy-source
write-record
load-context-pack
register-artifact
append-log
```

`init-home` guides or records the runtime-level `LLM_WIKI_HOME`. It may be called by a domain skill during first-run enablement, but it should remain simple enough for direct developer use.

`safe-write` may exist internally, but domain skills should prefer `write-record`. `write-record` uses the active domain profile to resolve paths, write mode, required variables, required references, and artifact registration behavior.

All public commands return JSON on stdout and use exit codes consistently:

```text
0  success
1  user or configuration fallback, with status in JSON
2  validation error, such as unsafe path, missing var, or missing ref
3  IO or lock failure
4  unexpected internal error
```

Fallback states are represented in JSON, not by free-form stderr text. For example:

```json
{
  "status": "disabled",
  "enabled": false,
  "scope_root": "D:/work/hr-pool",
  "wiki_root": null,
  "primary_profile": null,
  "fallback_mode": "markdown"
}
```

`resolve-config` must return at least:

```json
{
  "status": "enabled",
  "enabled": true,
  "scope_root": "D:/work/hr-pool",
  "storage_mode": "home",
  "wiki_home": "C:/Users/alice/Documents/LLM Wiki",
  "wiki_root": "C:/Users/alice/Documents/LLM Wiki/scopes/hr-default/.llm-wiki",
  "scope_id": "hr-default",
  "primary_profile": "hr",
  "scope_type": "talent_pool",
  "privacy": "sensitive_local",
  "fallback_mode": "markdown"
}
```

`fallback_mode` is an advisory field consumed by the domain skill, not by `llm-wiki-runtime` business logic.

V0.1 values:

```text
markdown
  Continue the existing Markdown report or output behavior.

original_output
  Continue the skill's original non-wiki output behavior.

none
  No fallback is available; mainly for direct developer CLI commands.
```

HR V0.1 should use `markdown`. DevOps may use `original_output` or `markdown` depending on the existing skill behavior.

## Workspace Layout

The first `llm-wiki-runtime` workspace should contain only the generic access layer:

```text
llm-wiki-runtime/
  SKILL.md
  README.md

  bin/
    llm_wiki.py

  docs/
    contract.md
    cli.md
    profile-spec.md
    integration-guide.md
    fallback-behavior.md

  examples/
    hr/
      .llm-wiki.yml
      llm-wiki-profile.yml
    devops/
      llm-wiki-profile.yml
    learning/
      llm-wiki-profile.yml
    ai-radar/
      llm-wiki-profile.yml

  tests/
    fixtures/
      hr-profile/
      disabled-config/
      invalid-config/
    test_resolve_config.py
    test_write_record.py
    test_context_pack.py
```

The example profiles are examples only. The authoritative HR profile should live in the HR skill package, for example:

```text
hr-agent-copilot/
  hr-resume-screening-copilot/
    llm-wiki-profile.yml
```

## Profile Contract

Each domain skill declares its wiki access rules in `llm-wiki-profile.yml`.

The V0.1 profile shape has five sections:

```yaml
profile:
layout:
write_rules:
read_rules:
artifacts:
```

### profile

```yaml
profile:
  id: hr
  version: v0.1
  display_name: HR Talent Pool
  scope_type: talent_pool
  privacy_default: sensitive_local
```

`profile.id` is the domain ID. Examples include `hr`, `devops`, `learning`, and `ai-radar`.

### layout

```yaml
layout:
  directories:
    - domains/hr/candidates
    - domains/hr/resumes
    - domains/hr/jobs
    - domains/hr/screenings
    - sources/originals/hr
    - sources/extracts/hr
    - artifacts
    - logs
```

`llm-wiki-runtime` creates declared directories. It does not interpret their business meaning.

### write_rules

```yaml
write_rules:
  records:
    candidate_profile:
      path: domains/hr/candidates/{candidate_id}/profile.md
      mode: update_allowed
      required_vars:
        - candidate_id
      required_refs:
        - source_id
        - resume_version_id
      register_artifact: false

    screening_report:
      path: domains/hr/screenings/{job_id}/{run_id}/report.md
      mode: create_only
      required_vars:
        - job_id
        - run_id
      required_refs:
        - job_id
        - candidate_ids
      register_artifact: true
      artifact_type: screening_report
```

Supported write modes:

```text
create_only
update_allowed
append_only
```

`create_only` refuses to overwrite existing files. `update_allowed` permits controlled replacement. `append_only` is for logs and appendable records.

### read_rules

```yaml
read_rules:
  context_pack:
    include:
      - domains/hr/**
      - artifacts/**
      - logs/**
    exclude:
      - sources/originals/**
      - .meta/**
    max_files: 30
    max_chars_per_file: 4000
```

V0.1 context packs are deterministic. They do not require embedding, vector search, semantic ranking, or cross-domain search.

The context pack should return file paths, titles or headings when available, bounded content snippets, checksums, and metadata useful to the domain skill.

Core-managed metadata under `.meta/**` is excluded from context packs by default, even when a profile includes broad paths such as `logs/**`. A future explicit `--include-meta` option may expose it for maintenance commands, but business skills should not consume it by default.

`llm-wiki-runtime` creates `.llm-wiki/.meta/` during `init-profile` even if the domain profile does not declare it in `layout.directories`.

### artifacts

```yaml
artifacts:
  types:
    - screening_report
    - ranking
    - interview_plan
```

`llm-wiki-runtime` should reject artifact types that are not declared by the active profile.

## Safety and Consistency Rules

### Path Variable Safety

Path variables such as `{candidate_id}`, `{run_id}`, and `{image_id}` are data, not trusted paths.

Before rendering a path template, `llm-wiki-runtime` must validate every variable value:

- reject empty values
- reject `.` and `..`
- reject `/`, `\`, drive prefixes, colons, and path separators
- reject control characters
- reject values longer than a configured limit, default 128 characters
- require a conservative slug pattern for V0.1: `[A-Za-z0-9][A-Za-z0-9._-]*`

Human display names may remain in Markdown content. Path IDs must be safe slugs generated by the domain skill and enforced by `llm-wiki-runtime`.

After rendering the template, `llm-wiki-runtime` must normalize the path and verify that the final path stays under `wiki_root`.

### Required Reference Validation

`required_refs` are not just presence checks.

V0.1 should validate references that belong to core-owned registries:

- `source_id` must exist in `sources/registry.json`.
- `artifact_id` must exist in `artifacts/index.json`.
- `checksum` must match the referenced source or content when the command provides enough information to verify it.

Domain-owned references such as `candidate_ids`, `job_id`, or `run_id` are validated for type and non-empty value in V0.1. Their deeper business existence is owned by the domain skill unless the profile declares them as core-checkable references in a later version.

Reference values may be scalar strings or arrays. The profile may declare reference types later, but V0.1 at minimum must reject empty strings, empty arrays, and non-string array items.

### Atomic Writes and Locking

Any command that writes `.llm-wiki` must take an exclusive scope lock before modifying files.

Before acquiring the lock, `llm-wiki-runtime` may create the `.llm-wiki/.meta/` directory if it does not exist yet. This bootstrap directory creation is allowed so `init-profile` itself can be protected by the same lock.

The lock file is:

```text
.llm-wiki/.meta/lock.json
```

The lock file must include at least:

```json
{
  "pid": 12345,
  "host": "machine-name",
  "command": "write-record",
  "acquired_at": "2026-07-06T10:30:00+08:00"
}
```

Default lock behavior:

- Acquire the lock by atomic file creation, equivalent to `O_CREAT | O_EXCL`, so two processes cannot both win lock creation.
- Wait up to 30 seconds to acquire the lock.
- Return exit code `3` if the lock cannot be acquired within the timeout.
- Treat a lock as stale after 10 minutes.
- On the same host, if the recorded PID is no longer alive, the stale lock may be reclaimed.
- On a different or unknown host, a lock older than the stale threshold may be renamed to `.llm-wiki/.meta/lock.stale.{timestamp}.json` before acquiring a new lock.

The lock protects:

- profile initialization
- source registry writes
- artifact index writes
- append-only logs
- `write-record`
- `copy-source`

Writes to JSON registries and replaceable records must be atomic:

```text
write temp file in same directory
fsync when available
rename/replace atomically
```

Append-only logs should either be written under the same lock or appended through a temp-and-rename strategy when the platform cannot guarantee atomic append.

### update_allowed and Checksums

`update_allowed` does not mean untracked overwrite.

When `write-record` updates an existing file, `llm-wiki-runtime` must record:

- previous checksum
- new checksum
- timestamp
- command name
- record type
- logical path
- refs provided by the domain skill

V0.1 may store this revision entry in a core-managed change log such as:

```text
.llm-wiki/.meta/change-log.jsonl
```

The current file may be replaced, but the update must be auditable. `create_only` files remain immutable through CLI-routed writes.

### Context Pack Determinism

`load-context-pack` must be deterministic.

Default selection order:

1. Explicit `--path` or `--glob` filters provided by the caller.
2. Profile `read_rules.context_pack.include` and `exclude`.
3. Sort by path ascending.
4. If `--order mtime_desc` is explicitly provided, sort by modification time descending, then path ascending.
5. Apply `max_files` and `max_chars_per_file` after sorting.

The command should support caller filters:

```text
--path domains/hr/candidates/zhang-san/profile.md
--glob domains/hr/candidates/**
--record-type candidate_profile
--ref candidate_id=zhang-san
```

Filters can only narrow the profile read rules. They cannot expand access outside the active profile.

Domain integration guides should require business skills to pass narrowing filters whenever the user intent is specific, such as a candidate ID, job ID, release ID, topic ID, or date range. Broad profile reads are allowed for small scopes but should not be the default for targeted questions.

### Privacy Semantics

`privacy_default` is a domain default used during `init-profile`.

`llm-wiki-runtime` stores the resolved privacy level in `.llm-wiki.yml`. Runtime config overrides the profile default. In V0.1, privacy controls default user prompts and Git guidance, especially whether `.llm-wiki/` should be ignored by Git. It is not an encryption or access-control system.

### Decline Persistence

When the user declines first-run enablement, the domain skill asks the question, but `llm-wiki-runtime` should provide the deterministic write operation that creates the minimal disabled config:

```yaml
llm_wiki:
  enabled: false
```

This keeps the "do not ask again in this scope" behavior consistent across domains.

For `local` storage domains, the disabled config is written to the local scope root.

For `home` storage domains, the decline is written to runtime user config under that profile, not to the current working directory. This prevents HR, Learning, or AI Radar from asking again when the user runs the same skill from another folder.

### Deferred Compatibility Rules

Profile `version` compatibility and migration of old on-disk domain data are deferred beyond V0.1. V0.1 may reject unsupported profile versions with `invalid_config` rather than attempting migration.

## Domain Examples

### HR

Reusable HR data includes:

- candidate profiles
- resume versions
- JD records
- screening runs
- candidate-job match records
- risk signals
- interview focus records
- screening reports

HR owns candidate scoring, JD matching, report generation, ID strategy, and user-facing confirmation wording.

### DevOps

Reusable DevOps data includes:

- package runs
- build summaries
- image manifests
- release notes
- verification results
- deployment environment snapshots
- troubleshooting logs

DevOps owns packaging decisions, verification meaning, deployment interpretation, and release guidance.

### Learning

Reusable learning data includes:

- learner profile
- learning goals
- generated courses
- study sessions
- progress reviews
- learning logs

The learning skill owns coaching behavior, curriculum decisions, progress interpretation, and reminder tone.

### AI Radar

Reusable AI Radar data includes:

- signals
- sources
- evaluations
- reports
- trend logs

The radar skill owns signal judgment, topic clustering, evaluation criteria, and report writing.

## Fallback Behavior

`runtime_unavailable`:

- Domain skill runs normally.
- No wiki write is attempted.
- The result may mention that the wiki backend was not used.

`missing_config`:

- First-party domains may ask whether to enable `.llm-wiki`.
- If the user refuses in a `local` storage domain, write a minimal `.llm-wiki.yml` with `enabled: false`.
- If the user refuses in a `home` storage domain, record the profile-level decline in runtime user config.
- For home-scope domains, `missing_config` means the default home scope is not initialized yet; the runtime must not silently create it.
- External light integrations should not interrupt unless the user explicitly asks to enable wiki mode.

`disabled`:

- Do not ask again.
- Do not write `.llm-wiki`.
- Run original behavior.

`invalid_config`:

- Do not write `.llm-wiki`.
- Report the config issue.
- Continue the business output when possible.

`profile_mismatch`:

- Do not write across domains.
- Continue original output when possible.
- Report that the current directory is configured for a different profile.

## Acceptance Criteria

1. `llm-wiki-runtime` can be introduced as a top-level skill workspace in `role-copilot-skills`.
2. The V0.1 design does not require migrating `project-agent-copilot`.
3. HR and DevOps are the first deep integration targets.
4. Learning Companion and AI Radar can be documented as light external integration examples.
5. Domain skills provide their own `llm-wiki-profile.yml`.
6. `llm-wiki-runtime` can initialize a profile from a domain-provided manifest.
7. `write-record` writes only record types declared by the active profile.
8. `write-record` rejects missing required variables and required references.
9. `write-record` enforces `create_only`, `update_allowed`, and `append_only`.
10. `load-context-pack` reads only paths allowed by the active profile read rules.
11. `llm-wiki-runtime` unavailable, disabled, invalid, or mismatched states do not block the original domain skill output.
12. `safe-write` may exist internally, but domain integrations should use `write-record`.
13. `resolve-config` defines scope discovery, `wiki_root` resolution, and single-primary-profile behavior.
14. V0.1 rejects multi-profile writes unless the current primary profile matches the caller profile.
15. Path variables are validated before template rendering and normalized paths must remain under `wiki_root`.
16. Core-owned references such as `source_id` and `artifact_id` are validated against core registries.
17. Registry, artifact, log, source, and record writes are protected by a scope lock.
18. JSON registry and replaceable record writes are atomic.
19. `update_allowed` writes record revision metadata with previous and new checksums.
20. `load-context-pack` defines deterministic ordering and supports narrowing filters such as `--path`, `--glob`, `--record-type`, and `--ref`.
21. Public CLI commands return JSON and use documented exit codes.
22. `privacy_default` is defined as a prompt and Git-guidance default, not encryption or access control.
23. `init-home` supports a user-selected `LLM_WIKI_HOME` and platform default paths.
24. V0.1 supports both `local` and `home` storage modes.
25. HR, Learning, and AI Radar default to home scopes; DevOps defaults to local scope.
26. Home scopes are used by `resolve-config` only after they have been initialized; otherwise the command returns `missing_config`.
27. Declines for home-scope domains are stored in runtime user config, not in the current working directory.
28. `fallback_mode` has documented values and is advisory to domain skills.
29. Scope locks define timeout, stale-lock detection, and recovery behavior.
30. Core-managed `.meta/**` data is excluded from context packs by default.
31. Profile version compatibility and on-disk data migration are explicitly deferred beyond V0.1.
