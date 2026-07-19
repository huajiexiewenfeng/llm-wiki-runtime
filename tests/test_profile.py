import pytest

from llm_wiki_runtime.profile import load_profile


def test_load_profile_parses_records_and_context(tmp_path):
    profile_path = tmp_path / "llm-wiki-profile.yml"
    profile_path.write_text(
        "\n".join(
            [
                "profile:",
                "  id: hr",
                "  version: v0.1",
                "  display_name: HR Talent Pool",
                "  scope_type: talent_pool",
                "  privacy_default: sensitive_local",
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
                "read_rules:",
                "  context_pack:",
                "    include: [domains/hr/**]",
                "    exclude: [.meta/**]",
                "    max_files: 30",
                "    max_chars_per_file: 4000",
                "artifacts:",
                "  types: [screening_report]",
            ]
        ),
        encoding="utf-8",
    )
    profile = load_profile(profile_path)
    assert profile.id == "hr"
    assert profile.directories == ["domains/hr/candidates"]
    assert profile.write_rules["candidate_profile"].mode == "update_allowed"
    assert profile.context_pack.include == ["domains/hr/**"]
    assert profile.artifact_types == ["screening_report"]


def test_load_profile_parses_append_only_log_contract(tmp_path):
    profile_path = tmp_path / "llm-wiki-profile.yml"
    profile_path.write_text(
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

    profile = load_profile(profile_path)

    assert profile.log_rules["hr_jd_import"].path == "logs/hr-jd-import.jsonl"
    assert profile.log_rules["hr_jd_import"].mode == "append_only"


@pytest.mark.parametrize(
    ("path_value", "mode_value", "message"),
    [
        ("", "append_only", "log path is required"),
        ("logs/hr-jd-import.jsonl", "update_allowed", "unsupported log mode"),
    ],
)
def test_load_profile_rejects_invalid_log_contract(tmp_path, path_value, mode_value, message):
    profile_path = tmp_path / "llm-wiki-profile.yml"
    profile_path.write_text(
        "\n".join(
            [
                "profile:",
                "  id: hr",
                "  version: v0.1",
                "logs:",
                "  types:",
                "    hr_jd_import:",
                f"      path: {path_value}",
                f"      mode: {mode_value}",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_profile(profile_path)
