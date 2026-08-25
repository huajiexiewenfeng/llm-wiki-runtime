from pathlib import Path

import pytest

import llm_wiki_runtime.mapping as mapping_module
from llm_wiki_runtime.mapping import load_ingest_mapping, validate_ingest_mapping
from llm_wiki_runtime.principal import load_principal_manifest
from llm_wiki_runtime.principal_registry import register_workload_principal
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


def write_v02_mapping(tmp_path: Path, *, include_legacy_owner: bool = False) -> Path:
    owner = "  owner_principal_id: demo-harness\n"
    if include_legacy_owner:
        owner += "  owner_skill_id: demo-skill\n"
    path = tmp_path / "workload-ingest-mapping.yml"
    path.write_text(
        """mapping:
  id: demo-workload-ingest
  version: v0.2
  domain: demo
"""
        + owner
        + """  source_types: [demo_source]
  instruction_ref: references/demo-ingest.md
produces:
  - record_type: demo_revision
""",
        encoding="utf-8",
    )
    return path


def workload_registry_and_profile(tmp_path: Path):
    manifest_path = tmp_path / "demo.principal.yml"
    manifest_path.write_text(
        """principal_version: v0.1
principal:
  id: demo-harness
  kind: workload
  role: domain_harness
  domain: demo
llm_wiki:
  profile: demo
  fallback_mode: evidence_only
trust:
  level: sensitive_local
  instruction_policy: data_only
query:
  primary_domain: demo
  supports: []
ingest:
  produces:
    - domain: demo
      record_type: demo_revision
""",
        encoding="utf-8",
    )
    registry = register_workload_principal(
        {"version": "v0.2", "principals": {}, "skills": {}, "domains": {}, "domain_policies": {}, "warnings": []},
        load_principal_manifest(manifest_path),
    )
    profile_path = tmp_path / "demo-profile.yml"
    profile_path.write_text(
        """profile:
  id: demo
  version: v0.1
write_rules:
  records:
    demo_revision:
      path: domains/demo/revisions/{revision_id}.md
      mode: create_only
""",
        encoding="utf-8",
    )
    return registry, load_profile(profile_path)


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
                "query:",
                f"  primary_domain: {owner_domain}",
                "  supports: []",
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


def test_mapping_v02_uses_workload_owner(tmp_path):
    mapping = load_ingest_mapping(write_v02_mapping(tmp_path))
    registry, profile = workload_registry_and_profile(tmp_path)

    result = validate_ingest_mapping(mapping, registry, profile)

    assert result["owner_principal_id"] == "demo-harness"
    assert result["principal_kind"] == "workload"
    assert result["mapping_digest"].startswith("sha256:")


def test_v01_owner_skill_id_is_normalized(tmp_path):
    mapping, registry, profile = load_contract(tmp_path)

    result = validate_ingest_mapping(mapping, registry, profile)

    assert result["owner_principal_id"] == "hr-resume-screening-copilot"
    assert result["owner_skill_id"] == "hr-resume-screening-copilot"


def test_mapping_rejects_two_owner_fields(tmp_path):
    path = write_v02_mapping(tmp_path, include_legacy_owner=True)

    with pytest.raises(ValueError, match="exactly one owner"):
        load_ingest_mapping(path)


@pytest.mark.parametrize(
    ("version", "owner_field", "first_owner", "second_owner"),
    [
        ("v0.1", "owner_skill_id", "demo-skill", "other-skill"),
        ("v0.1", "owner_skill_id", "demo-skill", "demo-skill"),
        ("v0.2", "owner_principal_id", "demo-harness", "other-harness"),
        ("v0.2", "owner_principal_id", "demo-harness", "demo-harness"),
    ],
)
def test_mapping_rejects_duplicate_owner_field(
    tmp_path,
    version,
    owner_field,
    first_owner,
    second_owner,
):
    path = tmp_path / "duplicate-owner.yml"
    path.write_text(
        MAPPING_TEXT.replace("  version: v0.1", f"  version: {version}").replace(
            "  owner_skill_id: hr-resume-screening-copilot",
            f"  {owner_field}: {first_owner}\n  {owner_field}: {second_owner}",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate owner field"):
        load_ingest_mapping(path)


@pytest.mark.parametrize("version", ["[v0.2]", "[]", "''"])
def test_mapping_rejects_non_string_or_empty_version(tmp_path, version):
    path = tmp_path / "invalid-version.yml"
    path.write_text(
        MAPPING_TEXT.replace("  version: v0.1", f"  version: {version}"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="mapping version must be a non-empty string"):
        load_ingest_mapping(path)


def test_mapping_rejects_mapping_version_object(tmp_path, monkeypatch):
    original_parse_scalar = mapping_module.parse_scalar

    def parse_version_object(value: str):
        if value.strip() == "version-object":
            return {"version": "v0.2"}
        return original_parse_scalar(value)

    monkeypatch.setattr(mapping_module, "parse_scalar", parse_version_object)
    path = tmp_path / "object-version.yml"
    path.write_text(
        MAPPING_TEXT.replace("  version: v0.1", "  version: version-object"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="mapping version must be a non-empty string"):
        load_ingest_mapping(path)


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

    with pytest.raises(ValueError, match="owner principal does not produce record_type: jd_version"):
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
        "scope_busy",
        "partial_failure",
        "read_denied",
        "runtime_unavailable",
        "io_error",
        "unexpected_error",
    ]
