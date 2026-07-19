from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import resolve_config
from .ingest import prepare_excerpt, write_excerpt_snapshot
from .mapping import load_ingest_mapping, validate_ingest_mapping
from .profile import load_profile
from .runtime import (
    append_log,
    append_profile_log,
    copy_source,
    init_home,
    init_profile,
    load_context_pack,
    record_decline,
    register_artifact,
    write_record,
)
from .scp import build_registry, write_registry


def with_response_envelope(payload: dict) -> dict:
    enriched = dict(payload)
    enriched.setdefault("warnings", [])
    enriched.setdefault("next_actions", [])
    enriched.setdefault("context_refs", [])
    return enriched


def emit(payload: dict, exit_code: int = 0) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    print(json.dumps(with_response_envelope(payload), ensure_ascii=False, sort_keys=True))
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
    copy.add_argument("--metadata-json", default="{}")

    artifact = sub.add_parser("register-artifact")
    artifact.add_argument("--wiki-root", required=True)
    artifact.add_argument("--record-json", required=True)

    log = sub.add_parser("append-log")
    log.add_argument("--wiki-root")
    log.add_argument("--log")
    log.add_argument("--scope-root")
    log.add_argument("--profile-path")
    log.add_argument("--log-type")
    log.add_argument("--record-json", required=True)

    write = sub.add_parser("write-record")
    write.add_argument("--scope-root", required=True)
    write.add_argument("--profile-path")
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
    context.add_argument("--path-json", default="[]")
    context.add_argument("--glob-json", default="[]")
    context.add_argument("--order", choices=["path_asc", "mtime_desc"], default="path_asc")
    context.add_argument("--policy")
    context.add_argument("--caller-domain")
    context.add_argument("--target-domain")
    context.add_argument("--domain-policies-json")
    context.add_argument("--caller-groups-json", default="[]")

    prepare = sub.add_parser("prepare-excerpt")
    prepare.add_argument("--items-file", required=True)
    prepare.add_argument("--selections-file", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--id-prefix", default="jd")
    prepare.add_argument("--confirmed-at", required=True)

    validate_mapping = sub.add_parser("validate-mapping")
    validate_mapping.add_argument("--mapping-path", required=True)
    validate_mapping.add_argument("--registry-path", required=True)
    validate_mapping.add_argument("--profile-path", required=True)

    scan_scp = sub.add_parser("scan-scp")
    scan_scp.add_argument("--scp-path-json", required=True)
    scan_scp.add_argument("--domain-policies-json")
    scan_scp.add_argument("--caller-groups-json", default="{}")
    scan_scp.add_argument("--write", action="store_true")
    scan_scp.add_argument("--output")
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
                    return emit(
                        {
                            "status": "validation_error",
                            "error": "--profile is required for --decline",
                            "next_actions": ["pass --profile <profile-id>"],
                        },
                        2,
                    )
                return emit(record_decline(args.profile, args.storage_mode, scope_root))
            if not args.profile_path:
                return emit(
                    {
                        "status": "validation_error",
                        "error": "--profile-path is required",
                        "next_actions": ["pass --profile-path <llm-wiki-profile.yml>"],
                    },
                    2,
                )
            return emit(init_profile(scope_root, Path(args.profile_path), args.storage_mode, args.scope_id))
        if args.command == "copy-source":
            return emit(
                copy_source(
                    Path(args.wiki_root),
                    Path(args.source),
                    args.logical_path,
                    args.source_type,
                    json.loads(args.metadata_json),
                )
            )
        if args.command == "register-artifact":
            return emit(register_artifact(Path(args.wiki_root), json.loads(args.record_json)))
        if args.command == "append-log":
            profile_mode = any((args.scope_root, args.profile_path, args.log_type))
            compatibility_mode = any((args.wiki_root, args.log))
            if profile_mode and compatibility_mode:
                return emit(
                    {"status": "validation_error", "error": "append-log modes cannot be mixed"},
                    2,
                )
            if profile_mode:
                if not args.scope_root or not args.log_type:
                    return emit(
                        {
                            "status": "validation_error",
                            "error": "--scope-root and --log-type are required for profile mode",
                        },
                        2,
                    )
                return emit(
                    append_profile_log(
                        Path(args.scope_root),
                        Path(args.profile_path) if args.profile_path else None,
                        args.log_type,
                        json.loads(args.record_json),
                    )
                )
            if not args.wiki_root or not args.log:
                return emit(
                    {
                        "status": "validation_error",
                        "error": "--wiki-root and --log are required for compatibility mode",
                    },
                    2,
                )
            return emit(append_log(Path(args.wiki_root), args.log, json.loads(args.record_json)))
        if args.command == "write-record":
            return emit(
                write_record(
                    Path(args.scope_root),
                    Path(args.profile_path) if args.profile_path else None,
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
                    json.loads(args.path_json),
                    json.loads(args.glob_json),
                    args.order,
                    args.policy,
                    args.caller_domain,
                    args.target_domain,
                    json.loads(args.domain_policies_json) if args.domain_policies_json else None,
                    json.loads(args.caller_groups_json),
                )
            )
        if args.command == "prepare-excerpt":
            items = json.loads(Path(args.items_file).read_text(encoding="utf-8"))
            selections = json.loads(Path(args.selections_file).read_text(encoding="utf-8"))
            payload = prepare_excerpt(items, selections, args.id_prefix, args.confirmed_at)
            snapshot_path = write_excerpt_snapshot(payload, Path(args.output))
            return emit(
                {
                    "status": "ok",
                    "version_id": payload["version_id"],
                    "body_checksum": payload["body_checksum"],
                    "metadata": payload["metadata"],
                    "risk_flags": payload["risk_flags"],
                    "snapshot_path": str(snapshot_path),
                }
            )
        if args.command == "validate-mapping":
            mapping_path = Path(args.mapping_path)
            if not mapping_path.is_file():
                return emit(
                    {
                        "status": "domain_mapping_required",
                        "error": f"ingest mapping is missing: {mapping_path}",
                        "next_actions": ["install or create the domain-owned ingest-mapping.yml"],
                    },
                    1,
                )
            mapping = load_ingest_mapping(mapping_path)
            registry = json.loads(Path(args.registry_path).read_text(encoding="utf-8"))
            profile = load_profile(Path(args.profile_path))
            return emit(validate_ingest_mapping(mapping, registry, profile))
        if args.command == "scan-scp":
            registry = build_registry(
                [Path(item) for item in json.loads(args.scp_path_json)],
                json.loads(args.domain_policies_json) if args.domain_policies_json else None,
                json.loads(args.caller_groups_json),
            )
            payload = {"status": "ok", **registry}
            if args.write:
                registry_path = write_registry(registry, Path(args.output) if args.output else None)
                payload["registry_path"] = str(registry_path)
            return emit(payload)
        return emit({"status": "invalid_command", "command": args.command}, 2)
    except (ValueError, FileExistsError, json.JSONDecodeError) as exc:
        return emit({"status": "validation_error", "error": str(exc)}, 2)
    except (OSError, TimeoutError) as exc:
        return emit(
            {
                "status": "io_error",
                "error": str(exc),
                "next_actions": ["run maintain or retry after checking filesystem permissions"],
            },
            3,
        )
    except Exception as exc:
        return emit({"status": "unexpected_error", "error": str(exc)}, 4)


if __name__ == "__main__":
    raise SystemExit(main())
