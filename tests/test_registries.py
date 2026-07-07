import json

from llm_wiki_runtime.runtime import append_log, copy_source, init_home, record_decline, register_artifact


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
