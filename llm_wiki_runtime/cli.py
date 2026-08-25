from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from . import __version__
from .config import resolve_config
from .graph_export import export_graphs
from .ingest import prepare_excerpt, write_excerpt_snapshot
from .invocation import InvocationError, execute_invocation, load_invocation
from .mapping import load_ingest_mapping, validate_ingest_mapping
from .profile import load_profile
from .record_lookup import find_records
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


def parse_lookup_value(raw: str):
    value = json.loads(raw)
    if value is None or isinstance(value, (list, dict)):
        raise ValueError("lookup value must be a non-null finite JSON scalar")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("lookup value must be a non-null finite JSON scalar")
    if not isinstance(value, (str, int, float, bool)):
        raise ValueError("lookup value must be a non-null finite JSON scalar")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-wiki")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version")

    resolve = sub.add_parser("resolve-config")
    resolve.add_argument("--cwd", default=".")
    resolve.add_argument("--profile")
    resolve.add_argument("--scope")

    graph_export = sub.add_parser("graph-export")
    graph_export.add_argument("--cwd", default=".")
    graph_export.add_argument("--profile")
    graph_export.add_argument("--scope")
    graph_export.add_argument("--domain")

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

    lookup = sub.add_parser("find-records")
    lookup.add_argument("--scope-root", required=True)
    lookup.add_argument("--record-type", required=True)
    lookup.add_argument("--lookup-value-json", required=True)
    lookup.add_argument("--caller-domain")
    lookup.add_argument("--target-domain")
    lookup.add_argument("--domain-policies-json")
    lookup.add_argument("--caller-groups-json", default="[]")

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

    invoke = sub.add_parser("invoke")
    invoke.add_argument("--request", required=True)
    invoke.add_argument("--registry-path", required=True)
    invoke.add_argument("--profile-path")
    invoke.add_argument("--mapping-path")
    invoke.add_argument("--domain-policies-json")

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
            payload = _config_payload(result)
            return emit(payload, 0 if result.status == "enabled" else 1)
        if args.command == "graph-export":
            result = resolve_config(cwd=args.cwd, profile=args.profile, scope=args.scope)
            if not result.enabled:
                return emit(_config_payload(result), 2)
            try:
                payload = export_graphs(result.scope_root, args.domain)
            except TimeoutError:
                return emit({"status": "scope_busy", "errors": ["scope_lock_timeout"]}, 3)
            except OSError:
                return emit({"status": "io_error", "errors": ["graph_export_io_error"]}, 3)
            except (TypeError, ValueError):
                return emit({"status": "validation_error", "errors": ["graph_export_validation_error"]}, 2)
            exit_code = 0 if payload["status"] == "ok" else 1 if payload["status"] == "partial_failure" else 2
            return emit(payload, exit_code)
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
        if args.command == "find-records":
            payload = find_records(
                Path(args.scope_root),
                args.record_type,
                parse_lookup_value(args.lookup_value_json),
                caller_domain=args.caller_domain,
                target_domain=args.target_domain,
                domain_policies=(
                    json.loads(args.domain_policies_json)
                    if args.domain_policies_json
                    else None
                ),
                caller_groups=json.loads(args.caller_groups_json),
            )
            return emit(payload, 1 if payload["status"] == "read_denied" else 0)
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
        if args.command == "invoke":
            payload = execute_invocation(
                load_invocation(Path(args.request)),
                registry_path=Path(args.registry_path),
                profile_path=Path(args.profile_path) if args.profile_path else None,
                mapping_path=Path(args.mapping_path) if args.mapping_path else None,
                domain_policies=json.loads(args.domain_policies_json) if args.domain_policies_json else None,
            )
            exit_code = 1 if payload.get("result", {}).get("status") == "read_denied" else 0
            return emit(payload, exit_code)
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
    except InvocationError as exc:
        return emit({"status": exc.code, "error": str(exc)}, 2)
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


def _config_payload(result) -> dict:
    return {
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


if __name__ == "__main__":
    raise SystemExit(main())
