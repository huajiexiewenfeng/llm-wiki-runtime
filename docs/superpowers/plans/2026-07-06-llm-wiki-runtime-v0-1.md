# LLM Wiki Runtime V0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first testable `llm-wiki-runtime` Python CLI that lets domain skills initialize, read, and safely write `.llm-wiki` scopes.

**Architecture:** Implement a small Python package with a deterministic CLI entry point named `llm-wiki`. Keep domain semantics outside the runtime: profile manifests define layouts, write rules, read rules, and artifact types; runtime code enforces config, path safety, locks, atomic writes, registries, logs, and context packs.

**Tech Stack:** Python 3.10+, standard library only for V0.1, `pytest` for tests, `pyproject.toml` console script entry point.

---

## File Structure

- Create `pyproject.toml`: package metadata, console script, pytest config.
- Create `README.md`: public project overview, install/dev commands, V0.1 status.
- Create `.gitignore`: Python caches, build outputs, local `.llm-wiki` runtime data.
- Create `llm_wiki_runtime/__init__.py`: package version.
- Create `llm_wiki_runtime/cli.py`: argparse command routing and JSON stdout responses.
- Create `llm_wiki_runtime/models.py`: dataclasses for command results, config, profile, write rules, context items.
- Create `llm_wiki_runtime/config.py`: `LLM_WIKI_HOME`, runtime user config, local/home scope resolution.
- Create `llm_wiki_runtime/profile.py`: load and validate `llm-wiki-profile.yml`.
- Create `llm_wiki_runtime/paths.py`: path variable validation, template rendering, wiki-root boundary checks.
- Create `llm_wiki_runtime/locking.py`: `.llm-wiki/.meta/lock.json` creation, timeout, stale lock recovery.
- Create `llm_wiki_runtime/io.py`: atomic JSON/text writes and checksum helpers.
- Create `llm_wiki_runtime/runtime.py`: command implementations for `init-home`, `resolve-config`, `init-profile`, `copy-source`, `write-record`, `load-context-pack`, `register-artifact`, `append-log`.
- Create `examples/hr/llm-wiki-profile.yml`: HR sample profile.
- Create `examples/devops/llm-wiki-profile.yml`: DevOps sample profile.
- Create `tests/fixtures/hr-profile.yml`: minimal profile used by tests.
- Create `tests/test_config.py`: home/local scope resolution and decline behavior.
- Create `tests/test_paths.py`: path variable and boundary checks.
- Create `tests/test_locking.py`: lock acquisition, stale handling, bootstrap `.meta`.
- Create `tests/test_registries.py`: runtime home init, decline persistence, source registry, artifact index, append log.
- Create `tests/test_write_record.py`: write modes, refs, checksums, revision metadata.
- Create `tests/test_context_pack.py`: deterministic context pack and `.meta` exclusion.
- Create `tests/test_cli.py`: JSON stdout and exit-code behavior.

Do not commit during implementation unless the user explicitly asks. Use staging/checkpoints instead.

---

### Task 1: Package Skeleton and CLI Smoke Test

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `llm_wiki_runtime/__init__.py`
- Create: `llm_wiki_runtime/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI smoke test**

Create `tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_cli.py -q
```

Expected: FAIL because `llm_wiki_runtime` does not exist yet.

- [ ] **Step 3: Create minimal package files**

Create `llm_wiki_runtime/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `llm_wiki_runtime/cli.py`:

```python
import argparse
import json
from . import __version__


def emit(payload: dict, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-wiki")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "version":
        return emit({"status": "ok", "version": __version__})
    return emit({"status": "invalid_command", "command": args.command}, 2)


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "llm-wiki-runtime"
version = "0.1.0"
description = "Local LLM Wiki runtime and access layer for AI skills."
requires-python = ">=3.10"
dependencies = []

[project.scripts]
llm-wiki = "llm_wiki_runtime.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

Create `.gitignore`:

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
dist/
build/
*.egg-info/
.llm-wiki/
```

Create `README.md`:

