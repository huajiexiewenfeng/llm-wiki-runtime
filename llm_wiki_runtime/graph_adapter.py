from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .io import atomic_write_text
from .paths import validate_slug


TOP_LEVEL_FIELDS = {"version", "domain_id", "display_name", "defaults", "subtype_map"}
DEFAULT_FIELDS = {
    "label_field",
    "subtype_field",
    "summary_field",
    "status_field",
    "tags_field",
    "metadata_allowlist",
}


@dataclass(frozen=True)
class GraphFieldDefaults:
    label_field: str | None = None
    subtype_field: str = "record_type"
    summary_field: str | None = None
    status_field: str = "status"
    tags_field: str = "tags"
    metadata_allowlist: tuple[str, ...] = ()


@dataclass(frozen=True)
class GraphAdapter:
    version: str
    domain_id: str
    display_name: str
    defaults: GraphFieldDefaults
    subtype_map: dict[str, str]


def _parse_string(value: str, message: str) -> str:
    parsed = value.strip()
    if len(parsed) >= 2 and parsed[0] == parsed[-1] and parsed[0] in {"'", '"'}:
        parsed = parsed[1:-1]
    if not parsed or parsed.startswith(("[", "{", "!", "&", "*")):
        raise ValueError(message)
    return parsed


def _parse_flow_list(value: str) -> tuple[str, ...]:
    parsed = value.strip()
    if not parsed.startswith("[") or not parsed.endswith("]"):
        raise ValueError("graph adapter metadata_allowlist must be a flow list")
    body = parsed[1:-1].strip()
    if not body:
        return ()
    items = tuple(_parse_string(item, "invalid graph adapter metadata field") for item in body.split(","))
    return tuple(validate_slug(item) for item in items)


def _split_field(line: str, message: str) -> tuple[str, str]:
    if ":" not in line:
        raise ValueError(message)
    key, value = line.split(":", 1)
    key = key.strip()
    if not key:
        raise ValueError(message)
    return key, value.strip()


def default_graph_adapter(domain_id: str) -> GraphAdapter:
    domain_id = validate_slug(domain_id)
    return GraphAdapter(
        version="v0.1",
        domain_id=domain_id,
        display_name=domain_id,
        defaults=GraphFieldDefaults(),
        subtype_map={},
    )


def load_graph_adapter(path: Path, expected_domain_id: str) -> GraphAdapter:
    expected_domain_id = validate_slug(expected_domain_id)
    top_level: dict[str, str] = {}
    defaults: dict[str, object] = {}
    subtype_map: dict[str, str] = {}
    section: str | None = None

    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw:
            raise ValueError(f"unsupported graph adapter nesting on line {line_number}")
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if indent == 0:
            key, value = _split_field(stripped, f"invalid graph adapter field on line {line_number}")
            if key not in TOP_LEVEL_FIELDS:
                raise ValueError(f"unsupported graph adapter field: {key}")
            if key in top_level:
                raise ValueError(f"duplicate graph adapter field: {key}")
            if key in {"defaults", "subtype_map"}:
                if value:
                    raise ValueError(f"unsupported graph adapter nesting on line {line_number}")
                top_level[key] = ""
                section = key
            else:
                top_level[key] = _parse_string(value, f"invalid graph adapter field: {key}")
                section = None
            continue

        if indent != 2 or section is None:
            raise ValueError(f"unsupported graph adapter nesting on line {line_number}")
        key, value = _split_field(stripped, f"invalid graph adapter field on line {line_number}")
        if section == "defaults":
            if key not in DEFAULT_FIELDS:
                raise ValueError(f"unsupported graph adapter defaults field: {key}")
            if key in defaults:
                raise ValueError(f"duplicate graph adapter defaults field: {key}")
            if key == "metadata_allowlist":
                defaults[key] = _parse_flow_list(value)
            else:
                defaults[key] = validate_slug(_parse_string(value, f"invalid graph adapter defaults field: {key}"))
        else:
            if key in subtype_map:
                raise ValueError(f"duplicate graph adapter subtype field: {key}")
            subtype_map[validate_slug(key)] = validate_slug(
                _parse_string(value, f"invalid graph adapter subtype field: {key}")
            )

    version = top_level.get("version")
    if version != "v0.1":
        raise ValueError(f"unsupported graph adapter version: {version!r}")
    domain_id = top_level.get("domain_id")
    if domain_id is None:
        raise ValueError("graph adapter domain_id is required")
    domain_id = validate_slug(domain_id)
    if domain_id != expected_domain_id:
        raise ValueError("graph adapter domain_id does not match expected domain")

    return GraphAdapter(
        version=version,
        domain_id=domain_id,
        display_name=top_level.get("display_name", domain_id),
        defaults=GraphFieldDefaults(
            label_field=defaults.get("label_field"),
            subtype_field=str(defaults.get("subtype_field", "record_type")),
            summary_field=defaults.get("summary_field"),
            status_field=str(defaults.get("status_field", "status")),
            tags_field=str(defaults.get("tags_field", "tags")),
            metadata_allowlist=tuple(defaults.get("metadata_allowlist", ())),
        ),
        subtype_map=subtype_map,
    )


def graph_adapter_snapshot_path(wiki_root: Path, domain_id: str) -> Path:
    return wiki_root / ".meta" / "graph-adapters" / f"{validate_slug(domain_id)}.yml"


def snapshot_graph_adapter(profile_path: Path, wiki_root: Path, domain_id: str) -> GraphAdapter:
    source_path = profile_path.with_name("graph-adapter.yml")
    target_path = graph_adapter_snapshot_path(wiki_root, domain_id)
    if not source_path.exists():
        target_path.unlink(missing_ok=True)
        return default_graph_adapter(domain_id)

    adapter = load_graph_adapter(source_path, domain_id)
    atomic_write_text(target_path, source_path.read_text(encoding="utf-8"))
    return adapter
