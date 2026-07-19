import json
import subprocess
import sys


def test_cli_help_module_imports():
    result = subprocess.run(
        [sys.executable, "-m", "llm_wiki_runtime.cli", "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "llm-wiki" in result.stdout


def test_cli_version_outputs_json():
    result = subprocess.run(
        [sys.executable, "-m", "llm_wiki_runtime.cli", "version"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["version"]


def test_cli_version_includes_standard_response_fields():
    result = subprocess.run(
        [sys.executable, "-m", "llm_wiki_runtime.cli", "version"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["warnings"] == []
    assert payload["next_actions"] == []
    assert payload["context_refs"] == []


def test_cli_validation_error_includes_standard_response_fields():
    result = subprocess.run(
        [sys.executable, "-m", "llm_wiki_runtime.cli", "init-profile", "--scope-root", "."],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "validation_error"
    assert "error" in payload
    assert payload["warnings"] == []
    assert payload["next_actions"]
    assert payload["context_refs"] == []


def test_cli_scan_scp_outputs_registry(tmp_path):
    scp = tmp_path / "ai.scp.yml"
    scp.write_text(
        "\n".join(
            [
                "scp_version: v0.1",
                "skill:",
                "  id: ai-radar-newsroom",
                "  domain: ai-radar",
                "llm_wiki:",
                "  profile: ai-radar",
                "query:",
                "  primary_domain: ai-radar",
                "  supports: []",
                "ingest:",
                "  produces:",
                "    - domain: ai-radar",
                "      record_type: tool_trend",
            ]
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_wiki_runtime.cli",
            "scan-scp",
            "--scp-path-json",
            json.dumps([str(scp)]),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["skills"]["ai-radar-newsroom"]["domain"] == "ai-radar"


def test_cli_append_profile_log_is_idempotent(tmp_path):
    profile = tmp_path / "hr-profile.yml"
    profile.write_text(
        "\n".join(
            [
                "profile:",
                "  id: hr",
                "  version: v0.1",
                "logs:",
                "  types:",
                "    hr_jd_import:",
                "      path: logs/hr-jd-import.jsonl",
                "      mode: append_only",
            ]
        ),
        encoding="utf-8",
    )
    init_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_wiki_runtime.cli",
            "init-profile",
            "--scope-root",
            str(tmp_path),
            "--profile-path",
            str(profile),
            "--scope-id",
            "hr-test",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert init_result.returncode == 0

    command = [
        sys.executable,
        "-m",
        "llm_wiki_runtime.cli",
        "append-log",
        "--scope-root",
        str(tmp_path),
        "--log-type",
        "hr_jd_import",
        "--record-json",
        json.dumps({"event": "jd_imported", "event_id": "hr-jd-import:src-1:job-1:jd-1"}),
    ]
    first = subprocess.run(command, text=True, capture_output=True, check=False)
    duplicate = subprocess.run(command, text=True, capture_output=True, check=False)

    assert first.returncode == 0
    assert json.loads(first.stdout)["status"] == "ok"
    assert duplicate.returncode == 0
    assert json.loads(duplicate.stdout)["status"] == "already_exists"


def test_cli_append_log_rejects_mixed_argument_modes(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_wiki_runtime.cli",
            "append-log",
            "--scope-root",
            str(tmp_path),
            "--log-type",
            "hr_jd_import",
            "--wiki-root",
            str(tmp_path / ".llm-wiki"),
            "--log",
            "logs/legacy.jsonl",
            "--record-json",
            "{}",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "validation_error"


def test_cli_copy_source_registers_metadata_and_is_idempotent(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    source = tmp_path / "jd.md"
    source.write_text("Senior Java Developer", encoding="utf-8")
    metadata = {
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
    command = [
        sys.executable,
        "-m",
        "llm_wiki_runtime.cli",
        "copy-source",
        "--wiki-root",
        str(wiki_root),
        "--source",
        str(source),
        "--logical-path",
        "sources/originals/hr/jobs/jd.md",
        "--source-type",
        "codex_thread_jd_excerpt",
        "--metadata-json",
        json.dumps(metadata),
    ]

    first = subprocess.run(command, text=True, capture_output=True, check=False)
    duplicate = subprocess.run(command, text=True, capture_output=True, check=False)

    assert first.returncode == 0
    assert json.loads(first.stdout)["status"] == "ok"
    assert duplicate.returncode == 0
    assert json.loads(duplicate.stdout)["status"] == "already_exists"
    registry = json.loads((wiki_root / "sources/registry.json").read_text(encoding="utf-8"))
    assert len(registry["sources"]) == 1
    assert registry["sources"][0]["metadata"] == metadata


def test_cli_prepare_excerpt_writes_snapshot_and_json_envelope(tmp_path):
    text = "Candidate note. JD: Senior Java Developer"
    items = [
        {
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "item_id": "item-1",
            "turn_order": 1,
            "item_order": 1,
            "text": text,
        }
    ]
    selections = [
        {
            "turn_id": "turn-1",
            "item_id": "item-1",
            "start": text.index("JD:"),
            "end": len(text),
        }
    ]
    items_file = tmp_path / "items.json"
    selections_file = tmp_path / "selections.json"
    output = tmp_path / "snapshot.md"
    items_file.write_text(json.dumps(items), encoding="utf-8")
    selections_file.write_text(json.dumps(selections), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_wiki_runtime.cli",
            "prepare-excerpt",
            "--items-file",
            str(items_file),
            "--selections-file",
            str(selections_file),
            "--output",
            str(output),
            "--id-prefix",
            "jd",
            "--confirmed-at",
            "2026-07-18T10:00:00+08:00",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["version_id"].startswith("jd-")
    assert payload["snapshot_path"] == str(output)
    assert payload["risk_flags"] == []
    assert output.is_file()
    assert "JD: Senior Java Developer" in output.read_text(encoding="utf-8")


def write_mapping_cli_contract(tmp_path):
    scp = tmp_path / "scp.yml"
    scp.write_text(
        "\n".join(
            [
                "scp_version: v0.1",
                "skill:",
                "  id: hr-resume-screening-copilot",
                "  domain: hr",
                "ingest:",
                "  produces:",
                "    - domain: hr",
                "      record_type: job_profile",
                "    - domain: hr",
                "      record_type: jd_version",
                "    - domain: hr",
                "      log_type: hr_jd_import",
            ]
        ),
        encoding="utf-8",
    )
    mapping = tmp_path / "ingest-mapping.yml"
    mapping.write_text(
        "\n".join(
            [
                "mapping:",
                "  id: hr-jd-codex-thread",
                "  version: v0.1",
                "  domain: hr",
                "  owner_skill_id: hr-resume-screening-copilot",
                "  source_types: [codex_thread_jd_excerpt]",
                "  instruction_ref: references/llm-wiki-ingest.md",
                "produces:",
                "  - record_type: job_profile",
                "  - record_type: jd_version",
                "  - log_type: hr_jd_import",
            ]
        ),
        encoding="utf-8",
    )
    profile = tmp_path / "profile.yml"
    profile.write_text(
        "\n".join(
            [
                "profile:",
                "  id: hr",
                "  version: v0.1",
                "write_rules:",
                "  records:",
                "    job_profile:",
                "      path: domains/hr/jobs/{job_id}/profile.md",
                "      mode: update_allowed",
                "    jd_version:",
                "      path: domains/hr/jobs/{job_id}/versions/{jd_version_id}.md",
                "      mode: create_only",
                "logs:",
                "  types:",
                "    hr_jd_import:",
                "      path: logs/hr-jd-import.jsonl",
                "      mode: append_only",
            ]
        ),
        encoding="utf-8",
    )
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "skills": {
                    "hr-resume-screening-copilot": {
                        "domain": "hr",
                        "scp_path": str(scp),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return mapping, profile, registry


def test_cli_validate_mapping_reports_ok(tmp_path):
    mapping, profile, registry = write_mapping_cli_contract(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_wiki_runtime.cli",
            "validate-mapping",
            "--mapping-path",
            str(mapping),
            "--registry-path",
            str(registry),
            "--profile-path",
            str(profile),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "ok"


def test_cli_validate_mapping_reports_missing_mapping_as_degradable(tmp_path):
    _, profile, registry = write_mapping_cli_contract(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_wiki_runtime.cli",
            "validate-mapping",
            "--mapping-path",
            str(tmp_path / "missing.yml"),
            "--registry-path",
            str(registry),
            "--profile-path",
            str(profile),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "domain_mapping_required"
    assert payload["next_actions"]
