from pathlib import Path

import pytest

from llm_wiki_runtime.record_lookup import find_records
from llm_wiki_runtime.runtime import init_profile


def write_project_profile(path: Path, max_results: int = 2) -> Path:
    profile = path / "profile.yml"
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
                "    include: [domains/projects/**, sources/originals/**, .meta/**]",
                "    exclude: [sources/originals/**, .meta/**]",
                "  record_lookup:",
                "    project_record:",
                "      identity_field: project_id",
                "      display_field: display_name",
                "      match_fields: [display_name, aliases]",
                "      return_fields: [project_id, display_name, aliases, status]",
                f"      max_results: {max_results}",
            ]
        ),
        encoding="utf-8",
    )
    return profile


def write_project_record(
    wiki_root: Path,
    project_id: str,
    display_name: str,
    aliases: str,
    *,
    body: str = "# Project\n",
    private_note: str = "internal-only",
) -> Path:
    path = wiki_root / f"domains/projects/{project_id}/profile.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                "record_type: project_record",
                f"project_id: {project_id}",
                f'display_name: "{display_name}"',
                f"aliases: [{aliases}]",
                "status: active",
                f"private_note: {private_note}",
                "---",
                body,
            ]
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def project_scope(tmp_path):
    profile = write_project_profile(tmp_path)
    init_profile(tmp_path, profile, "local", "projects-test")
    wiki_root = tmp_path / ".llm-wiki"
    write_project_record(wiki_root, "project-001", "Atlas", '"Atlas Platform"')
    write_project_record(wiki_root, "project-002", "Café", '"Café Platform"')
    for suffix in ("003", "004", "005"):
        write_project_record(wiki_root, f"project-{suffix}", "Shared", "")
    return tmp_path


def test_find_records_matches_display_name_and_returns_allowlisted_fields(project_scope):
    payload = find_records(
        project_scope,
        "project_record",
        "Atlas",
        caller_domain="projects",
        target_domain="projects",
    )

    assert payload["status"] == "found"
    assert payload["truncated"] is False
    assert payload["lookup_value"] == "Atlas"
    assert payload["matches"][0]["path"] == "domains/projects/project-001/profile.md"
    assert payload["matches"][0]["identity"] == "project-001"
    assert payload["matches"][0]["display"] == "Atlas"
    assert payload["matches"][0]["fields"] == {
        "project_id": "project-001",
        "display_name": "Atlas",
        "aliases": ["Atlas Platform"],
        "status": "active",
    }
    assert payload["context_refs"] == [
        {
            "path": payload["matches"][0]["path"],
            "checksum": payload["matches"][0]["checksum"],
        }
    ]


def test_find_records_matches_alias_with_unicode_nfc(project_scope):
    payload = find_records(
        project_scope,
        "project_record",
        "Café Platform",
        caller_domain="projects",
        target_domain="projects",
    )

    assert payload["status"] == "found"
    assert payload["matches"][0]["display"] == "Café"


def test_find_records_returns_multiple_matches_in_path_order_and_truncates(project_scope):
    payload = find_records(
        project_scope,
        "project_record",
        "Shared",
        caller_domain="projects",
        target_domain="projects",
    )

    assert payload["status"] == "multiple_matches"
    assert payload["truncated"] is True
    assert [match["path"] for match in payload["matches"]] == [
        "domains/projects/project-003/profile.md",
        "domains/projects/project-004/profile.md",
    ]


def test_find_records_is_case_sensitive_and_does_not_search_body(project_scope):
    wiki_root = project_scope / ".llm-wiki"
    write_project_record(
        wiki_root,
        "project-body",
        "Other",
        "",
        body="Atlas",
    )

    lowercase = find_records(project_scope, "project_record", "atlas")
    exact = find_records(project_scope, "project_record", "Atlas")

    assert lowercase["status"] == "not_found"
    assert [match["identity"] for match in exact["matches"]] == ["project-001"]


def test_find_records_uses_strict_scalar_types(project_scope):
    wiki_root = project_scope / ".llm-wiki"
    write_project_record(wiki_root, "project-number", "Numeric", "3")

    number = find_records(project_scope, "project_record", 3)
    text = find_records(project_scope, "project_record", "3")

    assert number["status"] == "found"
    assert text["status"] == "not_found"


def test_find_records_denies_cross_domain_without_returning_metadata(project_scope):
    payload = find_records(
        project_scope,
        "project_record",
        "Atlas",
        caller_domain="learning",
        target_domain="projects",
        domain_policies={"projects": {"readable_by": []}},
    )

    assert payload == {
        "status": "read_denied",
        "reason": "domain_not_readable_by_caller",
        "record_type": "project_record",
        "matches": [],
        "context_refs": [],
        "warnings": [],
        "truncated": False,
    }


def test_find_records_skips_forced_and_profile_excluded_paths(project_scope):
    wiki_root = project_scope / ".llm-wiki"
    for relative in (
        ".meta/private.md",
        "sources/originals/private.md",
    ):
        path = wiki_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\nrecord_type: project_record\nproject_id: excluded\n"
            'display_name: "Excluded"\naliases: []\nstatus: active\n---\n',
            encoding="utf-8",
        )

    payload = find_records(project_scope, "project_record", "Excluded")

    assert payload["status"] == "not_found"


def test_find_records_reports_stable_frontmatter_warnings(project_scope):
    wiki_root = project_scope / ".llm-wiki"
    invalid = wiki_root / "domains/projects/invalid/profile.md"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("---\nowner:\n  name: Nested\n---\n", encoding="utf-8")
    unclosed = wiki_root / "domains/projects/unclosed/profile.md"
    unclosed.parent.mkdir(parents=True)
    unclosed.write_text("---\nrecord_type: project_record\n", encoding="utf-8")
    oversized = wiki_root / "domains/projects/oversized/profile.md"
    oversized.parent.mkdir(parents=True)
    oversized.write_text(
        "---\nrecord_type: project_record\nsummary: " + ("x" * (64 * 1024)) + "\n---\n",
        encoding="utf-8",
    )

    payload = find_records(project_scope, "project_record", "Atlas")

    assert payload["status"] == "found"
    assert payload["warnings"] == [
        {
            "code": "frontmatter_invalid",
            "path": "domains/projects/invalid/profile.md",
        },
        {
            "code": "frontmatter_too_large",
            "path": "domains/projects/oversized/profile.md",
        },
        {
            "code": "frontmatter_missing_closing_delimiter",
            "path": "domains/projects/unclosed/profile.md",
        },
    ]


def test_find_records_legacy_nul_body_does_not_affect_frontmatter_lookup(project_scope):
    wiki_root = project_scope / ".llm-wiki"
    path = write_project_record(
        wiki_root,
        "project-legacy",
        "Legacy",
        "",
        body="body\x00text",
    )
    assert "\x00" in path.read_text(encoding="utf-8")

    payload = find_records(project_scope, "project_record", "Legacy")

    assert payload["status"] == "found"
    assert payload["matches"][0]["identity"] == "project-legacy"
    assert not (wiki_root / ".meta/graph").exists()


def test_find_records_rejects_missing_lookup_declaration(tmp_path):
    profile = write_project_profile(tmp_path)
    text = profile.read_text(encoding="utf-8")
    profile.write_text(text.split("  record_lookup:", 1)[0], encoding="utf-8")
    init_profile(tmp_path, profile, "local", "projects-test")

    with pytest.raises(ValueError, match="record lookup is not declared"):
        find_records(tmp_path, "project_record", "Atlas")
