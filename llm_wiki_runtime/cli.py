from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import resolve_config
from .runtime import (
    append_log,
    copy_source,
    init_home,
    init_profile,
    load_context_pack,
    record_decline,
    register_artifact,
    write_record,
)


def emit(payload: dict, exit_code: int = 0) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-wiki")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version")

    resolve = sub.add_parser("resolve-config")
    resolve.add_argument("--cwd", default=".")
    resolve.add_argument("--profile")
    resolve.add_argument("--scope")

    init_home_parser = sub.add_parser("init-home")
    init_home_parser.add_argument("--home", required=True)

    init_profile_parser = sub.add_parser("init-profile")
    init_profile_parser.add_argument("--decline", action="store_true")
    init_profile_parser.add_argument("--profile")
    init_profile_parser.add_argument("--storage-mode", choices=["home", "local"], default="local")
    init_profile_parser.add_argument("--scope-root", required=True)
    init_profile_parser.add_argument("--profile-path")
    init_profile_parser.add_argument("--scope-id")

    copy = sub.add_parser("copy-source")
    copy.add_argument("--wiki-root", required=True)
    copy.add_argument("--source", required=True)
    copy.add_argument("--logical-path", required=True)
    copy.add_argument("--source-type", required=True)

    artifact = sub.add_parser("register-artifact")
    artifact.add_argument("--wiki-root", required=True)
    artifact.add_argument("--record-json", required=True)

    log = sub.add_parser("append-log")
    log.add_argument("--wiki-root", required=True)
    log.add_argument("--log", required=True)
    log.add_argument("--record-json", required=True)

    write = sub.add_parser("write-record")
    write.add_argument("--scope-root", required=True)
    write.add_argument("--profile-path", required=True)
    write.add_argument("--record-type", required=True)
    write.add_argument("--variables-json", required=True)
    write.add_argument("--refs-json", required=True)
    write.add_argument("--content-file", required=True)

    context = sub.add_parser("load-context-pack")
    context.add_argument("--wiki-root", required=True)
    context.add_argument("--include-json", required=True)
    context.add_argument("--exclude-json", default="[]")
    context.add_argument("--max-files", type=int, default=30)
    context.add_argument("--max-chars-per-file", type=int, default=4000)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "version":
            return emit({"status": "ok", "version": __version__})
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
        if args.command == "init-home":
            return emit(init_home(Path(args.home)))
        if args.command == "init-profile":
            scope_root = Path(args.scope_root)
            if args.decline:
                if not args.profile:
                    return emit({"status": "validation_error", "error": "--profile is required for --decline"}, 2)
                return emit(record_decline(args.profile, args.storage_mode, scope_root))
            if not args.profile_path:
                return emit({"status": "validation_error", "error": "--profile-path is required"}, 2)
            return emit(init_profile(scope_root, Path(args.profile_path), args.storage_mode, args.scope_id))
        if args.command == "copy-source":
            return emit(copy_source(Path(args.wiki_root), Path(args.source), args.logical_path, args.source_type))
        if args.command == "register-artifact":
            return emit(register_artifact(Path(args.wiki_root), json.loads(args.record_json)))
        if args.command == "append-log":
            return emit(append_log(Path(args.wiki_root), args.log, json.loads(args.record_json)))
        if args.command == "write-record":
            return emit(
                write_record(
                    Path(args.scope_root),
                    Path(args.profile_path),
                    args.record_type,
                    json.loads(args.variables_json),
                    json.loads(args.refs_json),
                    Path(args.content_file),
                )
            )
        if args.command == "load-context-pack":
            return emit(
                load_context_pack(
                    Path(args.wiki_root),
                    json.loads(args.include_json),
                    json.loads(args.exclude_json),
                    args.max_files,
                    args.max_chars_per_file,
                )
            )
        return emit({"status": "invalid_command", "command": args.command}, 2)
    except (ValueError, FileExistsError, json.JSONDecodeError) as exc:
        return emit({"status": "validation_error", "error": str(exc)}, 2)
    except (OSError, TimeoutError) as exc:
        return emit({"status": "io_error", "error": str(exc)}, 3)
    except Exception as exc:
        return emit({"status": "unexpected_error", "error": str(exc)}, 4)


if __name__ == "__main__":
    raise SystemExit(main())
