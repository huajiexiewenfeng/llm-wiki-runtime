from pathlib import Path

from llm_wiki_runtime.config import default_home_for_platform, resolve_config
from llm_wiki_runtime.runtime import init_home


def test_init_home_config_is_used_by_resolve_config(tmp_path, monkeypatch):
    runtime_config = tmp_path / "runtime-config.yml"
    configured_home = tmp_path / "configured-home"
    monkeypatch.setenv("LLM_WIKI_RUNTIME_CONFIG", str(runtime_config))
    monkeypatch.delenv("LLM_WIKI_HOME", raising=False)

    init_home(configured_home)

    result = resolve_config(cwd=tmp_path, profile="hr")
    assert result.wiki_home == configured_home
    assert result.wiki_root == configured_home / "scopes" / "hr-default" / ".llm-wiki"


def test_missing_home_scope_returns_missing_config(tmp_path, monkeypatch):
    home = tmp_path / "LLM Wiki"
    monkeypatch.setenv("LLM_WIKI_HOME", str(home))
    result = resolve_config(cwd=tmp_path, profile="hr")
    assert result.status == "missing_config"
    assert result.storage_mode == "home"
    assert result.scope_id == "hr-default"
    assert result.wiki_root == home / "scopes" / "hr-default" / ".llm-wiki"


def test_initialized_home_scope_is_enabled(tmp_path, monkeypatch):
    home = tmp_path / "LLM Wiki"
    scope = home / "scopes" / "hr-default"
    scope.mkdir(parents=True)
    (scope / ".llm-wiki.yml").write_text(
        "llm_wiki:\n  enabled: true\n  storage_mode: home\n  scope_id: hr-default\n  primary_profile: hr\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_WIKI_HOME", str(home))
    result = resolve_config(cwd=tmp_path, profile="hr")
    assert result.status == "enabled"
    assert result.wiki_root == scope / ".llm-wiki"


def test_profile_decline_does_not_override_local_scope(tmp_path, monkeypatch):
    home = tmp_path / "home"
    app_config = tmp_path / "app-config.yml"
    monkeypatch.setenv("LLM_WIKI_HOME", str(home))
    monkeypatch.setenv("LLM_WIKI_RUNTIME_CONFIG", str(app_config))
    app_config.write_text(
        "profiles:\n  hr:\n    enabled: false\n    default_storage_mode: home\n    default_scope_id: hr-default\n",
        encoding="utf-8",
    )
    (tmp_path / ".llm-wiki.yml").write_text(
        "llm_wiki:\n  enabled: true\n  storage_mode: local\n  storage: .llm-wiki\n  primary_profile: hr\n",
        encoding="utf-8",
    )
    result = resolve_config(cwd=tmp_path, profile="hr")
    assert result.status == "enabled"
    assert result.storage_mode == "local"


def test_other_profile_decline_does_not_disable_hr(tmp_path, monkeypatch):
    home = tmp_path / "home"
    app_config = tmp_path / "app-config.yml"
    monkeypatch.setenv("LLM_WIKI_HOME", str(home))
    monkeypatch.setenv("LLM_WIKI_RUNTIME_CONFIG", str(app_config))
    app_config.write_text(
        "profiles:\n  learning:\n    enabled: false\n    default_storage_mode: home\n    default_scope_id: learning-default\n",
        encoding="utf-8",
    )
    result = resolve_config(cwd=tmp_path, profile="hr")
    assert result.status == "missing_config"


def test_local_profile_mismatch_returns_profile_mismatch(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_WIKI_HOME", str(tmp_path / "home"))
    (tmp_path / ".llm-wiki.yml").write_text(
        "llm_wiki:\n  enabled: true\n  storage_mode: local\n  storage: .llm-wiki\n  primary_profile: hr\n",
        encoding="utf-8",
    )
    result = resolve_config(cwd=tmp_path, profile="devops")
    assert result.status == "profile_mismatch"
    assert result.primary_profile == "hr"


def test_default_home_for_platform_returns_path():
    assert isinstance(default_home_for_platform(), Path)
