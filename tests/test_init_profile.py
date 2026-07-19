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


def test_init_profile_snapshots_active_profile(tmp_path):
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

    snapshot = tmp_path / ".llm-wiki" / ".meta" / "profile.yml"
    assert payload["status"] == "ok"
    assert snapshot.exists()
    assert snapshot.read_text(encoding="utf-8") == profile.read_text(encoding="utf-8")


def test_init_profile_rerun_refreshes_snapshot(tmp_path):
    profile = tmp_path / "llm-wiki-profile.yml"
    profile.write_text(
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
                "read_rules:",
                "  context_pack:",
                "    include: [domains/hr/**]",
                "artifacts:",
                "  types: []",
            ]
        ),
        encoding="utf-8",
    )
    init_profile(tmp_path, profile, "local", "hr-default")
    profile.write_text(profile.read_text(encoding="utf-8") + "\n# refreshed\n", encoding="utf-8")

    init_profile(tmp_path, profile, "local", "hr-default")

    snapshot = tmp_path / ".llm-wiki" / ".meta" / "profile.yml"
    assert "# refreshed" in snapshot.read_text(encoding="utf-8")
    assert (tmp_path / ".llm-wiki" / ".meta" / "profile-snapshot-log.jsonl").exists()
