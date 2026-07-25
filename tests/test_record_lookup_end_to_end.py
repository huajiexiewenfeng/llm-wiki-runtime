from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from llm_wiki_runtime.runtime import init_profile, load_context_pack


def write_project_profile(path: Path) -> Path:
    profile = path / "project-profile.yml"
    profile.write_text(
        "\n".join(
            [
                "profile:",
                "  id: projects",
                "  version: v0.1",
                "layout:",
                "  directories:",
                "    - domains/projects",
                "write_rules:",
                "  records:",
                "    project_record:",
                "      path: domains/projects/{project_id}/profile.md",
                "      mode: update_allowed",
                "      required_vars: [project_id]",
                "      required_refs: []",
                "read_rules:",
                "  context_pack:",
                "    include: [domains/projects/**]",
                "    exclude: [.meta/**]",
                "    max_files: 30",
                "    max_chars_per_file: 4000",
                "  record_lookup:",
                "    project_record:",
                "      identity_field: project_id",
                "      display_field: display_name",
                "      match_fields: [display_name, aliases]",
                "      return_fields: [project_id, display_name, aliases]",
                "      max_results: 20",
            ]
        ),
        encoding="utf-8",
    )
    return profile


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "llm_wiki_runtime.cli", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_lookup_then_context_load_without_graph(tmp_path):
    profile = write_project_profile(tmp_path)
    init_profile(tmp_path, profile, "local", "project-test")
    wiki_root = tmp_path / ".llm-wiki"
    record = wiki_root / "domains/projects/project-001/profile.md"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(
        "\n".join(
            [
                "---",
                "record_type: project_record",
                "project_id: project-001",
                "display_name: Atlas",
                "aliases: [Atlas Platform]",
                "---",
                "",
                "Synthetic project details.",
            ]
        ),
        encoding="utf-8",
    )
    graph = wiki_root / ".meta/graph/projects/graph.html"
    graph.parent.mkdir(parents=True, exist_ok=True)
    graph.write_text("aggregate data", encoding="utf-8")

    lookup = run_cli(
        "find-records",
        "--scope-root",
        str(tmp_path),
        "--record-type",
        "project_record",
        "--lookup-value-json",
        json.dumps("Atlas"),
        "--caller-domain",
        "projects",
        "--target-domain",
        "projects",
    )
    lookup_payload = json.loads(lookup.stdout)

    assert lookup.returncode == 0
    assert lookup_payload["status"] == "found"
    returned_path = lookup_payload["matches"][0]["path"]
    context = load_context_pack(
        wiki_root,
        ["**"],
        [],
        30,
        4000,
        path_filters=[returned_path],
    )

    assert [item["path"] for item in context["items"]] == [returned_path]
    assert "Synthetic project details." in context["items"][0]["content"]
    assert all(".meta/graph" not in item["path"] for item in context["items"])


def test_cli_write_record_rejects_forbidden_control_without_changing_target(tmp_path):
    profile = write_project_profile(tmp_path)
    init_profile(tmp_path, profile, "local", "project-test")
    target = tmp_path / ".llm-wiki/domains/projects/project-001/profile.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("original", encoding="utf-8")
    content = tmp_path / "unsafe.md"
    content.write_text("unsafe\x00content", encoding="utf-8")

    result = run_cli(
        "write-record",
        "--scope-root",
        str(tmp_path),
        "--record-type",
        "project_record",
        "--variables-json",
        json.dumps({"project_id": "project-001"}),
        "--refs-json",
        "{}",
        "--content-file",
        str(content),
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["status"] == "validation_error"
    assert "forbidden control character" in payload["error"]
    assert target.read_text(encoding="utf-8") == "original"
