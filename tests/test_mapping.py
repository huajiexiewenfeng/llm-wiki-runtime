from pathlib import Path

import pytest

from llm_wiki_runtime.mapping import load_ingest_mapping, validate_ingest_mapping
from llm_wiki_runtime.profile import load_profile


MAPPING_TEXT = """mapping:
  id: hr-jd-codex-thread
  version: v0.1
  domain: hr
  owner_skill_id: hr-resume-screening-copilot
  source_types: [codex_thread_jd_excerpt]
  instruction_ref: references/llm-wiki-ingest.md
produces:
  - record_type: job_profile
  - record_type: jd_version
  - log_type: hr_jd_import
"""


def load_contract(
    tmp_path: Path,
    *,
    owner_has_jd: bool = True,
    profile_has_log: bool = True,
    owner_domain: str = "hr",
):
    mapping_path = tmp_path / "ingest-mapping.yml"
    mapping_path.write_text(MAPPING_TEXT, encoding="utf-8")

    owner_products = [
        f"    - domain: {owner_domain}",
        "      record_type: job_profile",
    ]
    if owner_has_jd:
        owner_products.extend([f"    - domain: {owner_domain}", "      record_type: jd_version"])
    owner_products.extend([f"    - domain: {owner_domain}", "      log_type: hr_jd_import"])
    scp_path = tmp_path / "scp.yml"
    scp_path.write_text(
        "\n".join(
            [
                "scp_version: v0.1",
                "skill:",
                "  id: hr-resume-screening-copilot",
                f"  domain: {owner_domain}",
                "ingest:",
                "  produces:",
                *owner_products,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    profile_lines = [
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
    ]
    if profile_has_log:
        profile_lines.extend(
            [
                "logs:",
                "  types:",
                "    hr_jd_import:",
                "      path: logs/hr-jd-import.jsonl",
                "      mode: append_only",
            ]
        )
    profile_path = tmp_path / "profile.yml"
    profile_path.write_text("\n".join(profile_lines) + "\n", encoding="utf-8")
    registry = {
        "skills": {
            "hr-resume-screening-copilot": {
                "domain": owner_domain,
                "scp_path": str(scp_path),
            }
        }
    }
    return load_ingest_mapping(mapping_path), registry, load_profile(profile_path)


def test_mapping_products_must_be_declared_by_owner_scp_and_profile(tmp_path):
    mapping, registry, profile = load_contract(tmp_path)

    payload = validate_ingest_mapping(mapping, registry, profile)

    assert payload["status"] == "ok"
    assert payload["mapping_id"] == "hr-jd-codex-thread"
    assert payload["owner_skill_id"] == "hr-resume-screening-copilot"
    assert payload["produces"] == [
        {"record_type": "job_profile"},
        {"record_type": "jd_version"},
        {"log_type": "hr_jd_import"},
    ]


def test_mapping_rejects_product_missing_from_owner_scp(tmp_path):
    mapping, registry, profile = load_contract(tmp_path, owner_has_jd=False)

    with pytest.raises(ValueError, match="owner SCP does not produce record_type: jd_version"):
        validate_ingest_mapping(mapping, registry, profile)


def test_mapping_rejects_log_missing_from_profile(tmp_path):
    mapping, registry, profile = load_contract(tmp_path, profile_has_log=False)

    with pytest.raises(ValueError, match="profile does not declare log: hr_jd_import"):
        validate_ingest_mapping(mapping, registry, profile)


def test_mapping_rejects_owner_domain_mismatch(tmp_path):
    mapping, registry, profile = load_contract(tmp_path, owner_domain="learning")

    with pytest.raises(ValueError, match="mapping domain does not match owner domain"):
        validate_ingest_mapping(mapping, registry, profile)


def test_load_ingest_mapping_rejects_product_with_multiple_contract_kinds(tmp_path):
    mapping_path = tmp_path / "ingest-mapping.yml"
    mapping_path.write_text(
        MAPPING_TEXT.replace(
            "  - record_type: job_profile",
            "  - record_type: job_profile\n    log_type: hr_jd_import",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="exactly one contract kind"):
        load_ingest_mapping(mapping_path)


def test_status_reference_lists_phase_one_vocabulary_exactly():
    reference = Path(__file__).resolve().parents[1] / "skills/llm-wiki-core/references/status-v0.1.md"
    text = reference.read_text(encoding="utf-8")
    status_block = text.split("```text", 1)[1].split("```", 1)[0]
    assert status_block.split() == [
        "ok",
        "enabled",
        "missing_config",
        "disabled",
        "profile_mismatch",
        "domain_mapping_required",
        "already_exists",
        "validation_error",
        "read_denied",
        "runtime_unavailable",
        "io_error",
        "unexpected_error",
    ]
