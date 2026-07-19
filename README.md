# llm-wiki-runtime

Local knowledge-base runtime and `.llm-wiki` access layer for AI skills and copilots.

V0.1 focuses on deterministic local CLI behavior: home/scope config, domain profiles, safe writes, registries, logs, and context packs.

## Development

```powershell
python -m pytest -q
python -m llm_wiki_runtime.cli version
python -m llm_wiki_runtime.cli scan-scp --scp-path-json '["examples/scp/hr-resume-screening.scp.yml"]'
```

## V0.1 Scope

- Runtime home and local/home scope resolution
- Domain profile manifests
- Safe record writes
- Source/artifact/log registries
- Deterministic context packs
- SCP registry generation
- Cross-domain read policy
- `data_only` context isolation for external supporting domains

## llm-wiki-core Skill

The `skills/llm-wiki-core` folder contains the agent-shell orchestration skill for V0.1.

`llm-wiki-runtime` remains the deterministic CLI layer. `llm-wiki-core` interprets SCP, calls the CLI, and handles user-facing fallback behavior.

## Guides

- `docs/guides/domain-skill-integration-quickstart.zh.md`
- `docs/guides/hr-llm-wiki-integration.zh.md`
- `docs/guides/hr-skill-llm-wiki-runtime-implementation.zh.md`
- `docs/guides/learning-llm-wiki-integration.zh.md`

## Examples

- `examples/hr/llm-wiki-profile.yml`
- `examples/devops/llm-wiki-profile.yml`
- `examples/scp/hr-resume-screening.scp.yml`
- `examples/scp/learning-companion.scp.yml`
- `examples/scp/ai-radar.scp.yml`
- `examples/policies/domain-policies.v0.1.json`
