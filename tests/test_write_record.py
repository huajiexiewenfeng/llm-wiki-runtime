from pathlib import Path

import pytest

from llm_wiki_runtime.runtime import copy_source, init_profile, load_context_pack, write_record


def write_profile(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "profile:",
                "  id: hr",
                "  version: v0.1",
                "layout:",
                "  directories:",
                "    - domains/hr/candidates",
                "write_rules:",
                "  records:",
                "    candidate_profile:",
                "      path: domains/hr/candidates/{candidate_id}/profile.md",
                "      mode: update_allowed",
                "      required_vars: [candidate_id]",
                "      required_refs: [source_id]",
                "    screening_report:",
                "      path: domains/hr/screenings/{run_id}/report.md",
                "      mode: create_only",
                "      required_vars: [run_id]",
                "      required_refs: []",
                "    screening_log:",
                "      path: logs/hr-screening-log.jsonl",
                "      mode: append_only",
                "      required_vars: []",
                "      required_refs: []",
                "read_rules:",
                "  context_pack:",
                "    include: [domains/hr/**, logs/**]",
                "    exclude: [.meta/**]",
                "    max_files: 30",
                "    max_chars_per_file: 4000",
                "artifacts:",
                "  types: [screening_report]",
            ]
        ),
        encoding="utf-8",
    )


def test_write_record_create_only_refuses_overwrite_and_returns_existing(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    profile = tmp_path / "llm-wiki-profile.yml"
    write_profile(profile)
    content = tmp_path / "content.md"
    content.write_text("first", encoding="utf-8")
    first = write_record(tmp_path, profile, "screening_report", {"run_id": "run-001"}, {}, content)
    content.write_text("second", encoding="utf-8")
    duplicate = write_record(tmp_path, profile, "screening_report", {"run_id": "run-001"}, {}, content)

    assert first["status"] == "ok"
    assert duplicate["status"] == "already_exists"
    assert duplicate["checksum"] == first["checksum"]
    target = wiki_root / "domains/hr/screenings/run-001/report.md"
    assert target.read_text(encoding="utf-8") == "first"


def test_write_record_uses_scope_profile_snapshot_when_profile_path_missing(tmp_path):
    profile = tmp_path / "llm-wiki-profile.yml"
    write_profile(profile)
    init_profile(tmp_path, profile, "local", "hr-default")

    wiki_root = tmp_path / ".llm-wiki"
    source = tmp_path / "resume.pdf"
    source.write_bytes(b"resume")
    source_payload = copy_source(wiki_root, source, "sources/originals/hr/resume.pdf", "resume_pdf")

    content = tmp_path / "profile.md"
    content.write_text("candidate profile", encoding="utf-8")

    payload = write_record(
        tmp_path,
        None,
        "candidate_profile",
        {"candidate_id": "zhang-san"},
        {"source_id": source_payload["source_id"]},
        content,
    )

    assert payload["status"] == "ok"
    assert payload["path"] == "domains/hr/candidates/zhang-san/profile.md"


def test_write_record_update_allowed_records_meta_change_log(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    profile = tmp_path / "llm-wiki-profile.yml"
    write_profile(profile)
    source = tmp_path / "resume.pdf"
    source.write_bytes(b"resume")
    source_payload = copy_source(wiki_root, source, "sources/originals/hr/resume.pdf", "resume_pdf")
    content = tmp_path / "profile.md"
    content.write_text("first", encoding="utf-8")
    write_record(tmp_path, profile, "candidate_profile", {"candidate_id": "zhang-san"}, {"source_id": source_payload["source_id"]}, content)
    content.write_text("second", encoding="utf-8")
    write_record(tmp_path, profile, "candidate_profile", {"candidate_id": "zhang-san"}, {"source_id": source_payload["source_id"]}, content)
    change_log = wiki_root / ".meta" / "change-log.jsonl"
    assert change_log.exists()
    assert "candidate_profile" in change_log.read_text(encoding="utf-8")


def test_write_record_rejects_missing_source_ref(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    profile = tmp_path / "llm-wiki-profile.yml"
    write_profile(profile)
    content = tmp_path / "profile.md"
    content.write_text("first", encoding="utf-8")
    with pytest.raises(ValueError):
        write_record(tmp_path, profile, "candidate_profile", {"candidate_id": "zhang-san"}, {"source_id": "src-missing"}, content)


def test_write_record_append_only_appends(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    profile = tmp_path / "llm-wiki-profile.yml"
    write_profile(profile)
    content = tmp_path / "log.md"
    content.write_text("first\n", encoding="utf-8")
    write_record(tmp_path, profile, "screening_log", {}, {}, content)
    content.write_text("second\n", encoding="utf-8")
    write_record(tmp_path, profile, "screening_log", {}, {}, content)
    assert (wiki_root / "logs" / "hr-screening-log.jsonl").read_text(encoding="utf-8") == "first\nsecond\n"


def test_write_record_registers_artifact_without_reentrant_lock(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    profile = tmp_path / "llm-wiki-profile.yml"
    profile.write_text(
        "\n".join(
            [
                "profile:",
                "  id: devops",
                "  version: v0.1",
                "write_rules:",
                "  records:",
                "    package_run:",
                "      path: domains/devops/package-runs/{run_id}/summary.md",
                "      mode: create_only",
                "      required_vars: [run_id]",
                "      required_refs: []",
                "      register_artifact: true",
                "      artifact_type: package_run",
                "read_rules:",
                "  context_pack:",
                "    include: [domains/devops/**]",
                "    exclude: [.meta/**]",
                "artifacts:",
                "  types: [package_run]",
            ]
        ),
        encoding="utf-8",
    )
    content = tmp_path / "summary.md"
    content.write_text("packaged", encoding="utf-8")
    payload = write_record(tmp_path, profile, "package_run", {"run_id": "run-001"}, {}, content)
    assert payload["status"] == "ok"
    index = (wiki_root / "artifacts" / "index.json").read_text(encoding="utf-8")
    assert "package_run" in index


def test_context_pack_excludes_meta_and_sorts_by_path(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    (wiki_root / "domains/hr/b").mkdir(parents=True)
    (wiki_root / "domains/hr/a").mkdir(parents=True)
    (wiki_root / ".meta").mkdir(parents=True)
    (wiki_root / "domains/hr/b/file.md").write_text("b", encoding="utf-8")
    (wiki_root / "domains/hr/a/file.md").write_text("a", encoding="utf-8")
    (wiki_root / ".meta/change-log.jsonl").write_text("secret", encoding="utf-8")
    payload = load_context_pack(wiki_root, ["domains/hr/**", ".meta/**"], [".meta/**"], 30, 4000)
    paths = [item["path"] for item in payload["items"]]
    assert paths == ["domains/hr/a/file.md", "domains/hr/b/file.md"]
