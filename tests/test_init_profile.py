from llm_wiki_runtime.runtime import init_profile


def test_init_profile_creates_config_meta_and_declared_directories(tmp_path):
    profile = tmp_path / "llm-wiki-profile.yml"
    profile.write_text(
        "\n".join(
            [
                "profile:",
                "  id: hr",
                "  version: v0.1",
                "  scope_type: talent_pool",
                "  privacy_default: sensitive_local",
                "layout:",
                "  directories:",
                "    - domains/hr/candidates",
                "write_rules:",
                "  records:",
                "read_rules:",
                "  context_pack:",
                "    include: [domains/hr/**]",
                "    exclude: [.meta/**]",
                "artifacts:",
                "  types: []",
            ]
        ),
        encoding="utf-8",
    )
    payload = init_profile(tmp_path, profile, "local", "hr-default")
    assert payload["status"] == "ok"
    assert (tmp_path / ".llm-wiki.yml").exists()
    assert (tmp_path / ".llm-wiki" / ".meta").exists()
    assert (tmp_path / ".llm-wiki" / "domains/hr/candidates").exists()
