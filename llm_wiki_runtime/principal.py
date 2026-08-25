from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contract_yaml import load_contract_document
from .paths import validate_slug


PRINCIPAL_VERSION = "v0.1"
SUPPORTED_KINDS = frozenset({"skill", "workload"})
SUPPORTED_WORKLOAD_ROLES = frozenset({"domain_harness"})
CONTRACT_KINDS = ("record_type", "artifact_type", "log_type")


def principal_contract_digest(contract: dict) -> str:
    body = {key: value for key, value in contract.items() if key != "_path"}
    canonical = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def load_principal_manifest(path: Path) -> dict:
    contract = load_contract_document(path, "principal")
    validate_principal_contract(contract, expected_kind="workload")
    return contract


def principal_from_scp(scp: dict) -> dict:
    contract = {
        "principal_version": PRINCIPAL_VERSION,
        "principal": {
            "id": scp["skill"]["id"],
            "kind": "skill",
            "domain": scp["skill"]["domain"],
        },
        "llm_wiki": dict(scp.get("llm_wiki", {})),
        "trust": dict(scp.get("trust", {})),
        "query": dict(scp.get("query", {"supports": []})),
        "ingest": dict(scp.get("ingest", {"produces": []})),
        "_path": scp.get("_path"),
    }
    validate_principal_contract(contract, expected_kind="skill")
    return contract


def validate_principal_contract(contract: dict, expected_kind: str | None = None) -> None:
    if contract.get("principal_version") != PRINCIPAL_VERSION:
        raise ValueError(f"unsupported principal version: {contract.get('principal_version')!r}")

    principal = contract.get("principal")
    if not isinstance(principal, dict):
        raise ValueError("principal identity must be a mapping")
    kind = principal.get("kind")
    if kind not in SUPPORTED_KINDS:
        raise ValueError(f"unsupported principal kind: {kind!r}")
    if expected_kind is not None and kind != expected_kind:
        raise ValueError(f"expected {expected_kind} principal, got {kind!r}")

    required_keys = {"id", "kind", "domain"}
    if kind == "workload":
        required_keys.add("role")
    if set(principal) != required_keys:
        raise ValueError("principal identity fields do not match its kind")
    validate_slug(principal["id"])
    validate_slug(principal["domain"])

    if kind == "workload" and principal["role"] not in SUPPORTED_WORKLOAD_ROLES:
        raise ValueError(f"unsupported workload role: {principal['role']!r}")

    query = contract.get("query")
    if not isinstance(query, dict) or query.get("primary_domain") != principal["domain"]:
        raise ValueError("query primary domain mismatch")

    ingest = contract.get("ingest")
    produces = ingest.get("produces") if isinstance(ingest, dict) else None
    if not isinstance(produces, list):
        raise ValueError("ingest produces must be a list")
    for produced in produces:
        if not isinstance(produced, dict):
            raise ValueError("produced contract must be a mapping")
        if produced.get("domain") != principal["domain"]:
            raise ValueError("produce domain mismatch")
        if sum(key in produced for key in CONTRACT_KINDS) != 1:
            raise ValueError("produced contract must declare exactly one contract kind")
