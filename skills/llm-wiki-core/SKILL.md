---
name: llm-wiki-core
description: Use when a user or first-party Skill requests LLM Wiki initialization, durable knowledge import, knowledge-backed answers, or Wiki health checks.
---

# LLM Wiki Core Router

This parent is a pure intent router. It reads and follows exactly one child skill
for each request and does not execute runtime commands itself.

| User intent | Child Skill |
| --- | --- |
| Initialize or enable a domain Wiki | `llm-wiki-init/SKILL.md` |
| Import durable files, task history, or results | `llm-wiki-ingest/SKILL.md` |
| Answer from an existing domain Wiki | `llm-wiki-query/SKILL.md` |
| Diagnose configuration, contracts, or health | `llm-wiki-maintain/SKILL.md` |

Choose the most specific intent. If two intents are equally plausible, ask one
short question before routing. Once selected, read the child completely and
follow it; do not combine child workflows in the same routing decision.

The parent owns no domain SCP, mapping, profile, or business meaning. It does
not write files and does not bypass `llm-wiki-runtime`.

Read `references/scp-v0.1.md` for the Skill Context Protocol and
`references/status-v0.1.md` for shared status behavior.
