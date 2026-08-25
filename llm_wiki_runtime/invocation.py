from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path

from .authorization import AuthorizationError, authorize_query, authorize_write
from .mapping import load_ingest_mapping, mapping_digest, validate_ingest_mapping
from .paths import validate_slug
from .policy import domain_policy_digest, load_domain_policies
from .principal_registry import PrincipalRegistryError, load_principal_registry, resolve_principal
from .profile import active_profile_path, load_active_profile, load_profile
from .record_lookup import find_records
from .runtime import append_profile_log, copy_source, load_context_pack, register_artifact, write_record


INVOCATION_VERSION = "v0.1"
REQUIRED_INVOCATION_FIELDS = frozenset(
    {"protocol_version", "request_id", "principal_id", "operation", "scope_root", "payload"}
)
OPTIONAL_INVOCATION_FIELDS = frozenset({"mapping_id"})
ALLOWED_OPERATIONS = frozenset(
    {"resolve", "find_records", "load_context", "copy_source", "write_record", "register_artifact", "append_log"}
)
READ_OPERATIONS = frozenset({"resolve", "find_records", "load_context"})
WRITE_OPERATIONS = ALLOWED_OPERATIONS - READ_OPERATIONS


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
    envelope = _validate_envelope(request, mapping_path, profile_path)
    scope_root = _scope_root(envelope["scope_root"])
    try:
        registry = load_principal_registry(registry_path)
        principal = resolve_principal(registry, envelope["principal_id"])
    except PrincipalRegistryError as exc:
        raise InvocationError(_principal_error_code(exc), str(exc)) from exc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise InvocationError("invalid_invocation", "principal registry is invalid") from exc

    operation = envelope["operation"]
    if operation in WRITE_OPERATIONS:
        return _execute_write_invocation(
            envelope,
            scope_root,
            registry,
            principal,
            profile_path,
            mapping_path,
            domain_policies,
        )

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
            "registry_digest": _canonical_registry_digest(_registry_digest(registry)),
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


def _validate_envelope(
    request: object, mapping_path: Path | None, profile_path: Path | None
) -> dict:
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
    if operation in WRITE_OPERATIONS and (mapping_path is None or profile_path is None or declared_mapping_id is None):
        raise InvocationError(
            "invalid_invocation",
            "write invocations require mapping_id, mapping_path, and profile_path",
        )
    return dict(request)


def _execute_write_invocation(
    envelope: dict,
    scope_root: Path,
    registry: dict,
    principal: dict,
    profile_path: Path | None,
    mapping_path: Path | None,
    domain_policies: dict | None,
) -> dict:
    profile, active_path, profile_digest = _load_write_profile(
        scope_root, profile_path, principal
    )
    mapping, mapping_observation = _load_write_mapping(
        envelope, mapping_path, registry, profile, envelope["principal_id"]
    )
    payload = _write_payload(envelope["operation"], envelope["payload"])
    policies = _domain_policies(domain_policies)
    try:
        authorization = authorize_write(
            principal_id=envelope["principal_id"],
            principal=principal,
            operation=envelope["operation"],
            product=_write_product(envelope["operation"], payload),
            mapping=mapping,
            profile=profile,
        )
    except AuthorizationError as exc:
        raise InvocationError(_write_authorization_error_code(exc), str(exc)) from exc

    authorization.update(
        {
            "registry_digest": _canonical_registry_digest(_registry_digest(registry)),
            "policy_digest": domain_policy_digest(policies),
            "profile_digest": profile_digest,
            "mapping_digest": mapping_observation["mapping_digest"],
        }
    )
    result = _delegate_write(envelope["operation"], scope_root, active_path, payload)
    return {
        "status": "ok",
        "request_id": envelope["request_id"],
        "operation": envelope["operation"],
        "principal": _principal_observation(envelope["principal_id"], principal),
        "authorization": authorization,
        "result": result,
    }


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


def _load_write_profile(scope_root: Path, profile_path: Path | None, principal: dict):
    if profile_path is None:
        raise InvocationError("invalid_invocation", "write invocations require profile_path")
    try:
        active_path = active_profile_path(scope_root)
        active_profile = load_active_profile(scope_root)
        packaged_profile = load_profile(profile_path)
        _assert_profile_binding(active_profile, principal)
        _assert_profile_binding(packaged_profile, principal)
        active_digest = _profile_digest(active_profile)
        if _profile_digest(packaged_profile) != active_digest:
            raise InvocationError("profile_mismatch", "packaged profile does not match the active profile")
        return active_profile, active_path, active_digest
    except InvocationError:
        raise
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


