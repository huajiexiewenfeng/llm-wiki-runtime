from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .authorization import AuthorizationError, authorize_query
from .mapping import load_ingest_mapping, mapping_digest, validate_ingest_mapping
from .paths import validate_slug
from .policy import load_domain_policies
from .principal_registry import PrincipalRegistryError, load_principal_registry, resolve_principal
from .profile import active_profile_path, load_active_profile, load_profile
from .record_lookup import find_records
from .runtime import load_context_pack


INVOCATION_VERSION = "v0.1"
REQUIRED_INVOCATION_FIELDS = frozenset(
    {"protocol_version", "request_id", "principal_id", "operation", "scope_root", "payload"}
)
OPTIONAL_INVOCATION_FIELDS = frozenset({"mapping_id"})
ALLOWED_OPERATIONS = frozenset(
    {"resolve", "find_records", "load_context", "copy_source", "write_record", "register_artifact", "append_log"}
)
READ_OPERATIONS = frozenset({"resolve", "find_records", "load_context"})


class InvocationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def load_invocation(path: Path, max_bytes: int = 1_000_000) -> dict:
    if type(max_bytes) is not int or max_bytes < 1:
        raise InvocationError("invalid_invocation", "max_bytes must be a positive integer")
    try:
        with path.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise InvocationError("invalid_invocation", "invocation request exceeds the byte limit")
        value = json.loads(raw.decode("utf-8"))
    except InvocationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvocationError("invalid_invocation", "invocation request must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise InvocationError("invalid_invocation", "invocation request must be a JSON object")
    return value


def execute_invocation(
    request: dict,
    registry_path: Path,
    profile_path: Path | None = None,
    mapping_path: Path | None = None,
    domain_policies: dict | None = None,
) -> dict:
    envelope = _validate_envelope(request, mapping_path)
    scope_root = _scope_root(envelope["scope_root"])
    try:
        registry = load_principal_registry(registry_path)
        principal = resolve_principal(registry, envelope["principal_id"])
    except PrincipalRegistryError as exc:
        raise InvocationError(_principal_error_code(exc), str(exc)) from exc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise InvocationError("invalid_invocation", "principal registry is invalid") from exc

    operation = envelope["operation"]
    if operation not in READ_OPERATIONS:
        raise InvocationError("operation_not_allowed", f"read invocation does not support operation: {operation}")

    profile, resolved_profile_path = _load_bound_profile(
        scope_root, profile_path, principal, operation
    )
    payload = _normalize_payload(operation, envelope["payload"], profile)
    target_domain = _target_domain(payload, principal["domain"])
    policies = _domain_policies(domain_policies)
    try:
        authorization = authorize_query(
            principal=principal,
            operation=operation,
            target_domain=target_domain,
            domain_policies=policies,
            caller_groups=[],
        )
    except AuthorizationError as exc:
        raise InvocationError(_authorization_error_code(exc), str(exc)) from exc

    mapping_observation = _validate_mapping(
        envelope, mapping_path, registry, profile, envelope["principal_id"]
    )

    authorization.update(
        {
            "principal_contract_digest": principal["contract_digest"],
            "profile_digest": _profile_digest(profile),
        }
    )
    if mapping_observation is not None:
        authorization["mapping_digest"] = mapping_observation["mapping_digest"]

    if operation == "resolve":
        result = {
            "status": "ready",
            "profile_id": profile.id,
            "profile_path": str(resolved_profile_path),
        }
    elif operation == "find_records":
        result = find_records(
            scope_root,
            payload["record_type"],
            payload["lookup_value"],
            caller_domain=principal["domain"],
            target_domain=target_domain,
            domain_policies=policies,
            caller_groups=[],
        )
    else:
        result = load_context_pack(
            scope_root / ".llm-wiki",
            payload["include"],
            payload["exclude"],
            payload["max_files"],
            payload["max_chars_per_file"],
            payload["path_filters"],
            payload["glob_filters"],
            payload["order"],
            payload["policy"],
            principal["domain"],
            target_domain,
            policies,
            [],
        )

    return {
        "status": "ok",
        "request_id": envelope["request_id"],
        "operation": operation,
        "principal": _principal_observation(envelope["principal_id"], principal),
        "authorization": authorization,
        "result": result,
    }


def _validate_envelope(request: object, mapping_path: Path | None) -> dict:
    if not isinstance(request, dict):
        raise InvocationError("invalid_invocation", "invocation request must be an object")
    fields = set(request)
    unknown = fields - REQUIRED_INVOCATION_FIELDS - OPTIONAL_INVOCATION_FIELDS
    missing = REQUIRED_INVOCATION_FIELDS - fields
    if unknown or missing:
        raise InvocationError("invalid_invocation", "invocation request fields do not match the protocol")
    if request.get("protocol_version") != INVOCATION_VERSION:
        raise InvocationError("invalid_invocation", "unsupported invocation protocol version")
    for name in ("request_id", "principal_id"):
        _safe_id(request.get(name), name)
    operation = request.get("operation")
    if not isinstance(operation, str) or operation not in ALLOWED_OPERATIONS:
        raise InvocationError("operation_not_allowed", f"operation is not allowed: {operation!r}")
    if not isinstance(request.get("scope_root"), str):
        raise InvocationError("invalid_invocation", "scope_root must be a string")
    if not isinstance(request.get("payload"), dict):
        raise InvocationError("invalid_invocation", "payload must be an object")

    declared_mapping_id = request.get("mapping_id")
    if mapping_path is None and declared_mapping_id is not None:
        raise InvocationError("invalid_invocation", "mapping_id requires mapping_path")
    if mapping_path is not None and declared_mapping_id is None:
        raise InvocationError("invalid_invocation", "mapping_path requires mapping_id")
    if declared_mapping_id is not None:
        _safe_id(declared_mapping_id, "mapping_id")
    return dict(request)


def _scope_root(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or not path.is_dir():
        raise InvocationError("invalid_invocation", "scope_root must be an existing absolute directory")
    return path


def _load_bound_profile(scope_root: Path, profile_path: Path | None, principal: dict, operation: str):
    try:
        active_path = active_profile_path(scope_root)
        active_profile = load_active_profile(scope_root)
        _assert_profile_binding(active_profile, principal)
        if profile_path is None:
            return active_profile, active_path
        explicit_profile = load_profile(profile_path)
        _assert_profile_binding(explicit_profile, principal)
        if operation == "resolve":
            return explicit_profile, profile_path
        return active_profile, active_path
    except (OSError, ValueError) as exc:
        raise InvocationError("invalid_invocation", f"active profile is invalid: {exc}") from exc


def _assert_profile_binding(profile, principal: dict) -> None:
    declared_profile = principal.get("profile")
    if not isinstance(declared_profile, str) or profile.id != declared_profile:
        raise ValueError("profile does not match the principal contract")


def _validate_mapping(
    envelope: dict, mapping_path: Path | None, registry: dict, profile, principal_id: str
) -> dict | None:
    if mapping_path is None:
        return None
    try:
        mapping = load_ingest_mapping(mapping_path)
        if mapping["id"] != envelope["mapping_id"]:
            raise InvocationError("invalid_invocation", "mapping_id does not match the mapping contract")
        if mapping["owner_principal_id"] != principal_id:
            raise InvocationError("mapping_owner_mismatch", "mapping owner does not match request principal")
        validation = validate_ingest_mapping(mapping, registry, profile)
    except InvocationError:
        raise
    except (OSError, ValueError, PrincipalRegistryError) as exc:
        raise InvocationError("invalid_invocation", f"mapping contract is invalid: {exc}") from exc
    return {"mapping_id": validation["mapping_id"], "mapping_digest": mapping_digest(mapping)}


def _target_domain(payload: dict, principal_domain: str) -> str:
    value = payload.get("target_domain", principal_domain)
    return _safe_id(value, "target_domain")


def _require_empty_payload(payload: dict) -> None:
    if payload:
        raise InvocationError("invalid_invocation", "resolve payload must be empty")


def _normalize_payload(operation: str, payload: dict, profile) -> dict:
    if operation == "resolve":
        _require_empty_payload(payload)
        return {}
    if operation == "find_records":
        return _find_records_payload(payload)
    return _load_context_payload(payload, profile)


def _domain_policies(value: dict | None) -> dict:
    if value is not None and not isinstance(value, dict):
        raise InvocationError("invalid_invocation", "domain_policies must be an object")
    try:
        policies = load_domain_policies(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise InvocationError("invalid_invocation", "domain_policies must be an object") from exc
    if not isinstance(policies, dict):
        raise InvocationError("invalid_invocation", "domain_policies must be an object")
    return policies


def _find_records_payload(payload: dict) -> dict:
    allowed = {"record_type", "lookup_value", "target_domain"}
    if set(payload) - allowed or {"record_type", "lookup_value"} - set(payload):
        raise InvocationError("invalid_invocation", "find_records payload fields are invalid")
    _safe_id(payload["record_type"], "record_type")
    if payload["lookup_value"] is None or isinstance(payload["lookup_value"], (list, dict)):
        raise InvocationError("invalid_invocation", "lookup_value must be a non-null scalar")
    if isinstance(payload["lookup_value"], float) and not _finite(payload["lookup_value"]):
        raise InvocationError("invalid_invocation", "lookup_value must be finite")
    if not isinstance(payload["lookup_value"], (str, int, float, bool)):
        raise InvocationError("invalid_invocation", "lookup_value must be a scalar")
    return payload


def _load_context_payload(payload: dict, profile) -> dict:
    allowed = {
        "include", "exclude", "max_files", "max_chars_per_file", "path_filters",
        "glob_filters", "order", "policy", "target_domain",
    }
    if set(payload) - allowed:
        raise InvocationError("invalid_invocation", "load_context payload fields are invalid")
    result = {
        "include": payload.get("include", profile.context_pack.include),
        "exclude": payload.get("exclude", profile.context_pack.exclude),
        "max_files": payload.get("max_files", profile.context_pack.max_files),
        "max_chars_per_file": payload.get("max_chars_per_file", profile.context_pack.max_chars_per_file),
        "path_filters": payload.get("path_filters", []),
        "glob_filters": payload.get("glob_filters", []),
        "order": payload.get("order", "path_asc"),
        "policy": payload.get("policy"),
    }
    for name in ("include", "exclude", "path_filters", "glob_filters"):
        if not _string_list(result[name]):
            raise InvocationError("invalid_invocation", f"{name} must be a list of strings")
    for name in ("max_files", "max_chars_per_file"):
        if type(result[name]) is not int or result[name] < 1:
            raise InvocationError("invalid_invocation", f"{name} must be a positive integer")
    if result["order"] not in {"path_asc", "mtime_desc"}:
        raise InvocationError("invalid_invocation", "load_context order is invalid")
    if result["policy"] is not None and result["policy"] not in {"trusted_content", "data_only"}:
        raise InvocationError("invalid_invocation", "load_context policy is invalid")
    return result


def _safe_id(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise InvocationError("invalid_invocation", f"{name} must be a safe identifier")
    try:
        return validate_slug(value)
    except ValueError as exc:
        raise InvocationError("invalid_invocation", f"{name} must be a safe identifier") from exc


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _finite(value: float) -> bool:
    return value != float("inf") and value != float("-inf") and value == value


def _profile_digest(profile) -> str:
    canonical = json.dumps(asdict(profile), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _principal_observation(principal_id: str, principal: dict) -> dict:
    return {
        "id": principal_id,
        "kind": principal["kind"],
        "role": principal.get("role"),
        "domain": principal["domain"],
        "profile": principal.get("profile"),
        "contract_digest": principal["contract_digest"],
    }


def _principal_error_code(exc: PrincipalRegistryError) -> str:
    if exc.code in {"principal_not_found", "principal_contract_stale"}:
        return exc.code
    return "invalid_invocation"


def _authorization_error_code(exc: AuthorizationError) -> str:
    if exc.code == "support_not_declared":
        return "principal_domain_mismatch"
    return "capability_denied"
