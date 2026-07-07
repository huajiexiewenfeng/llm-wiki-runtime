from __future__ import annotations

import ctypes
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
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
        self._owns_lock = False

    def __enter__(self):
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout_seconds
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(
                        {
                            "pid": os.getpid(),
                            "host": socket.gethostname(),
                            "command": self.command,
                            "acquired_at": datetime.now(timezone.utc).isoformat(),
                        },
                        fh,
                    )
                self._owns_lock = True
                return self
            except FileExistsError:
                self._recover_stale_lock()
                if time.time() >= deadline:
                    raise TimeoutError(f"could not acquire lock: {self.lock_path}")
                time.sleep(0.1)

    def __exit__(self, exc_type, exc, tb):
        if not self._owns_lock:
            return
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
