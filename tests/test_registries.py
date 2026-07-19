import json

import pytest

from llm_wiki_runtime.runtime import (
    append_log,
    append_profile_log,
    copy_source,
    init_home,
    init_profile,
    record_decline,
    register_artifact,
)


def test_init_home_writes_runtime_config(tmp_path, monkeypatch):
    config = tmp_path / "config.yml"
    monkeypatch.setenv("LLM_WIKI_RUNTIME_CONFIG", str(config))
    payload = init_home(tmp_path / "LLM Wiki")
    assert payload["status"] == "ok"
    assert config.exists()
    assert "home:" in config.read_text(encoding="utf-8")


def test_record_decline_for_home_profile_writes_runtime_config(tmp_path, monkeypatch):
    config = tmp_path / "config.yml"
    monkeypatch.setenv("LLM_WIKI_RUNTIME_CONFIG", str(config))
    payload = record_decline(profile="hr", storage_mode="home", scope_root=tmp_path)
    assert payload["status"] == "disabled"
    text = config.read_text(encoding="utf-8")
    assert "hr:" in text
    assert "enabled: false" in text


def test_runtime_config_merges_home_and_multiple_profile_declines(tmp_path, monkeypatch):
    config = tmp_path / "config.yml"
    monkeypatch.setenv("LLM_WIKI_RUNTIME_CONFIG", str(config))
    home = tmp_path / "LLM Wiki"
    init_home(home)
    record_decline(profile="learning", storage_mode="home", scope_root=tmp_path)
    record_decline(profile="hr", storage_mode="home", scope_root=tmp_path)
    text = config.read_text(encoding="utf-8")
    assert f"home: {home}" in text
    assert "learning:" in text
    assert "hr:" in text
    assert text.count("enabled: false") == 2


def test_record_decline_for_local_profile_writes_scope_config(tmp_path):
    payload = record_decline(profile="devops", storage_mode="local", scope_root=tmp_path)
    assert payload["status"] == "disabled"
    assert (tmp_path / ".llm-wiki.yml").exists()
    assert "enabled: false" in (tmp_path / ".llm-wiki.yml").read_text(encoding="utf-8")


