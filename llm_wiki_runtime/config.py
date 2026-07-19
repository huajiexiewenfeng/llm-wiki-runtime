from __future__ import annotations

import os
import sys
from pathlib import Path

from .models import ConfigResult

HOME_DEFAULT_PROFILES = {
    "hr": "hr-default",
    "learning": "learning-default",
    "ai-radar": "ai-radar-default",
}


def default_home_for_platform() -> Path:
    home = Path.home()
    if sys.platform.startswith("win"):
        return home / "Documents" / "LLM Wiki"
    if sys.platform == "darwin":
        return home / "Documents" / "LLM Wiki"
    return home / ".local" / "share" / "llm-wiki-runtime"


def runtime_config_path() -> Path:
    override = os.environ.get("LLM_WIKI_RUNTIME_CONFIG")
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "llm-wiki-runtime" / "config.yml"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "llm-wiki-runtime" / "config.yml"
    return Path.home() / ".config" / "llm-wiki-runtime" / "config.yml"


def resolve_home() -> Path:
    override = os.environ.get("LLM_WIKI_HOME")
    if override:
        return Path(override)
    configured = read_text_config(runtime_config_path()).get("home")
    if configured:
        return Path(configured)
    return default_home_for_platform()


def read_text_config(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def find_local_config(cwd: Path) -> Path | None:
    current = cwd.resolve()
    for candidate in [current, *current.parents]:
        config = candidate / ".llm-wiki.yml"
        if config.exists():
            return config
    return None


def profile_declined(profile: str | None) -> bool:
    if not profile:
        return False
    path = runtime_config_path()
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    in_profiles = False
    in_target = False
    target_indent = None
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if stripped == "profiles:":
            in_profiles = True
            in_target = False
            target_indent = None
            continue
        if not in_profiles:
            continue
        if indent == 2 and stripped.endswith(":"):
            in_target = stripped[:-1] == profile
            target_indent = indent
            continue
        if in_target and target_indent is not None and indent <= target_indent and stripped:
            in_target = False
        if in_target and stripped == "enabled: false":
            return True
    return False


def resolve_config(cwd: str | Path, profile: str | None = None, scope: str | Path | None = None) -> ConfigResult:
    cwd_path = Path(cwd)
    home = resolve_home()
    config_path = Path(scope) / ".llm-wiki.yml" if scope else find_local_config(cwd_path)
    if config_path and config_path.exists():
        values = read_text_config(config_path)
        storage_mode = values.get("storage_mode", "local")
        primary = values.get("primary_profile", profile)
        scope_id = values.get("scope_id")
        if profile and primary and profile != primary:
            return ConfigResult("profile_mismatch", False, config_path.parent, None, storage_mode, scope_id, primary, home)
        if values.get("enabled", "true").lower() == "false":
            return ConfigResult("disabled", False, config_path.parent, None, storage_mode, scope_id, primary, home)
        if storage_mode == "home":
            scope_id = scope_id or HOME_DEFAULT_PROFILES.get(primary or "")
            wiki_root = home / "scopes" / str(scope_id) / ".llm-wiki"
        else:
            wiki_root = config_path.parent / values.get("storage", ".llm-wiki")
        return ConfigResult(
            "enabled",
            True,
            config_path.parent,
            wiki_root,
            storage_mode,
            scope_id,
            primary,
            home,
            values.get("scope_type"),
            values.get("privacy"),
        )

    scope_id = HOME_DEFAULT_PROFILES.get(profile or "")
    if scope_id:
        if profile_declined(profile):
            return ConfigResult("disabled", False, cwd_path, None, "home", scope_id, profile, home)
        home_scope = home / "scopes" / scope_id
        home_config = home_scope / ".llm-wiki.yml"
        wiki_root = home_scope / ".llm-wiki"
        if home_config.exists():
            values = read_text_config(home_config)
            return ConfigResult(
                "enabled",
                True,
                home_scope,
                wiki_root,
                "home",
                scope_id,
                profile,
                home,
                values.get("scope_type"),
                values.get("privacy"),
            )
        return ConfigResult("missing_config", False, cwd_path, wiki_root, "home", scope_id, profile, home)

    return ConfigResult("missing_config", False, cwd_path, None, None, None, profile, home)
