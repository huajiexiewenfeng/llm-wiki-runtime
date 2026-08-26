from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1] / "skills" / "llm-wiki-core"
CHILDREN = {
    "llm-wiki-init": "llm-wiki-init/SKILL.md",
    "llm-wiki-ingest": "llm-wiki-ingest/SKILL.md",
    "llm-wiki-query": "llm-wiki-query/SKILL.md",
    "llm-wiki-maintain": "llm-wiki-maintain/SKILL.md",
}


def read(relative: str) -> str:
    return (PACKAGE / relative).read_text(encoding="utf-8")


def test_parent_is_pure_router_and_routes_exactly_one_generic_child():
    text = read("SKILL.md")
    assert "exactly one child skill" in text.lower()
    assert "does not execute runtime commands" in text.lower()
    for relative in CHILDREN.values():
        assert relative in text


def test_each_child_has_discoverable_trigger_only_frontmatter():
    expected_triggers = {
        "llm-wiki-init": "initializing or enabling",
        "llm-wiki-ingest": "importing durable knowledge",
        "llm-wiki-query": "answering from an existing",
        "llm-wiki-maintain": "diagnosing or auditing",
    }
    for skill_id, relative in CHILDREN.items():
        text = read(relative)
        frontmatter = text.split("---", 2)[1]
        assert f"name: {skill_id}" in frontmatter
        assert "description: Use when" in frontmatter
        assert expected_triggers[skill_id] in frontmatter.lower()


def test_init_uses_dynamic_binding_without_modifying_scp():
    text = read(CHILDREN["llm-wiki-init"])
    assert "resolve-config" in text
    assert "init-home" in text
    assert "init-profile" in text
    assert "Do not modify any scp.yml" in text
    assert "missing_config" in text
    assert "disabled" in text


def test_init_requires_confirmation_before_installing_missing_runtime_from_github():
    text = read(CHILDREN["llm-wiki-init"])
    assert "llm-wiki version" in text
    assert "python -m pip install" in text
    assert "github.com/huajiexiewenfeng/llm-wiki-runtime" in text
    assert "confirmation" in text.lower()
    assert "do not install" in text.lower()
    assert "runtime_unavailable" in text


def test_ingest_requires_preview_before_any_write_and_is_retry_safe():
    text = read(CHILDREN["llm-wiki-ingest"])
    assert "validate-mapping" in text
    assert "prepare-excerpt" in text
    assert "Do not call any write command before the user confirms the preview" in text
    assert "copy-source" in text
    assert "write-record" in text
    assert "append-log" in text
    assert "hr-jd-import:{source_id}:{job_id}:{jd_version_id}" in text
    assert "already_exists" in text
    assert "domain_mapping_required" in text


def test_query_resolves_domain_and_uses_runtime_context_filters():
    text = read(CHILDREN["llm-wiki-query"])
    assert "explicit domain" in text.lower()
    assert "calling skill's scp" in text.lower()
    assert "find-records" in text
    assert "load-context-pack" in text
    assert "--path-json" in text
    assert "--glob-json" in text
    assert "multiple_matches" in text
    assert "never infer identity from graph output" in text.lower()
    assert "record lookup is not declared" in text.lower()
    assert "data_only" in text


def test_maintain_checks_contracts_without_semantic_repair():
    text = read(CHILDREN["llm-wiki-maintain"])
    assert "resolve-config" in text
    assert "scan-scp" in text
    assert "validate-mapping" in text
    assert "does not invent domain mappings" in text.lower()


def test_codex_thread_adapter_requires_stable_message_provenance_and_fallback():
    text = read("llm-wiki-ingest/references/codex-thread-source.md")
    for fragment in (
        "list_threads",
        "read_thread",
        "thread_id",
        "turn_id",
        "item_id",
        "start",
        "end",
        "oldest-to-newest",
        "Markdown or JSON export",
    ):
        assert fragment in text
    assert "Do not claim that a task was read" in text


def test_phase_one_skills_do_not_claim_person_context_views_or_raw_writes():
    combined = "\n".join(read(path) for path in CHILDREN.values())
    assert "person_core" not in combined
    assert "ambiguous_person" not in combined
    assert "Do not write directly inside .llm-wiki" in combined


def test_status_reference_publishes_principal_invocation_outcomes():
    text = read("references/status-v0.1.md")
    for status in (
        "principal_not_found",
        "principal_conflict",
        "principal_contract_stale",
        "principal_kind_unsupported",
        "principal_role_unsupported",
        "principal_domain_mismatch",
        "capability_denied",
        "mapping_owner_mismatch",
        "operation_not_allowed",
        "invalid_invocation",
    ):
        assert status in text
