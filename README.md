# llm-wiki-runtime

Local knowledge-base runtime and `.llm-wiki` access layer for AI skills and copilots.

V0.1 focuses on deterministic local CLI behavior: home/scope config, domain profiles, safe writes, registries, logs, and context packs.

## Development

```powershell
python -m pytest -q
python -m llm_wiki_runtime.cli version
```

## V0.1 Scope

- Runtime home and local/home scope resolution
- Domain profile manifests
- Safe record writes
- Source/artifact/log registries
- Deterministic context packs