def _load_write_mapping(
    envelope: dict, mapping_path: Path | None, registry: dict, profile, principal_id: str
) -> tuple[dict, dict]:
    if mapping_path is None:
        raise InvocationError("invalid_invocation", "write invocations require mapping_path")
    try:
        mapping = load_ingest_mapping(mapping_path)
        if mapping["version"] != "v0.2" or "_legacy_owner_skill_id" in mapping:
            raise InvocationError("invalid_invocation", "write invocations do not accept legacy mappings")
        if mapping["id"] != envelope["mapping_id"]:
            raise InvocationError("invalid_invocation", "mapping_id does not match the mapping contract")
        if mapping["owner_principal_id"] != principal_id:
            raise InvocationError("mapping_owner_mismatch", "mapping owner does not match request principal")
        validation = validate_ingest_mapping(mapping, registry, profile)
    except InvocationError:
        raise
    except (OSError, ValueError, PrincipalRegistryError) as exc:
        raise InvocationError("invalid_invocation", f"mapping contract is invalid: {exc}") from exc
    return mapping, {"mapping_id": validation["mapping_id"], "mapping_digest": mapping_digest(mapping)}


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


def _write_payload(operation: str, payload: dict) -> dict:
    required = {
        "copy_source": {"source", "logical_path", "source_type", "metadata"},
        "write_record": {"record_type", "variables", "refs", "content_file"},
        "register_artifact": {"artifact_type", "record"},
        "append_log": {"log_type", "record"},
    }[operation]
    if set(payload) != required:
        raise InvocationError("invalid_invocation", f"{operation} payload fields are invalid")
    if operation == "copy_source":
        if not all(isinstance(payload[name], str) and payload[name] for name in ("source", "logical_path")):
            raise InvocationError("invalid_invocation", "copy_source paths must be non-empty strings")
        _safe_id(payload["source_type"], "source_type")
        if not isinstance(payload["metadata"], dict):
            raise InvocationError("invalid_invocation", "metadata must be an object")
    elif operation == "write_record":
        _safe_id(payload["record_type"], "record_type")
        if not isinstance(payload["variables"], dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in payload["variables"].items()
        ):
            raise InvocationError("invalid_invocation", "variables must be an object of strings")
        if not isinstance(payload["refs"], dict):
            raise InvocationError("invalid_invocation", "refs must be an object")
        if not isinstance(payload["content_file"], str) or not payload["content_file"]:
            raise InvocationError("invalid_invocation", "content_file must be a non-empty string")
    elif operation == "register_artifact":
        _safe_id(payload["artifact_type"], "artifact_type")
        record = payload["record"]
        if not isinstance(record, dict):
            raise InvocationError("invalid_invocation", "artifact record must be an object")
        _safe_id(record.get("artifact_id"), "artifact_id")
        record_artifact_type = _safe_id(record.get("artifact_type"), "artifact_type")
        if record_artifact_type != payload["artifact_type"]:
            raise InvocationError("invalid_invocation", "artifact record type must match artifact_type")
        return {"artifact_type": payload["artifact_type"], "record": copy.deepcopy(record)}
    else:
        _safe_id(payload["log_type"], "log_type")
        if not isinstance(payload["record"], dict):
            raise InvocationError("invalid_invocation", "record must be an object")
    return dict(payload)


def _write_product(operation: str, payload: dict) -> dict:
    if operation == "copy_source":
        return {"source_type": payload["source_type"]}
    if operation == "write_record":
        return {"record_type": payload["record_type"]}
    if operation == "register_artifact":
        return {"artifact_type": payload["artifact_type"]}
    return {"log_type": payload["log_type"]}


def _delegate_write(operation: str, scope_root: Path, active_profile: Path, payload: dict) -> dict:
    wiki_root = scope_root / ".llm-wiki"
    if operation == "copy_source":
        return copy_source(
            wiki_root,
            Path(payload["source"]),
            payload["logical_path"],
            payload["source_type"],
            payload["metadata"],
        )
    if operation == "write_record":
        return write_record(
            scope_root,
            active_profile,
            payload["record_type"],
            payload["variables"],
            payload["refs"],
            Path(payload["content_file"]),
        )
    if operation == "register_artifact":
        return register_artifact(wiki_root, payload["record"])
    return append_profile_log(scope_root, active_profile, payload["log_type"], payload["record"])


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


def _registry_digest(registry: dict) -> str:
    canonical = json.dumps(registry, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _canonical_registry_digest(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value):
        return "sha256:" + value
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        return value
    raise InvocationError("invalid_invocation", "registry_digest must be a canonical SHA-256 digest")


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


def _write_authorization_error_code(exc: AuthorizationError) -> str:
    if exc.code in {"mapping_owner_mismatch", "mapping_domain_mismatch", "profile_mismatch"}:
        return exc.code
    return "capability_denied"
