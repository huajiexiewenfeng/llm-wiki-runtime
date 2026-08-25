from pathlib import Path

from llm_wiki_runtime.scp import build_registry, load_scp, write_registry


def write_scp(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_load_scp_parses_minimal_first_party_file(tmp_path):
    scp = tmp_path / "scp.yml"
    write_scp(
        scp,
        "\n".join(
            [
                "scp_version: v0.1",
                "skill:",
                "  id: hr-resume-screening",
                "  domain: hr",
                "llm_wiki:",
                "  profile: hr",
                "  required: false",
                "  fallback_mode: markdown",
                "trust:",
                "  level: internal_sensitive",
                "  instruction_policy: trusted_content",
                "query:",
                "  primary_domain: hr",
                "  supports:",
                "    - domain: ai-radar",
                "      record_types: [tool_trend]",
                "ingest:",
                "  produces:",
                "    - domain: hr",
                "      record_type: candidate_profile",
            ]
        ),
    )

    doc = load_scp(scp)

    assert doc["skill"]["id"] == "hr-resume-screening"
    assert doc["skill"]["domain"] == "hr"
    assert doc["llm_wiki"]["profile"] == "hr"
    assert doc["query"]["supports"][0]["domain"] == "ai-radar"


def test_build_registry_rejects_unauthorized_support(tmp_path):
    scp = tmp_path / "learning.scp.yml"
    write_scp(
        scp,
        "\n".join(
            [
                "scp_version: v0.1",
                "skill:",
                "  id: learning-companion",
                "  domain: learning",
                "llm_wiki:",
                "  profile: learning",
                "trust:",
                "  level: user_owned",
                "  instruction_policy: trusted_content",
                "query:",
                "  primary_domain: learning",
                "  supports:",
                "    - domain: hr",
                "      record_types: [candidate_profile]",
                "ingest:",
                "  produces:",
                "    - domain: learning",
                "      record_type: study_note",
            ]
        ),
    )

    registry = build_registry(
        [scp],
        domain_policies={"hr": {"readable_by": []}},
        caller_groups={"learning-companion": ["first_party"]},
    )

    assert registry["skills"]["learning-companion"]["supports"] == []
    assert registry["warnings"][0]["reason"] == "domain_not_readable_by_caller"


def test_parse_scalar_supports_flow_list_record_types(tmp_path):
    scp = tmp_path / "scp.yml"
    write_scp(
        scp,
        "\n".join(
            [
                "scp_version: v0.1",
                "skill:",
                "  id: learning-companion",
                "  domain: learning",
                "llm_wiki:",
                "  profile: learning",
                "query:",
                "  primary_domain: learning",
                "  supports:",
                "    - domain: ai-radar",
                "      record_types: [tool_trend, learning_material]",
                "ingest:",
                "  produces:",
                "    - domain: learning",
                "      record_type: study_note",
            ]
        ),
    )

    doc = load_scp(scp)

    assert doc["query"]["supports"][0]["record_types"] == ["tool_trend", "learning_material"]


def test_build_registry_warns_on_duplicate_skill_id(tmp_path):
    first = tmp_path / "a.scp.yml"
    second = tmp_path / "b.scp.yml"
    body = [
        "scp_version: v0.1",
        "skill:",
        "  id: duplicate-skill",
        "  domain: learning",
        "llm_wiki:",
        "  profile: learning",
        "query:",
        "  primary_domain: learning",
        "  supports: []",
        "ingest:",
        "  produces:",
        "    - domain: learning",
        "      record_type: study_note",
    ]
    write_scp(first, "\n".join(body))
    write_scp(second, "\n".join(body))

    registry = build_registry([first, second], domain_policies={})

    assert any(item["reason"] == "duplicate_skill_id" for item in registry["warnings"])


def test_build_registry_warns_on_primary_domain_mismatch(tmp_path):
    scp = tmp_path / "bad.scp.yml"
    write_scp(
        scp,
        "\n".join(
            [
                "scp_version: v0.1",
                "skill:",
                "  id: bad-skill",
                "  domain: learning",
                "llm_wiki:",
                "  profile: learning",
                "query:",
                "  primary_domain: hr",
                "  supports: []",
                "ingest:",
                "  produces:",
                "    - domain: learning",
                "      record_type: study_note",
            ]
        ),
    )

    registry = build_registry([scp], domain_policies={})

    assert any(item["reason"] == "primary_domain_mismatch" for item in registry["warnings"])


def test_build_registry_warns_on_produce_domain_mismatch(tmp_path):
    scp = tmp_path / "bad.scp.yml"
    write_scp(
        scp,
        "\n".join(
            [
                "scp_version: v0.1",
                "skill:",
                "  id: bad-skill",
                "  domain: learning",
                "llm_wiki:",
                "  profile: learning",
                "query:",
                "  primary_domain: learning",
                "  supports: []",
                "ingest:",
                "  produces:",
                "    - domain: hr",
                "      record_type: candidate_profile",
            ]
        ),
    )

    registry = build_registry([scp], domain_policies={})

    assert any(item["reason"] == "produce_domain_mismatch" for item in registry["warnings"])


def test_build_registry_rejects_support_record_type_not_produced(tmp_path):
    ai = tmp_path / "ai.scp.yml"
    learning = tmp_path / "learning.scp.yml"
    write_scp(
        ai,
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
    )
    write_scp(
        learning,
        "\n".join(
            [
                "scp_version: v0.1",
                "skill:",
                "  id: learning-companion",
                "  domain: learning",
                "llm_wiki:",
                "  profile: learning",
                "query:",
                "  primary_domain: learning",
                "  supports:",
                "    - domain: ai-radar",
                "      record_types: [missing_type]",
                "ingest:",
                "  produces:",
                "    - domain: learning",
                "      record_type: study_note",
            ]
        ),
    )

    registry = build_registry(
        [ai, learning],
        domain_policies={"ai-radar": {"readable_by": ["*"]}},
    )

    assert registry["skills"]["learning-companion"]["supports"] == []
    assert any(item["reason"] == "support_record_type_not_produced" for item in registry["warnings"])


def test_scp_registry_aliases_write_v02_principal_registry(tmp_path):
    scp = tmp_path / "demo.scp.yml"
    write_scp(
        scp,
        """scp_version: v0.1
skill:
  id: demo-skill
  domain: demo
llm_wiki:
  profile: demo
query:
  primary_domain: demo
  supports: []
ingest:
  produces:
    - domain: demo
      record_type: demo_record
""",
    )

    registry = build_registry([scp], domain_policies={})
    target = write_registry(registry, tmp_path / "registry.json")

    assert registry["version"] == "v0.2"
    assert registry["skills"] == registry["principals"]
    assert registry["skills"]["demo-skill"]["scp_path"] == str(scp)
    assert target.exists()
