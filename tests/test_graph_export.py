import json
from pathlib import Path

import pytest

from llm_wiki_runtime.audit import append_change_event
from llm_wiki_runtime.graph_export import export_graphs
from llm_wiki_runtime.locking import ScopeLock


def _scope(tmp_path: Path, domains=("hr",)) -> Path:
    scope_root = tmp_path / "scope"
    wiki_root = scope_root / ".llm-wiki"
    directories = "\n".join(f"    - domains/{domain}/records" for domain in domains)
    (wiki_root / ".meta").mkdir(parents=True)
    (wiki_root / ".meta/profile.yml").write_text(
        "\n".join(
            [
                "profile:",
                "  id: test",
                "  version: v0.1",
                "  display_name: Test scope",
                "layout:",
                "  directories:",
                directories,
                "write_rules:",
                "  records:",
                "read_rules:",
                "  context_pack:",
                "    include: [domains/**]",
                "    exclude: [.meta/**]",
                "    max_files: 30",
                "    max_chars_per_file: 4000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    for domain in domains:
        path = wiki_root / f"domains/{domain}/records/example.md"
        path.parent.mkdir(parents=True)
        path.write_text(f"---\ntitle: {domain} example\n---\nSee the local record.\n", encoding="utf-8")
    return scope_root


def test_append_change_event_sorts_and_sanitizes(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    append_change_event(
        wiki_root,
        {
            "event": "graph_export",
            "status": "ok",
            "domains": ["hr"],
            "body": "must not persist",
            "output_paths": [".meta/graph/index.html", r"C:\private\graph.html"],
        },
    )

    line = (wiki_root / ".meta/change-log.jsonl").read_text(encoding="utf-8")
    payload = json.loads(line)
    assert payload["event"] == "graph_export"
    assert "body" not in payload
    assert payload["output_paths"] == [".meta/graph/index.html"]
    assert line == json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def test_export_graphs_writes_index_manifest_report_and_domain_files(tmp_path):
    scope_root = _scope(tmp_path)

    result = export_graphs(scope_root)

    root = scope_root / ".llm-wiki/.meta/graph"
    assert result["status"] == "ok"
    assert (root / "index.html").is_file()
    assert (root / "graph-manifest.json").is_file()
    assert (root / "graph-export-report.json").is_file()
    assert (root / "hr/graph.html").is_file()
    assert (root / "hr/graph.json").is_file()
    manifest = json.loads((root / "graph-manifest.json").read_text(encoding="utf-8"))
    report = json.loads((root / "graph-export-report.json").read_text(encoding="utf-8"))
    assert manifest["scope_root"] == str(scope_root.resolve())
    assert str(scope_root.resolve()) not in (root / "index.html").read_text(encoding="utf-8")
    assert str(scope_root.resolve()) not in json.dumps(report)
    graph = json.loads((root / "hr/graph.json").read_text(encoding="utf-8"))
    assert graph["nodes"]
    assert all(edge["evidence"] for edge in graph["edges"])


def test_failed_domain_preserves_previous_success_and_continues_other_domains(tmp_path, monkeypatch):
    scope_root = _scope(tmp_path, ("hr", "ops"))
    first = export_graphs(scope_root)
    assert first["status"] == "ok"
    graph_root = scope_root / ".llm-wiki/.meta/graph"
    previous = (graph_root / "hr/graph.html").read_bytes()

    from llm_wiki_runtime import graph_export

    original = graph_export.collect_domain_nodes

    def fail_hr(wiki_root, profile, adapter, domain_id):
        if domain_id == "hr":
            raise ValueError("synthetic private path C:\\secret")
        return original(wiki_root, profile, adapter, domain_id)

    monkeypatch.setattr(graph_export, "collect_domain_nodes", fail_hr)
    result = export_graphs(scope_root)

    assert result["status"] == "partial_failure"
    assert result["domains"]["hr"]["errors"] == ["domain_validation_error"]
    assert result["domains"]["ops"]["status"] == "ok"
    assert (graph_root / "hr/graph.html").read_bytes() == previous
    assert "secret" not in (graph_root / "graph-export-report.json").read_text(encoding="utf-8")


def test_requested_unknown_domain_does_not_create_graph_output(tmp_path):
    scope_root = _scope(tmp_path)

    result = export_graphs(scope_root, requested_domain="missing")

    assert result["status"] == "validation_error"
    assert not (scope_root / ".llm-wiki/.meta/graph").exists()


def test_lock_contention_changes_no_graph_output(tmp_path):
    scope_root = _scope(tmp_path)
    wiki_root = scope_root / ".llm-wiki"

    with ScopeLock(wiki_root, command="test", timeout_seconds=1):
        with pytest.raises(TimeoutError):
            export_graphs(scope_root, lock_timeout_seconds=0)

    assert not (wiki_root / ".meta/graph").exists()


def test_orphaned_backup_is_restored_before_a_failed_attempt(tmp_path, monkeypatch):
    scope_root = _scope(tmp_path)
    assert export_graphs(scope_root)["status"] == "ok"
    graph_root = scope_root / ".llm-wiki/.meta/graph"
    final = graph_root / "hr"
    previous = (final / "graph.html").read_bytes()
    backup = graph_root / ".hr.backup-a1"
    final.rename(backup)
    staging = graph_root / ".hr.staging-b2"
    staging.mkdir()
    (staging / "partial").write_text("incomplete", encoding="utf-8")

    def fail(*args, **kwargs):
        raise ValueError("synthetic failure")

    monkeypatch.setattr("llm_wiki_runtime.graph_export.collect_domain_nodes", fail)
    result = export_graphs(scope_root)

    assert result["status"] == "validation_error"
    assert (final / "graph.html").read_bytes() == previous
    assert not backup.exists()
    assert not staging.exists()
