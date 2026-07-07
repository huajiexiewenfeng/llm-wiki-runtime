import json
import os
import socket
from datetime import datetime, timedelta, timezone

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
        json.dumps(
            {
                "pid": 99999999,
                "host": "unknown-host",
                "command": "write-record",
                "acquired_at": stale_time.isoformat(),
            }
        ),
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
        json.dumps(
            {
                "pid": 99999999,
                "host": socket.gethostname(),
                "command": "write-record",
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("llm_wiki_runtime.locking.pid_is_alive", lambda pid: False)
    with ScopeLock(wiki_root, command="write-record", timeout_seconds=1, stale_seconds=600):
        assert lock.exists()
        assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid()