```markdown
# llm-wiki-runtime

Local knowledge-base runtime and `.llm-wiki` access layer for AI skills and copilots.

V0.1 focuses on deterministic local CLI behavior: home/scope config, domain profiles, safe writes, registries, logs, and context packs.
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 5: Stage checkpoint**

Run:

```powershell
git add pyproject.toml .gitignore README.md llm_wiki_runtime tests/test_cli.py
git diff --cached --name-status
```

Expected: only skeleton files staged. Do not commit unless the user asks.

---

### Task 2: Config Resolution and Runtime Home

**Files:**
- Create: `llm_wiki_runtime/models.py`
- Create: `llm_wiki_runtime/config.py`
- Modify: `llm_wiki_runtime/cli.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_config.py`:

```python
from pathlib import Path
from llm_wiki_runtime.config import resolve_config, default_home_for_platform


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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_config.py -q
```

Expected: FAIL because `config.py` does not exist.

- [ ] **Step 3: Implement minimal config model and parser**

Implement dataclasses in `llm_wiki_runtime/models.py`:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConfigResult:
    status: str
    enabled: bool
    scope_root: Path
    wiki_root: Path | None
    storage_mode: str | None
    scope_id: str | None
    primary_profile: str | None
    wiki_home: Path | None = None
    scope_type: str | None = None
    privacy: str | None = None
    fallback_mode: str = "markdown"
```

Implement `llm_wiki_runtime/config.py` with standard-library parsing for the V0.1 subset:

```python
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
    return Path(os.environ.get("LLM_WIKI_HOME", default_home_for_platform()))


def read_text_config(path: Path) -> dict[str, str]:
    """Parse the tiny V0.1 YAML subset used in tests.

    This intentionally supports simple `key: value` lines only. Nested profile
    and runtime config parsing is handled by dedicated helpers below so future
    config growth does not silently change behavior.
    """
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
            current = stripped[:-1]
            in_target = current == profile
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
        if profile and primary and profile != primary:
            return ConfigResult("profile_mismatch", False, config_path.parent, None, storage_mode, values.get("scope_id"), primary, home)
        if values.get("enabled", "true").lower() == "false":
            return ConfigResult("disabled", False, config_path.parent, None, storage_mode, values.get("scope_id"), primary, home)
        if storage_mode == "home":
            scope_id = values.get("scope_id") or HOME_DEFAULT_PROFILES.get(primary or "")
            wiki_root = home / "scopes" / scope_id / ".llm-wiki"
        else:
            wiki_root = config_path.parent / values.get("storage", ".llm-wiki")
            scope_id = values.get("scope_id")
        return ConfigResult("enabled", True, config_path.parent, wiki_root, storage_mode, scope_id, primary, home, values.get("scope_type"), values.get("privacy"))

    scope_id = HOME_DEFAULT_PROFILES.get(profile or "")
    if scope_id:
        if profile_declined(profile):
            return ConfigResult("disabled", False, cwd_path, None, "home", scope_id, profile, home)
        home_scope = home / "scopes" / scope_id
        home_config = home_scope / ".llm-wiki.yml"
        wiki_root = home_scope / ".llm-wiki"
        if home_config.exists():
            values = read_text_config(home_config)
            return ConfigResult("enabled", True, home_scope, wiki_root, "home", scope_id, profile, home, values.get("scope_type"), values.get("privacy"))
        return ConfigResult("missing_config", False, cwd_path, wiki_root, "home", scope_id, profile, home)

    return ConfigResult("missing_config", False, cwd_path, None, None, None, profile, home)
```

- [ ] **Step 4: Wire `resolve-config` CLI**

Add a parser subcommand in `llm_wiki_runtime/cli.py`:

```python
resolve = sub.add_parser("resolve-config")
resolve.add_argument("--cwd", default=".")
resolve.add_argument("--profile")
resolve.add_argument("--scope")
```

Handle it:

