from __future__ import annotations

from pathlib import Path

from .profile import parse_scalar


IDENTITY_SECTIONS = frozenset({"skill", "principal"})


def load_contract_document(path: Path, identity_section: str) -> dict:
    if identity_section not in IDENTITY_SECTIONS:
        raise ValueError(f"unsupported identity section: {identity_section}")

    lines = path.read_text(encoding="utf-8").splitlines()
    doc: dict = {
        identity_section: {},
        "llm_wiki": {},
        "trust": {},
        "query": {"supports": []},
        "ingest": {"produces": []},
        "_path": str(path),
    }
    section: str | None = None
    in_supports = False
    in_produces = False
    current_item: dict | None = None

    def flush_item() -> None:
        nonlocal current_item
        if current_item is None:
            return
        if in_supports:
            doc["query"]["supports"].append(current_item)
        elif in_produces:
            doc["ingest"]["produces"].append(current_item)
        current_item = None

    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            flush_item()
            section = stripped[:-1]
            in_supports = False
            in_produces = False
            continue
        if indent == 0 and ":" in stripped:
            key, value = stripped.split(":", 1)
            doc[key] = parse_scalar(value)
            continue
        if section in {identity_section, "llm_wiki", "trust"} and indent == 2 and ":" in stripped:
            key, value = stripped.split(":", 1)
            doc[section][key] = parse_scalar(value)
            continue
        if section == "query":
            if indent == 2 and stripped == "supports:":
                in_supports = True
                continue
            if indent == 2 and ":" in stripped:
                key, value = stripped.split(":", 1)
                doc["query"][key] = parse_scalar(value)
                continue
            if in_supports and stripped.startswith("- "):
                flush_item()
                current_item = {}
                key, value = stripped[2:].split(":", 1)
                current_item[key] = parse_scalar(value)
                continue
            if in_supports and current_item is not None and ":" in stripped:
                key, value = stripped.split(":", 1)
                current_item[key] = parse_scalar(value)
                continue
        if section == "ingest":
            if indent == 2 and stripped == "produces:":
                in_produces = True
                continue
            if in_produces and stripped.startswith("- "):
                flush_item()
                current_item = {}
                key, value = stripped[2:].split(":", 1)
                current_item[key] = parse_scalar(value)
                continue
            if in_produces and current_item is not None and ":" in stripped:
                key, value = stripped.split(":", 1)
                current_item[key] = parse_scalar(value)
                continue
    flush_item()
    return doc
