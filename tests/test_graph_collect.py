import json
from pathlib import Path

import pytest

from llm_wiki_runtime.graph_adapter import GraphAdapter, GraphFieldDefaults
from llm_wiki_runtime.models import LogRule, Profile, WriteRule


def _profile(*, directories=None, logs=None):
    return Profile(
        id="hr",
        version="v0.1",
        display_name="People scope",
        directories=directories or ["domains/hr/candidates"],
        write_rules={
            "candidate_profile": WriteRule(
                record_type="candidate_profile",
                path="domains/hr/candidates/{candidate_id}/profile.md",
                mode="update_allowed",
            )
        },
        log_rules=logs or {"events": LogRule("events", "logs/events.jsonl")},
    )


def _adapter():
    return GraphAdapter(
        version="v0.1",
        domain_id="hr",
        display_name="Human Resources",
        defaults=GraphFieldDefaults(
            label_field="candidate_id",
            subtype_field="record_type",
            summary_field="summary",
            status_field="status",
            tags_field="tags",
            metadata_allowlist=("education_level", "years_experience"),
        ),
        subtype_map={"candidate_profile": "candidate"},
    )


def _write(path: Path, contents: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def test_discover_domains_intersects_profile_roots_and_directories(tmp_path):
    from llm_wiki_runtime.graph_collect import discover_domains

    wiki_root = tmp_path / ".llm-wiki"
    (wiki_root / "domains/hr").mkdir(parents=True)
    (wiki_root / "domains/undeclared").mkdir(parents=True)
    profile = _profile(directories=["domains/hr/candidates", "domains/missing/items"])

    result = discover_domains(wiki_root, profile)

    assert result.domain_ids == ("hr",)
    assert [item.code for item in result.diagnostics] == [
        "declared_domain_missing",
        "undeclared_domain_directory",
    ]


def test_collect_nodes_classifies_records_documents_and_referenced_sources(tmp_path):
    from llm_wiki_runtime.graph_collect import collect_domain_nodes

    wiki_root = tmp_path / ".llm-wiki"
    _write(
        wiki_root / "domains/hr/candidates/c-1/profile.md",
        "---\ncandidate_id: c-1\nrecord_type: candidate_profile\nsummary: Approved\nstatus: active\ntags: [priority, internal]\nsource_id: src-1\n---\nResume body must remain available only to links.\n",
    )
    _write(wiki_root / "domains/hr/notes.md", "A document body.")
    _write(wiki_root / "sources/originals/hr/resume.pdf", "resume body")
    _write(
        wiki_root / "sources/registry.json",
        json.dumps({"sources": [{"source_id": "src-1", "source_type": "resume", "path": "sources/originals/hr/resume.pdf"}]}),
    )

    collected = collect_domain_nodes(wiki_root, _profile(), _adapter(), "hr")
    by_type = {node.type for node in collected.nodes}
    source = next(node for node in collected.nodes if node.type == "source")
    record = next(node for node in collected.nodes if node.type == "record")

    assert {"scope", "domain", "record", "document", "source", "log"} <= by_type
    assert source.path == "sources/originals/hr/resume.pdf"
    assert source.metadata == {}
    assert record.subtype == "candidate"
    assert record.label == "c-1"
    assert record.summary == "Approved"
    assert source.id in collected.identity_index["src-1"]
    assert "resume body" not in json.dumps([node.to_dict() for node in collected.nodes])


def test_collection_anchors_write_rules_and_requires_safe_single_segments(tmp_path):
    from llm_wiki_runtime.graph_collect import collect_domain_nodes

    wiki_root = tmp_path / ".llm-wiki"
    _write(wiki_root / "domains/hr/candidates/c-1/profile.md", "---\ncandidate_id: c-1\n---\n")
    _write(wiki_root / "domains/hr/candidates/c-1/profile-extra.md", "---\ncandidate_id: c-1\n---\n")
    _write(wiki_root / "domains/hr/candidates/c-1/other.md", "---\ncandidate_id: bad/value\n---\n")

    collected = collect_domain_nodes(wiki_root, _profile(), _adapter(), "hr")
    by_path = {node.path: node.type for node in collected.nodes}

    assert by_path["domains/hr/candidates/c-1/profile.md"] == "record"
    assert by_path["domains/hr/candidates/c-1/profile-extra.md"] == "document"
    assert by_path["domains/hr/candidates/c-1/other.md"] == "document"


def test_collection_uses_exact_adapter_fields_and_allowlisted_scalar_metadata(tmp_path):
    from llm_wiki_runtime.graph_collect import collect_domain_nodes

    wiki_root = tmp_path / ".llm-wiki"
    _write(
        wiki_root / "domains/hr/candidates/c-1/profile.md",
        "---\ncandidate_id: c-1\nCandidate_ID: private\nrecord_type: candidate_profile\nsummary: Exact summary\nstatus: active\ntags: [one, two]\neducation_level: masters\nyears_experience: 5\nemail: person@example.test\n---\nDo not use this body as a fallback label.\n",
    )

    collected = collect_domain_nodes(wiki_root, _profile(), _adapter(), "hr")
    record = next(node for node in collected.nodes if node.type == "record")

    assert record.label == "c-1"
    assert record.summary == "Exact summary"
    assert record.metadata == {"education_level": "masters", "years_experience": 5}
    assert "email" not in record.metadata


def test_malformed_and_nested_frontmatter_diagnostics_do_not_abort_collection(tmp_path):
    from llm_wiki_runtime.graph_collect import collect_domain_nodes

    wiki_root = tmp_path / ".llm-wiki"
    _write(wiki_root / "domains/hr/bad.md", "---\nname: [nested, [value]]\n---\n")
    _write(wiki_root / "domains/hr/good.md", "---\nrelated_ids: [same, same]\n---\n")

    collected = collect_domain_nodes(wiki_root, _profile(), _adapter(), "hr")

    assert any(item.code == "malformed_frontmatter" and item.path == "domains/hr/bad.md" for item in collected.diagnostics)
    assert any(node.path == "domains/hr/good.md" for node in collected.nodes)


def test_source_and_log_collection_never_reads_their_bodies(tmp_path, monkeypatch):
    from llm_wiki_runtime.graph_collect import collect_domain_nodes

    wiki_root = tmp_path / ".llm-wiki"
    _write(wiki_root / "domains/hr/reference.md", "---\nsource_id: src-1\n---\n")
    source_path = wiki_root / "sources/extracts/hr/resume.md"
    log_path = wiki_root / "logs/events.jsonl"
    _write(source_path, "secret source body")
    _write(log_path, '{"secret": "log body"}\n')
    _write(
        wiki_root / "sources/registry.json",
        json.dumps({"sources": [{"source_id": "src-1", "source_type": "resume", "path": "sources/extracts/hr/resume.md"}]}),
    )
    original_read_text = Path.read_text

    def guarded_read(path, *args, **kwargs):
        if path in {source_path, log_path}:
            raise AssertionError("source and log bodies must not be read")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    collected = collect_domain_nodes(wiki_root, _profile(), _adapter(), "hr")

    assert {node.type for node in collected.nodes} >= {"source", "log"}
    assert all("secret" not in json.dumps(node.to_dict()) for node in collected.nodes)


def test_artifacts_require_domain_except_one_domain_legacy_scope(tmp_path):
    from llm_wiki_runtime.graph_collect import collect_domain_nodes

    wiki_root = tmp_path / ".llm-wiki"
    (wiki_root / "domains/hr").mkdir(parents=True)
    entries = [
        {"artifact_id": "art-current", "artifact_type": "report", "domain": "hr", "path": "artifacts/current.md"},
        {"artifact_id": "art-legacy", "artifact_type": "report", "path": "artifacts/legacy.md"},
        {"artifact_id": "art-other", "artifact_type": "report", "domain": "ops", "path": "artifacts/other.md"},
    ]
    _write(wiki_root / "artifacts/index.json", json.dumps({"artifacts": entries}))

    collected = collect_domain_nodes(wiki_root, _profile(), _adapter(), "hr")
    artifacts = [node.label for node in collected.nodes if node.type == "artifact"]

    assert set(artifacts) == {"art-current", "art-legacy"}
    assert any(item.code == "legacy_artifact_domain_assumed" for item in collected.diagnostics)
    _write(wiki_root / "artifacts/index.json", json.dumps({"artifacts": list(reversed(entries))}))
    reordered = collect_domain_nodes(wiki_root, _profile(), _adapter(), "hr")
    assert [node.to_dict() for node in reordered.nodes] == [node.to_dict() for node in collected.nodes]


def test_duplicate_identity_is_preserved_and_collection_is_deterministic(tmp_path):
    from llm_wiki_runtime.graph_collect import collect_domain_nodes

    wiki_root = tmp_path / ".llm-wiki"
    _write(wiki_root / "domains/hr/z.md", "---\nrelated_id: duplicate\n---\n")
    _write(wiki_root / "domains/hr/a.md", "---\nrelated_id: duplicate\n---\n")

    first = collect_domain_nodes(wiki_root, _profile(), _adapter(), "hr")
    second = collect_domain_nodes(wiki_root, _profile(), _adapter(), "hr")

    assert len(first.identity_index["duplicate"]) == 2
    assert first.identity_index["duplicate"] == tuple(sorted(first.identity_index["duplicate"]))
    assert [node.to_dict() for node in first.nodes] == [node.to_dict() for node in second.nodes]
    assert [item.to_dict() for item in first.diagnostics] == [item.to_dict() for item in second.diagnostics]
    assert all(not Path(node.path).is_absolute() for node in first.nodes)
    assert all(not Path(item.path).is_absolute() for item in first.diagnostics if item.path)