```python
from .config import resolve_config

if args.command == "resolve-config":
    result = resolve_config(cwd=args.cwd, profile=args.profile, scope=args.scope)
    payload = {
        "status": result.status,
        "enabled": result.enabled,
        "scope_root": str(result.scope_root),
        "wiki_root": str(result.wiki_root) if result.wiki_root else None,
        "wiki_home": str(result.wiki_home) if result.wiki_home else None,
        "storage_mode": result.storage_mode,
        "scope_id": result.scope_id,
        "primary_profile": result.primary_profile,
        "scope_type": result.scope_type,
        "privacy": result.privacy,
        "fallback_mode": result.fallback_mode,
    }
    return emit(payload, 0 if result.status == "enabled" else 1)
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest tests/test_config.py tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 6: Stage checkpoint**

Run:

```powershell
git add llm_wiki_runtime tests pyproject.toml
git diff --cached --name-status
```

Expected: config and CLI files staged. Do not commit unless the user asks.

---

### Task 3: Path Safety and Profile Loading

**Files:**
- Create: `llm_wiki_runtime/paths.py`
- Create: `llm_wiki_runtime/profile.py`
- Test: `tests/test_paths.py`

- [ ] **Step 1: Write failing path tests**

Create `tests/test_paths.py`:

```python
from pathlib import Path
import pytest
from llm_wiki_runtime.paths import validate_slug, render_logical_path, ensure_under_root


@pytest.mark.parametrize("value", ["../x", "a/b", "a\\b", "", ".", "..", "C:bad"])
def test_validate_slug_rejects_unsafe_values(value):
    with pytest.raises(ValueError):
        validate_slug(value)


def test_render_logical_path_substitutes_safe_vars():
    path = render_logical_path("domains/hr/candidates/{candidate_id}/profile.md", {"candidate_id": "zhang-san"})
    assert path == Path("domains/hr/candidates/zhang-san/profile.md")


def test_ensure_under_root_rejects_escape(tmp_path):
    with pytest.raises(ValueError):
        ensure_under_root(tmp_path, Path("../escape.md"))
```

- [ ] **Step 2: Implement path helpers**

Create `llm_wiki_runtime/paths.py`:

```python
import re
from pathlib import Path

SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_slug(value: str) -> str:
    if not value or value in {".", ".."} or len(value) > 128:
        raise ValueError(f"unsafe path variable: {value!r}")
    if "/" in value or "\\" in value or ":" in value:
        raise ValueError(f"unsafe path variable: {value!r}")
    if not SLUG_RE.match(value):
        raise ValueError(f"unsafe path variable: {value!r}")
    return value


def render_logical_path(template: str, variables: dict[str, str]) -> Path:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace("{" + key + "}", validate_slug(value))
    if "{" in rendered or "}" in rendered:
        raise ValueError(f"unresolved path template: {template}")
    return Path(rendered)


def ensure_under_root(root: Path, logical_path: Path) -> Path:
    if logical_path.is_absolute():
        raise ValueError("absolute logical paths are not allowed")
    target = (root / logical_path).resolve()
    root_resolved = root.resolve()
    if root_resolved != target and root_resolved not in target.parents:
        raise ValueError("path escapes wiki root")
    return target
```

- [ ] **Step 3: Run tests**

Run:

```powershell
python -m pytest tests/test_paths.py -q
```

Expected: PASS.

---

### Task 4: Locking and Atomic IO

**Files:**
- Create: `llm_wiki_runtime/locking.py`
- Create: `llm_wiki_runtime/io.py`
- Test: `tests/test_locking.py`

- [ ] **Step 1: Write failing locking tests**

Create `tests/test_locking.py`:

```python
import json
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from llm_wiki_runtime.locking import ScopeLock


