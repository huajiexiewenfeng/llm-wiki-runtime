import pytest

from llm_wiki_runtime.runtime import init_profile


def write_minimal_profile(tmp_path, domain_id="hr"):
    profile = tmp_path / "llm-wiki-profile.yml"
    profile.write_text(
        "\n".join(
            [
                "profile:",
                f"  id: {domain_id}",
                "  version: v0.1",
                "layout:",
                "  directories:",
                f"    - domains/{domain_id}/records",
                "write_rules:",
                "  records:",
                "read_rules:",
                "  context_pack:",
                f"    include: [domains/{domain_id}/**]",
                "artifacts:",
                "  types: []",
            ]
        ),
        encoding="utf-8",
    )
    return profile


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


def test_init_profile_snapshots_sibling_graph_adapter(tmp_path):
    profile = write_minimal_profile(tmp_path)
    adapter = tmp_path / "graph-adapter.yml"
    adapter.write_text("version: v0.1\ndomain_id: hr\n", encoding="utf-8")

    init_profile(tmp_path, profile, "local", "hr-default")

    snapshot = tmp_path / ".llm-wiki" / ".meta" / "graph-adapters" / "hr.yml"
    assert snapshot.read_text(encoding="utf-8") == adapter.read_text(encoding="utf-8")


def test_init_profile_removes_old_snapshot_when_adapter_is_removed(tmp_path):
    profile = write_minimal_profile(tmp_path)
    adapter = tmp_path / "graph-adapter.yml"
    adapter.write_text("version: v0.1\ndomain_id: hr\n", encoding="utf-8")
    init_profile(tmp_path, profile, "local", "hr-default")
    adapter.unlink()

    init_profile(tmp_path, profile, "local", "hr-default")

    assert not (tmp_path / ".llm-wiki" / ".meta" / "graph-adapters" / "hr.yml").exists()


def test_invalid_adapter_refresh_preserves_existing_graph_adapter_snapshot(tmp_path):
    profile = write_minimal_profile(tmp_path)
    adapter = tmp_path / "graph-adapter.yml"
    adapter.write_text("version: v0.1\ndomain_id: hr\n", encoding="utf-8")
    init_profile(tmp_path, profile, "local", "hr-default")
    snapshot = tmp_path / ".llm-wiki" / ".meta" / "graph-adapters" / "hr.yml"
    original_snapshot = snapshot.read_text(encoding="utf-8")
    adapter.write_text("version: v0.2\ndomain_id: hr\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported graph adapter version"):
        init_profile(tmp_path, profile, "local", "hr-default")

    assert snapshot.read_text(encoding="utf-8") == original_snapshot