def test_copy_source_copies_file_and_registers_source(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    source = tmp_path / "resume.pdf"
    source.write_bytes(b"resume")
    payload = copy_source(wiki_root, source, "sources/originals/hr/resumes/zhang-san/resume.pdf", "resume_pdf")
    assert payload["status"] == "ok"
    assert payload["source_id"]
    registry = json.loads((wiki_root / "sources" / "registry.json").read_text(encoding="utf-8"))
    assert registry["sources"][0]["source_id"] == payload["source_id"]


def excerpt_metadata():
    return {
        "excerpted": True,
        "thread_id": "thread-1",
        "selections": [
            {
                "turn_id": "turn-1",
                "item_id": "item-1",
                "start": 0,
                "end": 21,
                "original_message_checksum": "sha256:abc123",
            }
        ],
        "confirmed_at": "2026-07-18T10:00:00+08:00",
    }


def test_copy_source_registers_controlled_provenance_metadata(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    source = tmp_path / "jd.md"
    source.write_text("Senior Java Developer", encoding="utf-8")
    metadata = excerpt_metadata()

    payload = copy_source(
        wiki_root,
        source,
        "sources/originals/hr/jobs/job-1/jd-1.md",
        "codex_thread_jd_excerpt",
        metadata,
    )

    registry = json.loads((wiki_root / "sources/registry.json").read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert registry["sources"][0]["metadata"] == metadata


def test_copy_source_is_idempotent_by_checksum_and_logical_path(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    source = tmp_path / "jd.md"
    source.write_text("Senior Java Developer", encoding="utf-8")
    logical_path = "sources/originals/hr/jobs/jd.md"

    first = copy_source(wiki_root, source, logical_path, "jd")
    second = copy_source(wiki_root, source, logical_path, "jd")

    registry = json.loads((wiki_root / "sources/registry.json").read_text(encoding="utf-8"))
    assert first["source_id"] == second["source_id"]
    assert second["status"] == "already_exists"
    assert len(registry["sources"]) == 1


def test_copy_source_refuses_different_content_at_existing_logical_path(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    source = tmp_path / "jd.md"
    logical_path = "sources/originals/hr/jobs/jd.md"
    source.write_text("JD version one", encoding="utf-8")
    copy_source(wiki_root, source, logical_path, "jd")

    source.write_text("JD version two", encoding="utf-8")
    with pytest.raises(FileExistsError, match="source target already exists"):
        copy_source(wiki_root, source, logical_path, "jd")

    assert (wiki_root / logical_path).read_text(encoding="utf-8") == "JD version one"


def test_copy_source_recovers_missing_registry_entry_for_matching_target(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    target = wiki_root / "sources/originals/hr/jobs/jd.md"
    target.parent.mkdir(parents=True)
    target.write_text("Senior Java Developer", encoding="utf-8")
    source = tmp_path / "jd.md"
    source.write_text("Senior Java Developer", encoding="utf-8")

    payload = copy_source(wiki_root, source, "sources/originals/hr/jobs/jd.md", "jd")

    registry = json.loads((wiki_root / "sources/registry.json").read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert len(registry["sources"]) == 1


def test_copy_source_rejects_incomplete_excerpt_metadata(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    source = tmp_path / "jd.md"
    source.write_text("Senior Java Developer", encoding="utf-8")

    with pytest.raises(ValueError, match="excerpt metadata requires thread_id and selections"):
        copy_source(
            wiki_root,
            source,
            "sources/originals/hr/jobs/jd.md",
            "codex_thread_jd_excerpt",
            {"excerpted": True},
        )


def test_copy_source_rejects_unsupported_metadata_field(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    source = tmp_path / "jd.md"
    source.write_text("Senior Java Developer", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported source metadata fields"):
        copy_source(
            wiki_root,
            source,
            "sources/originals/hr/jobs/jd.md",
            "codex_thread_jd_excerpt",
            {"unexpected": "value"},
        )


def test_register_artifact_updates_index(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    payload = register_artifact(
        wiki_root,
        {"artifact_id": "art-001", "artifact_type": "screening_report", "path": "domains/hr/report.md"},
    )
    assert payload["status"] == "ok"
    index = json.loads((wiki_root / "artifacts" / "index.json").read_text(encoding="utf-8"))
    assert index["artifacts"][0]["artifact_id"] == "art-001"


def test_append_log_appends_jsonl(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    payload = append_log(wiki_root, "logs/hr-screening-log.jsonl", {"event": "screening_started"})
    assert payload["status"] == "ok"
    text = (wiki_root / "logs" / "hr-screening-log.jsonl").read_text(encoding="utf-8")
    assert "screening_started" in text


def write_log_profile(path):
    path.write_text(
        "\n".join(
            [
                "profile:",
                "  id: hr",
                "  version: v0.1",
                "layout:",
                "  directories:",
                "    - logs",
                "logs:",
                "  types:",
                "    hr_jd_import:",
                "      path: logs/hr-jd-import.jsonl",
                "      mode: append_only",
            ]
        ),
        encoding="utf-8",
    )


def test_append_profile_log_uses_contract_and_deduplicates_event_id(tmp_path):
    profile = tmp_path / "hr-profile.yml"
    write_log_profile(profile)
    init_profile(tmp_path, profile, "local", "hr-test")
    record = {
        "event": "jd_imported",
        "event_id": "hr-jd-import:src-1:job-1:jd-1",
    }

    first = append_profile_log(tmp_path, None, "hr_jd_import", record)
    duplicate = append_profile_log(tmp_path, None, "hr_jd_import", record)

    assert first["status"] == "ok"
    assert first["log_type"] == "hr_jd_import"
    assert duplicate["status"] == "already_exists"
    lines = (tmp_path / ".llm-wiki/logs/hr-jd-import.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "jd_imported" in lines[0]


def test_append_profile_log_rejects_undeclared_type(tmp_path):
    profile = tmp_path / "hr-profile.yml"
    profile.write_text("profile:\n  id: hr\n  version: v0.1\n", encoding="utf-8")
    init_profile(tmp_path, profile, "local", "hr-test")

    with pytest.raises(ValueError, match="undeclared log type"):
        append_profile_log(tmp_path, None, "hr_jd_import", {"event": "jd_imported"})


@pytest.mark.parametrize("event_id", ["", 123])
def test_append_profile_log_rejects_invalid_event_id(tmp_path, event_id):
    profile = tmp_path / "hr-profile.yml"
    write_log_profile(profile)
    init_profile(tmp_path, profile, "local", "hr-test")

    with pytest.raises(ValueError, match="event_id must be a non-empty string"):
        append_profile_log(tmp_path, None, "hr_jd_import", {"event_id": event_id})