def test_lock_creates_meta_before_init_profile(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    with ScopeLock(wiki_root, command="init-profile", timeout_seconds=1):
        assert (wiki_root / ".meta" / "lock.json").exists()


def test_lock_releases_file(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    with ScopeLock(wiki_root, command="write-record", timeout_seconds=1):
        pass
    assert not (wiki_root / ".meta" / "lock.json").exists()


def test_stale_lock_is_renamed_and_reclaimed(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    meta = wiki_root / ".meta"
    meta.mkdir(parents=True)
    lock = meta / "lock.json"
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=11)
    lock.write_text(
        json.dumps({
            "pid": 99999999,
            "host": "unknown-host",
            "command": "write-record",
            "acquired_at": stale_time.isoformat(),
        }),
        encoding="utf-8",
    )
    with ScopeLock(wiki_root, command="write-record", timeout_seconds=1, stale_seconds=600):
        assert lock.exists()
        assert json.loads(lock.read_text(encoding="utf-8"))["host"] == socket.gethostname()
    stale_files = list(meta.glob("lock.stale.*.json"))
    assert len(stale_files) == 1


def test_same_host_dead_pid_is_reclaimed_without_waiting_for_stale_threshold(tmp_path, monkeypatch):
    wiki_root = tmp_path / ".llm-wiki"
    meta = wiki_root / ".meta"
    meta.mkdir(parents=True)
    lock = meta / "lock.json"
    lock.write_text(
        json.dumps({
            "pid": 99999999,
            "host": socket.gethostname(),
            "command": "write-record",
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr("llm_wiki_runtime.locking.pid_is_alive", lambda pid: False)
    with ScopeLock(wiki_root, command="write-record", timeout_seconds=1, stale_seconds=600):
        assert lock.exists()
        assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid()
```

- [ ] **Step 2: Implement lock**

Create `llm_wiki_runtime/locking.py`:

```python
import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


class ScopeLock:
    def __init__(self, wiki_root: Path, command: str, timeout_seconds: int = 30, stale_seconds: int = 600):
        self.wiki_root = wiki_root
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.stale_seconds = stale_seconds
        self.meta_dir = wiki_root / ".meta"
        self.lock_path = self.meta_dir / "lock.json"

    def __enter__(self):
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout_seconds
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump({
                        "pid": os.getpid(),
                        "host": socket.gethostname(),
                        "command": self.command,
                        "acquired_at": datetime.now(timezone.utc).isoformat(),
                    }, fh)
                return self
            except FileExistsError:
                self._recover_stale_lock()
                if time.time() >= deadline:
                    raise TimeoutError(f"could not acquire lock: {self.lock_path}")
                time.sleep(0.1)

    def __exit__(self, exc_type, exc, tb):
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

    def _recover_stale_lock(self) -> None:
        try:
            payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
            acquired = datetime.fromisoformat(payload["acquired_at"])
            pid = int(payload.get("pid", -1))
        except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
            return
        age = datetime.now(timezone.utc) - acquired
        same_host_dead_pid = payload.get("host") == socket.gethostname() and not pid_is_alive(pid)
        lock_is_too_old = age.total_seconds() >= self.stale_seconds
        if not same_host_dead_pid and not lock_is_too_old:
            return
        stale_name = self.meta_dir / f"lock.stale.{int(time.time())}.json"
        try:
            os.replace(self.lock_path, stale_name)
        except FileNotFoundError:
            return
```

Create `llm_wiki_runtime/io.py`:

```python
import hashlib
import json
import os
import uuid
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for old_tmp in path.parent.glob(path.name + ".*.tmp"):
        try:
            old_tmp.unlink()
        except OSError:
            pass
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def atomic_write_json(path: Path, payload: object) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
```

- [ ] **Step 3: Run tests**

Run:

```powershell
python -m pytest tests/test_locking.py -q
```

Expected: PASS.

---

### Task 4.5: Runtime Registries and Missing CLI Commands

**Files:**
- Create: `llm_wiki_runtime/runtime.py`
- Modify: `llm_wiki_runtime/cli.py`
- Test: `tests/test_registries.py`

- [ ] **Step 1: Write failing registry and command tests**

Create `tests/test_registries.py`:

```python
import json
from pathlib import Path
from llm_wiki_runtime.runtime import init_home, record_decline, copy_source, register_artifact, append_log


def test_init_home_writes_runtime_config(tmp_path, monkeypatch):
    config = tmp_path / "config.yml"
    monkeypatch.setenv("LLM_WIKI_RUNTIME_CONFIG", str(config))
    payload = init_home(tmp_path / "LLM Wiki")
    assert payload["status"] == "ok"
    assert config.exists()
    assert "home:" in config.read_text(encoding="utf-8")


def test_record_decline_for_home_profile_writes_runtime_config(tmp_path, monkeypatch):
    config = tmp_path / "config.yml"
    monkeypatch.setenv("LLM_WIKI_RUNTIME_CONFIG", str(config))
    payload = record_decline(profile="hr", storage_mode="home", scope_root=tmp_path)
    assert payload["status"] == "disabled"
    text = config.read_text(encoding="utf-8")
    assert "hr:" in text
    assert "enabled: false" in text


def test_runtime_config_merges_home_and_multiple_profile_declines(tmp_path, monkeypatch):
    config = tmp_path / "config.yml"
    monkeypatch.setenv("LLM_WIKI_RUNTIME_CONFIG", str(config))
    home = tmp_path / "LLM Wiki"
    init_home(home)
    record_decline(profile="learning", storage_mode="home", scope_root=tmp_path)
    record_decline(profile="hr", storage_mode="home", scope_root=tmp_path)
    text = config.read_text(encoding="utf-8")
    assert f"home: {home}" in text
    assert "learning:" in text
    assert "hr:" in text
    assert text.count("enabled: false") == 2


def test_record_decline_for_local_profile_writes_scope_config(tmp_path):
    payload = record_decline(profile="devops", storage_mode="local", scope_root=tmp_path)
    assert payload["status"] == "disabled"
    assert (tmp_path / ".llm-wiki.yml").exists()
    assert "enabled: false" in (tmp_path / ".llm-wiki.yml").read_text(encoding="utf-8")


def test_copy_source_copies_file_and_registers_source(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    source = tmp_path / "resume.pdf"
    source.write_bytes(b"resume")
    payload = copy_source(wiki_root, source, "sources/originals/hr/resumes/zhang-san/resume.pdf", "resume_pdf")
    assert payload["status"] == "ok"
    assert payload["source_id"]
    registry = json.loads((wiki_root / "sources" / "registry.json").read_text(encoding="utf-8"))
    assert registry["sources"][0]["source_id"] == payload["source_id"]


def test_register_artifact_updates_index(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    payload = register_artifact(wiki_root, {"artifact_id": "art-001", "artifact_type": "screening_report", "path": "domains/hr/report.md"})
    assert payload["status"] == "ok"
    index = json.loads((wiki_root / "artifacts" / "index.json").read_text(encoding="utf-8"))
    assert index["artifacts"][0]["artifact_id"] == "art-001"


def test_append_log_appends_jsonl(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    payload = append_log(wiki_root, "logs/hr-screening-log.jsonl", {"event": "screening_started"})
    assert payload["status"] == "ok"
    text = (wiki_root / "logs" / "hr-screening-log.jsonl").read_text(encoding="utf-8")
    assert "screening_started" in text
```

- [ ] **Step 2: Implement registry command functions**

Add these functions to `llm_wiki_runtime/runtime.py`:

```python
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from .config import runtime_config_path
from .io import atomic_write_json, atomic_write_text, sha256_file
from .locking import ScopeLock
from .paths import ensure_under_root


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_runtime_config_text() -> str:
    path = runtime_config_path()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def merge_home_config(existing: str, home: Path) -> str:
    remaining = [line for line in existing.splitlines() if not line.startswith("home:")]
    lines = [f"home: {home}", *remaining]
    return "\n".join(line for line in lines if line.strip()) + "\n"


def remove_profile_block(existing: str, profile: str) -> str:
    lines = existing.splitlines()
    output = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line == "profiles:":
            output.append(line)
            i += 1
            while i < len(lines) and (not lines[i] or lines[i].startswith(" ")):
                if lines[i] == f"  {profile}:":
                    i += 1
                    while i < len(lines) and (not lines[i] or lines[i].startswith("    ")):
                        i += 1
                    continue
                output.append(lines[i])
                i += 1
            continue
        output.append(line)
        i += 1
    return "\n".join(line for line in output if line.strip())


def merge_profile_decline(existing: str, profile: str) -> str:
    cleaned = remove_profile_block(existing, profile)
    lines = cleaned.splitlines() if cleaned else []
    if "profiles:" not in lines:
        lines.append("profiles:")
    lines.extend([
        f"  {profile}:",
        "    enabled: false",
        "    default_storage_mode: home",
        f"    declined_at: {now_iso()}",
    ])
    return "\n".join(lines) + "\n"


def init_home(home: Path) -> dict:
    config = runtime_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(config, merge_home_config(read_runtime_config_text(), home))
    home.mkdir(parents=True, exist_ok=True)
    return {"status": "ok", "wiki_home": str(home)}


def record_decline(profile: str, storage_mode: str, scope_root: Path) -> dict:
    if storage_mode == "home":
        config = runtime_config_path()
        config.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(config, merge_profile_decline(read_runtime_config_text(), profile))
        return {"status": "disabled", "profile": profile, "storage_mode": "home"}
    target = scope_root / ".llm-wiki.yml"
    atomic_write_text(target, "llm_wiki:\n  enabled: false\n")
    return {"status": "disabled", "profile": profile, "storage_mode": "local"}


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def copy_source(wiki_root: Path, source: Path, logical_path: str, source_type: str) -> dict:
    with ScopeLock(wiki_root, command="copy-source"):
        target = ensure_under_root(wiki_root, Path(logical_path))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        checksum = sha256_file(target)
        source_id = "src-" + checksum[:12]
        registry_path = wiki_root / "sources" / "registry.json"
        registry = load_json(registry_path, {"sources": []})
        registry["sources"].append({
            "source_id": source_id,
            "source_type": source_type,
            "path": logical_path,
            "checksum": checksum,
            "registered_at": now_iso(),
        })
        atomic_write_json(registry_path, registry)
        return {"status": "ok", "source_id": source_id, "path": logical_path, "checksum": checksum}


def register_artifact(wiki_root: Path, record: dict) -> dict:
    with ScopeLock(wiki_root, command="register-artifact"):
        index_path = wiki_root / "artifacts" / "index.json"
        index = load_json(index_path, {"artifacts": []})
        enriched = dict(record)
        enriched["registered_at"] = now_iso()
        index["artifacts"].append(enriched)
        atomic_write_json(index_path, index)
        return {"status": "ok", "artifact_id": record["artifact_id"]}


def append_log(wiki_root: Path, logical_log_path: str, record: dict) -> dict:
    with ScopeLock(wiki_root, command="append-log"):
        target = ensure_under_root(wiki_root, Path(logical_log_path))
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"logged_at": now_iso(), **record}, ensure_ascii=False, sort_keys=True)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        atomic_write_text(target, existing + line + "\n")
        return {"status": "ok", "path": logical_log_path}
```

- [ ] **Step 3: Wire CLI commands**

Add subcommands and JSON output for:

```text
init-home --home <path>
init-profile --decline --profile <id> --storage-mode home|local --scope-root <path>
copy-source --wiki-root <path> --source <path> --logical-path <path> --source-type <type>
register-artifact --wiki-root <path> --record-json <json>
append-log --wiki-root <path> --log <path> --record-json <json>
```

Create the `init-profile` parser in Task 4.5 with `--decline`; Task 5 extends the same parser for normal profile initialization.

Each command returns `0` on success, `2` on validation errors, and `3` on IO or lock errors.

- [ ] **Step 4: Run registry tests**

Run:

```powershell
python -m pytest tests/test_registries.py tests/test_locking.py -q
```

Expected: PASS.

- [ ] **Step 5: Stage checkpoint**

Run:

```powershell
git add llm_wiki_runtime tests/test_registries.py
git diff --cached --name-status
```

Expected: registry command files staged. Do not commit unless the user asks.

---

### Task 5: Init Profile, Write Record, and Context Pack

**Files:**
- Modify: `llm_wiki_runtime/runtime.py`
- Modify: `llm_wiki_runtime/cli.py`
- Test: `tests/test_write_record.py`
- Test: `tests/test_context_pack.py`

- [ ] **Step 1: Write tests for write-record and context pack**

Create tests that assert:

```python
from pathlib import Path
import json
import pytest
from llm_wiki_runtime.runtime import copy_source, write_record, load_context_pack


def write_profile(path: Path) -> None:
    path.write_text(
        "\n".join([
            "profile:",
            "  id: hr",
            "  version: v0.1",
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
            "    screening_report:",
            "      path: domains/hr/screenings/{run_id}/report.md",
            "      mode: create_only",
            "      required_vars: [run_id]",
            "      required_refs: []",
            "    screening_log:",
            "      path: logs/hr-screening-log.jsonl",
            "      mode: append_only",
            "      required_vars: []",
            "      required_refs: []",
            "read_rules:",
            "  context_pack:",
            "    include: [domains/hr/**, logs/**]",
            "    exclude: [.meta/**]",
            "    max_files: 30",
            "    max_chars_per_file: 4000",
            "artifacts:",
            "  types: [screening_report]",
        ]),
        encoding="utf-8",
    )


def test_write_record_create_only_refuses_overwrite(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    profile = tmp_path / "llm-wiki-profile.yml"
    write_profile(profile)
    content = tmp_path / "report.md"
    content.write_text("first", encoding="utf-8")
    write_record(tmp_path, profile, "screening_report", {"run_id": "run-001"}, {}, content)
    content.write_text("second", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_record(tmp_path, profile, "screening_report", {"run_id": "run-001"}, {}, content)


def test_write_record_update_allowed_records_meta_change_log(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    profile = tmp_path / "llm-wiki-profile.yml"
    write_profile(profile)
    source = tmp_path / "resume.pdf"
    source.write_bytes(b"resume")
    source_payload = copy_source(wiki_root, source, "sources/originals/hr/resume.pdf", "resume_pdf")
    content = tmp_path / "profile.md"
    content.write_text("first", encoding="utf-8")
    write_record(tmp_path, profile, "candidate_profile", {"candidate_id": "zhang-san"}, {"source_id": source_payload["source_id"]}, content)
    content.write_text("second", encoding="utf-8")
    write_record(tmp_path, profile, "candidate_profile", {"candidate_id": "zhang-san"}, {"source_id": source_payload["source_id"]}, content)
    change_log = wiki_root / ".meta" / "change-log.jsonl"
    assert change_log.exists()
    assert "candidate_profile" in change_log.read_text(encoding="utf-8")


def test_write_record_rejects_missing_source_ref(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    profile = tmp_path / "llm-wiki-profile.yml"
    write_profile(profile)
    content = tmp_path / "profile.md"
    content.write_text("first", encoding="utf-8")
    with pytest.raises(ValueError):
        write_record(tmp_path, profile, "candidate_profile", {"candidate_id": "zhang-san"}, {"source_id": "src-missing"}, content)


def test_write_record_append_only_appends(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    profile = tmp_path / "llm-wiki-profile.yml"
    write_profile(profile)
    content = tmp_path / "log.md"
    content.write_text("first\n", encoding="utf-8")
    write_record(tmp_path, profile, "screening_log", {}, {}, content)
    content.write_text("second\n", encoding="utf-8")
    write_record(tmp_path, profile, "screening_log", {}, {}, content)
    assert (wiki_root / "logs" / "hr-screening-log.jsonl").read_text(encoding="utf-8") == "first\nsecond\n"


def test_context_pack_excludes_meta_and_sorts_by_path(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    (wiki_root / "domains/hr/b").mkdir(parents=True)
    (wiki_root / "domains/hr/a").mkdir(parents=True)
    (wiki_root / ".meta").mkdir(parents=True)
    (wiki_root / "domains/hr/b/file.md").write_text("b", encoding="utf-8")
    (wiki_root / "domains/hr/a/file.md").write_text("a", encoding="utf-8")
    (wiki_root / ".meta/change-log.jsonl").write_text("secret", encoding="utf-8")
    payload = load_context_pack(wiki_root, ["domains/hr/**", ".meta/**"], [".meta/**"], 30, 4000)
    paths = [item["path"] for item in payload["items"]]
    assert paths == ["domains/hr/a/file.md", "domains/hr/b/file.md"]
```

Expected behaviors:

- `create_only` raises or returns validation failure when target exists.
- `update_allowed` writes `.llm-wiki/.meta/change-log.jsonl`.
- `load-context-pack` never returns `.meta/**`.
- Default context order is path ascending.

- [ ] **Step 2: Implement command functions**

Implement these function signatures in `llm_wiki_runtime/runtime.py`:

```python
from pathlib import Path


def init_profile(scope_root: Path, profile_path: Path, storage_mode: str, scope_id: str | None) -> dict:
    """Create scope config, declared profile directories, and .llm-wiki/.meta."""


def write_record(
    scope_root: Path,
    profile_path: Path,
    record_type: str,
    variables: dict[str, str],
    refs: dict,
    content_file: Path,
) -> dict:
    """Validate the profile rule, render the target path, enforce write mode, write content, and return JSON-ready metadata."""


def load_context_pack(
    wiki_root: Path,
    include: list[str],
    exclude: list[str],
    max_files: int,
    max_chars_per_file: int,
) -> dict:
    """Return deterministic context items sorted by path and excluding .meta by default."""
```

Use `ScopeLock`, `render_logical_path`, `ensure_under_root`, `atomic_write_text`, and `.meta/change-log.jsonl`.

`write_record` must validate core-owned refs before writing:

```python
def assert_source_exists(wiki_root: Path, source_id: str) -> None:
    registry_path = wiki_root / "sources" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {"sources": []}
    if not any(item.get("source_id") == source_id for item in registry["sources"]):
        raise ValueError(f"unknown source_id: {source_id}")
```

For `append_only`, read the existing target content, append the new content, and write the concatenated result through the locked atomic writer.

- [ ] **Step 3: Wire CLI commands**

Add subcommands:

```text
init-profile
write-record
load-context-pack
```

Each command must return JSON stdout and use:

```text
0 success
1 fallback status
2 validation error
3 IO or lock failure
4 unexpected error
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m pytest tests/test_write_record.py tests/test_context_pack.py tests/test_cli.py -q
```

Expected: PASS.

---

### Task 6: Examples and Documentation

**Files:**
- Create: `examples/hr/llm-wiki-profile.yml`
- Create: `examples/devops/llm-wiki-profile.yml`
- Modify: `README.md`

- [ ] **Step 1: Add HR example profile**

Create `examples/hr/llm-wiki-profile.yml` with records:

```yaml
profile:
  id: hr
  version: v0.1
  display_name: HR Talent Pool
  scope_type: talent_pool
  privacy_default: sensitive_local

layout:
  directories:
    - domains/hr/candidates
    - domains/hr/resumes
    - domains/hr/jobs
    - domains/hr/screenings
    - sources/originals/hr
    - sources/extracts/hr
    - artifacts
    - logs

write_rules:
  records:
    candidate_profile:
      path: domains/hr/candidates/{candidate_id}/profile.md
      mode: update_allowed
      required_vars: [candidate_id]
      required_refs: [source_id, resume_version_id]
      register_artifact: false

read_rules:
  context_pack:
    include: [domains/hr/**, artifacts/**, logs/**]
    exclude: [sources/originals/**, .meta/**]
    max_files: 30
    max_chars_per_file: 4000

artifacts:
  types: [screening_report, ranking, interview_plan]
```

- [ ] **Step 2: Add DevOps example profile**

Create `examples/devops/llm-wiki-profile.yml` with records:

```yaml
profile:
  id: devops
  version: v0.1
  display_name: DevOps Release Workspace
  scope_type: release_workspace
  privacy_default: local

layout:
  directories:
    - domains/devops/package-runs
    - domains/devops/images
    - domains/devops/verifications
    - artifacts
    - logs

write_rules:
  records:
    package_run:
      path: domains/devops/package-runs/{run_id}/summary.md
      mode: create_only
      required_vars: [run_id]
      required_refs: []
      register_artifact: true
      artifact_type: package_run

read_rules:
  context_pack:
    include: [domains/devops/**, artifacts/**, logs/**]
    exclude: [.meta/**]
    max_files: 30
    max_chars_per_file: 4000

artifacts:
  types: [package_run, image_manifest, verification_result]
```

- [ ] **Step 3: Update README with dev workflow**

Add:

````markdown
## Development

```powershell
python -m pytest -q
python -m llm_wiki_runtime.cli version
```

## V0.1 Scope

- Runtime home and local/home scope resolution
- Domain profile manifests
- Safe record writes
- Source/artifact/log registries
- Deterministic context packs
````

- [ ] **Step 4: Run all tests**

Run:

```powershell
python -m pytest -q
```

Expected: PASS.

---

## Plan Self-Review

- Spec coverage: covers naming, home/local scope resolution, first-run missing config behavior, profile-level decline, runtime config merge preservation, profile mismatch, path safety, stale lock recovery including same-host dead PID recovery, lock bootstrap, atomic IO, init-home, copy-source, register-artifact, append-log, write-record, append-only writes, source ref validation, context-pack determinism, `.meta` exclusion, and example HR/DevOps profiles.
- Intentional deferrals: full YAML parser replacement, MCP/HTTP server, vector search, profile version migration, cross-domain search, HR skill integration, DevOps skill integration.
- No commits are required by this plan. Use staged checkpoints until the user asks for commits.
