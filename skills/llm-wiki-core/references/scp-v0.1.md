# SCP v0.1 Reference

SCP means Skill Context Protocol in V0.1.

It declares how a domain skill participates in `.llm-wiki`:

- skill identity and domain
- runtime profile id
- fallback behavior
- trust level and instruction policy
- primary query domain
- supporting domains and record filters
- records, artifacts, and logs produced by ingest

## Rules

1. A domain skill declares meaning. It does not decide physical storage mode.
2. Runtime policy decides whether one domain can read another domain.
3. `readable_by` defaults to deny for cross-domain reads.
4. External or semi-trusted context should use `instruction_policy: data_only`.
5. Supporting context may enrich an answer, but it must not override primary domain facts.
6. V0.1 uses static SCP declarations. Runtime model-driven dynamic fetching is out of scope.

## Registry

Use `llm-wiki scan-scp --scp-path-json <json-array>` to build a registry from SCP files.

Optional arguments:

- `--domain-policies-json <json-object>` applies host read policy.
- `--caller-groups-json <json-object>` marks first-party skills or trusted groups.
- `--write` writes the registry to the runtime registry path.
- `--output <path>` writes the registry to a specific file.

The returned JSON always includes `status`, `warnings`, `next_actions`, and `context_refs`.

## Ingest Mapping

SCP declares the products a domain Skill is authorized to own. A domain-owned
`ingest-mapping.yml` selects a source adapter and narrows those products for one
ingest workflow. The active profile supplies the physical paths and write modes.

Runtime validation requires every mapping product to be both:

1. declared by the mapping's `owner_skill_id` SCP using the same contract kind,
2. declared by the active profile as a record, artifact, or append-only log.

The generic `llm-wiki-ingest` Skill executes this contract but does not own the
domain meaning. A missing mapping returns `domain_mapping_required`; a malformed
or inconsistent mapping returns `validation_error`. Neither state permits a raw
write into `.llm-wiki`.
