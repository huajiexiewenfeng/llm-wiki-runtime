import json
from pathlib import Path

from llm_wiki_runtime.ingest import prepare_excerpt, write_excerpt_snapshot
from llm_wiki_runtime.io import sha256_file
from llm_wiki_runtime.mapping import load_ingest_mapping, validate_ingest_mapping
from llm_wiki_runtime.profile import load_profile
from llm_wiki_runtime.runtime import (
    append_profile_log,
    copy_source,
    init_profile,
    load_context_pack,
    write_record,
)
from llm_wiki_runtime.scp import build_registry


FIXTURES = Path(__file__).parent / "fixtures"
PROFILE = FIXTURES / "hr-jd-profile.yml"
MAPPING = FIXTURES / "hr-jd-mapping.yml"
OWNER_SCP = FIXTURES / "hr-jd-owner.scp.yml"
THREAD_ITEMS = FIXTURES / "hr-jd-thread-items.json"
SELECTIONS = FIXTURES / "hr-jd-selections.json"


def test_hr_jd_flow_is_source_backed_queryable_and_idempotent(tmp_path):
    scope = tmp_path / "hr-scope"
    scope.mkdir()
    init_payload = init_profile(scope, PROFILE, "local", "hr-default")
    assert init_payload["status"] == "ok"

    registry = build_registry([OWNER_SCP])
    mapping = load_ingest_mapping(MAPPING)
    profile = load_profile(PROFILE)
    mapping_payload = validate_ingest_mapping(mapping, registry, profile)
    assert mapping_payload["status"] == "ok"

    items = json.loads(THREAD_ITEMS.read_text(encoding="utf-8"))
    selections = json.loads(SELECTIONS.read_text(encoding="utf-8"))
    excerpt = prepare_excerpt(items, selections, "jd", "2026-07-18T10:00:00+08:00")
    assert excerpt["risk_flags"] == []
    snapshot = tmp_path / "jd-snapshot.md"
    write_excerpt_snapshot(excerpt, snapshot)
    snapshot_text = snapshot.read_text(encoding="utf-8")

    job_id = "job-java-senior"
    version_id = excerpt["version_id"]
    wiki_root = scope / ".llm-wiki"
    logical_source = f"sources/originals/hr/jobs/{job_id}/{version_id}.md"
    first_copy = copy_source(
        wiki_root,
        snapshot,
        logical_source,
        "codex_thread_jd_excerpt",
        excerpt["metadata"],
    )
    assert first_copy["status"] == "ok"
    source_id = first_copy["source_id"]

    version_content = tmp_path / "jd-version.md"
    version_content.write_text(
        "\n".join(
            [
                "# Senior Java Developer",
                "",
                f"source_id: {source_id}",
                f"jd_version_id: {version_id}",
                "",
                "## Source-backed facts",
                excerpt["body"],
                "",
                "## Interpretation",
                "- Senior backend role using Java and Spring Boot.",
                "",
                "## Unknowns",
                "- Compensation and reporting line were not stated.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    first_version = write_record(
        scope,
        None,
        "jd_version",
        {"job_id": job_id, "jd_version_id": version_id},
        {"source_id": source_id},
        version_content,
    )
    assert first_version["status"] == "ok"

    profile_content = tmp_path / "job-profile.md"
    profile_content.write_text(
        "\n".join(
            [
                "# Senior Java Developer",
                "",
                f"job_id: {job_id}",
                f"source_id: {source_id}",
                "jd_versions:",
                f"- {version_id}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    first_profile = write_record(
        scope,
        None,
        "job_profile",
        {"job_id": job_id},
        {"source_id": source_id, "jd_version_id": version_id},
        profile_content,
    )
    assert first_profile["status"] == "ok"
    profile_path = scope / f".llm-wiki/domains/hr/jobs/{job_id}/profile.md"
    first_profile_checksum = sha256_file(profile_path)

    event_id = f"hr-jd-import:{source_id}:{job_id}:{version_id}"
    first_log = append_profile_log(
        scope,
        None,
        "hr_jd_import",
        {
            "event": "jd_imported",
            "event_id": event_id,
            "job_id": job_id,
            "jd_version_id": version_id,
            "source_id": source_id,
        },
    )
    assert first_log["status"] == "ok"

    second_copy = copy_source(
        wiki_root,
        snapshot,
        logical_source,
        "codex_thread_jd_excerpt",
        excerpt["metadata"],
    )
    second_version = write_record(
        scope,
        None,
        "jd_version",
        {"job_id": job_id, "jd_version_id": version_id},
        {"source_id": source_id},
        version_content,
    )
    if version_id not in profile_path.read_text(encoding="utf-8"):
        write_record(
            scope,
            None,
            "job_profile",
            {"job_id": job_id},
            {"source_id": source_id, "jd_version_id": version_id},
            profile_content,
        )
    second_log = append_profile_log(
        scope,
        None,
        "hr_jd_import",
        {"event": "jd_imported", "event_id": event_id},
    )

    context_payload = load_context_pack(
        wiki_root,
        profile.context_pack.include,
        profile.context_pack.exclude,
        profile.context_pack.max_files,
        profile.context_pack.max_chars_per_file,
        glob_filters=[f"domains/hr/jobs/{job_id}/**"],
    )
    source_registry = json.loads((wiki_root / "sources/registry.json").read_text(encoding="utf-8"))

    assert (scope / f".llm-wiki/domains/hr/jobs/{job_id}/profile.md").is_file()
    assert (scope / f".llm-wiki/domains/hr/jobs/{job_id}/versions/{version_id}.md").is_file()
    assert (scope / ".llm-wiki/logs/hr-jd-import.jsonl").is_file()
    assert len(source_registry["sources"]) == 1
    assert second_copy["status"] == "already_exists"
    assert second_version["status"] == "already_exists"
    assert second_log["status"] == "already_exists"
    assert sha256_file(profile_path) == first_profile_checksum
    log_lines = (scope / ".llm-wiki/logs/hr-jd-import.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 1
    assert context_payload["status"] == "ok"
    assert context_payload["items"]
    assert all("sources/originals" not in item["path"] for item in context_payload["items"])
    assert "test@example.com" not in snapshot_text
    assert "Candidate Zhang San" not in snapshot_text
