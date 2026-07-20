"""A deliberately bounded parser for the metadata subset used by domain files."""

from __future__ import annotations

import json
import re
from typing import TypeAlias


FrontmatterScalar: TypeAlias = str | int | float | bool | None
FrontmatterValue: TypeAlias = FrontmatterScalar | list[FrontmatterScalar]

_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
_INTEGER_RE = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_FLOAT_RE = re.compile(
    r"-?(?:(?:0|[1-9][0-9]*)\.[0-9]+|(?:0|[1-9][0-9]*)[eE][+-]?[0-9]+|(?:0|[1-9][0-9]*)\.[0-9]+[eE][+-]?[0-9]+)\Z"
)


def parse_frontmatter(text: str) -> tuple[dict[str, FrontmatterValue], int]:
    """Parse a leading, restricted YAML-like metadata block without YAML support."""
    if not isinstance(text, str) or not text.startswith("---"):
        return {}, 0

    lines = text.splitlines(keepends=True)
    if not lines or _line_content(lines[0]) != "---":
        raise ValueError("frontmatter opening delimiter must be exactly '---'")

    metadata: dict[str, FrontmatterValue] = {}
    offset = len(lines[0])
    for line in lines[1:]:
        content = _line_content(line)
        offset += len(line)
        if content == "---":
            return metadata, offset
        if "\t" in content:
            raise ValueError("frontmatter must not contain tabs")
        if not content:
            continue

        key, separator, raw_value = content.partition(":")
        if not separator or not _KEY_RE.fullmatch(key) or raw_value[:1] not in {" ", ""}:
            raise ValueError("frontmatter entries must be simple key/value pairs")
        raw_value = raw_value.lstrip(" ")
        if not raw_value:
            raise ValueError("frontmatter values must be explicit scalars or flow lists")
        if key in metadata:
            raise ValueError(f"duplicate frontmatter key: {key}")
        metadata[key] = _parse_value(raw_value)

    raise ValueError("frontmatter block is missing a closing delimiter")


def _line_content(line: str) -> str:
    return line.rstrip("\r\n")


def _parse_value(value: str) -> FrontmatterValue:
    if value.startswith("["):
        return _parse_flow_list(value)
    if value.startswith(("{", "&", "*", "!", "|", ">")) or any(character in value for character in "{}[]"):
        raise ValueError("unsupported frontmatter value")
    return _parse_scalar(value)


def _parse_flow_list(value: str) -> list[FrontmatterScalar]:
    if not value.endswith("]"):
        raise ValueError("malformed flow list")
    contents = value[1:-1].strip()
    if not contents:
        return []
    items = _split_flow_items(contents)
    return [_parse_scalar(item.strip()) for item in items]


def _split_flow_items(contents: str) -> list[str]:
    items: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(contents):
        character = contents[index]
        if quote == '"':
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif quote == "'":
            if character == quote:
                if index + 1 < len(contents) and contents[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif character in {"'", '"'}:
            quote = character
        elif character in "{}[]":
            raise ValueError("nested flow values are not supported")
        elif character == ",":
            item = contents[start:index].strip()
            if not item:
                raise ValueError("flow lists must not contain empty items")
            items.append(item)
            start = index + 1
        index += 1

    if quote is not None or escaped:
        raise ValueError("unterminated quoted scalar")
    item = contents[start:].strip()
    if not item:
        raise ValueError("flow lists must not contain empty items")
    items.append(item)
    return items


def _parse_scalar(value: str) -> FrontmatterScalar:
    if not value or "\n" in value or "\r" in value or "\t" in value:
        raise ValueError("frontmatter scalar must be a single line")
    if value.startswith('"'):
        return _parse_double_quoted(value)
    if value.startswith("'"):
        return _parse_single_quoted(value)
    if value in {"true", "false"}:
        return value == "true"
    if value == "null":
        return None
    if _INTEGER_RE.fullmatch(value):
        return int(value)
    if _FLOAT_RE.fullmatch(value):
        return float(value)
    if value.startswith(("&", "*", "!", "|", ">")) or ":" in value or "#" in value:
        raise ValueError("unsupported plain scalar")
    return value


def _parse_double_quoted(value: str) -> str:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("invalid double-quoted scalar") from error
    if not isinstance(parsed, str) or "\n" in parsed or "\r" in parsed:
        raise ValueError("double-quoted scalar must be a single line string")
    return parsed


def _parse_single_quoted(value: str) -> str:
    if len(value) < 2 or not value.endswith("'"):
        raise ValueError("invalid single-quoted scalar")
    contents = value[1:-1]
    if "'" in contents.replace("''", ""):
        raise ValueError("invalid single-quoted scalar")
    return contents.replace("''", "'")
