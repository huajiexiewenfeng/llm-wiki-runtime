from __future__ import annotations

from collections.abc import Mapping

from .policy import assert_read_allowed, domain_policy_digest


class AuthorizationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


QUERY_OPERATIONS = frozenset({"resolve", "find_records", "load_context"})
WRITE_OPERATION_KIND = {
    "write_record": "record_type",
    "register_artifact": "artifact_type",
    "append_log": "log_type",
}


def authorize_query(*, principal, operation, target_domain, domain_policies, caller_groups) -> dict:
    if operation not in QUERY_OPERATIONS:
        raise AuthorizationError("unsupported_operation", f"unsupported query operation: {operation!r}")

    caller_domain = principal.get("domain")
    supports = principal.get("supports", [])
    if target_domain != caller_domain and target_domain not in supports:
        raise AuthorizationError("support_not_declared", f"principal does not declare support for domain: {target_domain!r}")

    allowed, reason = assert_read_allowed(caller_domain, target_domain, domain_policies, caller_groups)
    if not allowed:
        raise AuthorizationError("read_denied", f"read denied: {reason}")

    return {
        "operation": operation,
        "domain": target_domain,
        "decision": "allowed",
        "policy_digest": domain_policy_digest(domain_policies),
    }


def authorize_write(*, principal_id, principal, operation, product, mapping, profile) -> dict:
    if mapping.get("owner_principal_id") != principal_id:
        raise AuthorizationError("mapping_owner_mismatch", "mapping owner does not match principal")
    if mapping.get("domain") != principal.get("domain"):
        raise AuthorizationError("mapping_domain_mismatch", "mapping domain does not match principal domain")

    if operation == "copy_source":
        _require_typed_product(product, "source_type")
        if product["source_type"] not in mapping.get("source_types", []):
            raise AuthorizationError("product_not_declared", "source type is not declared by mapping")
    else:
        kind = WRITE_OPERATION_KIND.get(operation)
        if kind is None:
            raise AuthorizationError("unsupported_operation", f"unsupported write operation: {operation!r}")
        _require_typed_product(product, kind)
        if not _contains_product(principal.get("produces", []), product) or not _contains_product(
            mapping.get("produces", []), product
        ):
            raise AuthorizationError("product_not_declared", "product is not declared by principal and mapping")
        if not _profile_supports(profile, kind, product[kind]):
            raise AuthorizationError("profile_mismatch", "product is not declared by profile")

    return {
        "operation": operation,
        "domain": principal["domain"],
        "decision": "allowed",
    }


def _require_typed_product(product, kind: str) -> None:
    if not isinstance(product, Mapping) or set(product) != {kind} or not isinstance(product[kind], str) or not product[kind]:
        raise AuthorizationError("invalid_product", f"product must declare one non-empty {kind}")


def _contains_product(products, product) -> bool:
    kind, value = next(iter(product.items()))
    return any(isinstance(candidate, Mapping) and candidate.get(kind) == value for candidate in products)


def _profile_supports(profile, kind: str, value: str) -> bool:
    if kind == "record_type":
        return value in profile.write_rules
    if kind == "artifact_type":
        return value in profile.artifact_types
    return value in profile.log_rules
