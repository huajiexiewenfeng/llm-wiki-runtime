from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .io import atomic_write_text


EXCERPT_SEPARATOR = "\n\n---\n\n"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CN_MOBILE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
ID_PREFIX_RE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")


def normalize_evidence_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", normalized).strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scan_sensitive_patterns(text: str) -> list[str]:
    flags: list[str] = []
    if EMAIL_RE.search(text):
        flags.append("email")
    if CN_MOBILE_RE.search(text):
        flags.append("phone")
    return flags


def validate_confirmed_at(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("confirmed_at must be a non-empty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("confirmed_at must be a valid ISO-8601 timestamp") from exc
    if parsed.utcoffset() is None:
        raise ValueError("confirmed_at must include a timezone offset")


def prepare_excerpt(
    items: list[dict],
    selections: list[dict],
    id_prefix: str,
    confirmed_at: str,
) -> dict:
    validate_confirmed_at(confirmed_at)
    if not isinstance(id_prefix, str) or not ID_PREFIX_RE.fullmatch(id_prefix):
        raise ValueError("id_prefix must contain lowercase letters, digits, or hyphens")
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list")
    if not isinstance(selections, list) or not selections:
        raise ValueError("selections must be a non-empty list")

    item_index: dict[tuple[str, str], dict] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("thread item must be an object")
        key = (item.get("turn_id"), item.get("item_id"))
        if not all(isinstance(value, str) and value for value in key):
            raise ValueError("thread item requires turn_id and item_id")
        if key in item_index:
            raise ValueError(f"duplicate thread item: {key[0]}/{key[1]}")
        if not isinstance(item.get("thread_id"), str) or not item["thread_id"]:
            raise ValueError("thread item requires thread_id")
        if type(item.get("turn_order")) is not int or type(item.get("item_order")) is not int:
            raise ValueError("thread item requires integer turn_order and item_order")
        if not isinstance(item.get("text"), str):
            raise ValueError("thread item text must be a string")
        item_index[key] = item

    prepared: list[tuple[int, int, int, str, dict, str]] = []
    thread_ids: set[str] = set()
    for selection in selections:
        if not isinstance(selection, dict):
            raise ValueError("selection must be an object")
        turn_id = selection.get("turn_id")
        item_id = selection.get("item_id")
        item = item_index.get((turn_id, item_id))
        if item is None:
            raise ValueError(f"selected thread item not found: {turn_id}/{item_id}")
        start = selection.get("start")
        end = selection.get("end")
        text = item["text"]
        if type(start) is not int or type(end) is not int or start < 0 or end <= start or end > len(text):
            raise ValueError(f"invalid excerpt range: {turn_id}/{item_id}:{start}-{end}")
        excerpt = normalize_evidence_text(text[start:end])
        if not excerpt:
            raise ValueError(f"empty excerpt range: {turn_id}/{item_id}:{start}-{end}")
        provenance = {
            "turn_id": turn_id,
            "item_id": item_id,
            "start": start,
            "end": end,
            "original_message_checksum": "sha256:" + sha256_text(text),
        }
        prepared.append(
            (
                item["turn_order"],
                item["item_order"],
                start,
                excerpt,
                provenance,
                item["thread_id"],
            )
        )
        thread_ids.add(item["thread_id"])

    if len(thread_ids) != 1:
        raise ValueError("excerpt selections must belong to a single thread")
    prepared.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
    body = EXCERPT_SEPARATOR.join(entry[3] for entry in prepared)
    digest = sha256_text(body)
    metadata = {
        "excerpted": True,
        "thread_id": prepared[0][5],
        "selections": [entry[4] for entry in prepared],
        "confirmed_at": confirmed_at,
    }
    return {
        "body": body,
        "version_id": f"{id_prefix}-{digest[:12]}",
        "body_checksum": "sha256:" + digest,
        "metadata": metadata,
        "risk_flags": scan_sensitive_patterns(body),
    }


def write_excerpt_snapshot(payload: dict, output: Path) -> Path:
    metadata = payload["metadata"]
    selections_json = json.dumps(metadata["selections"], ensure_ascii=False, sort_keys=True)
    text = "\n".join(
        [
            "---",
            "source_type: codex_thread_jd_excerpt",
            f"version_id: {payload['version_id']}",
            f"body_checksum: {payload['body_checksum']}",
            f"thread_id: {metadata['thread_id']}",
            f"confirmed_at: {metadata['confirmed_at']}",
            "excerpted: true",
            f"selections_json: {selections_json}",
            "---",
            "",
            payload["body"],
            "",
        ]
    )
    atomic_write_text(output, text)
    return output
