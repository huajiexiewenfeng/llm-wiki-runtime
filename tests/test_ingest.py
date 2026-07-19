import json
import unicodedata

import pytest

from llm_wiki_runtime.ingest import (
    EXCERPT_SEPARATOR,
    normalize_evidence_text,
    prepare_excerpt,
    write_excerpt_snapshot,
)


CONFIRMED_AT = "2026-07-18T10:00:00+08:00"


def test_normalize_evidence_text_is_deterministic():
    decomposed = "  Cafe\u0301\r\nSenior Java\r  "
    expected = unicodedata.normalize("NFC", "Cafe\u0301\nSenior Java")
    assert normalize_evidence_text(decomposed) == expected


def test_prepare_excerpt_hashes_confirmed_verbatim_ranges_only():
    text = "Candidate discussion. JD: Senior Java Developer"
    items = [
        {
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "item_id": "item-1",
            "turn_order": 1,
            "item_order": 1,
            "text": text,
        }
    ]
    selections = [
        {
            "turn_id": "turn-1",
            "item_id": "item-1",
            "start": text.index("JD:"),
            "end": len(text),
        }
    ]

    first = prepare_excerpt(items, selections, "jd", CONFIRMED_AT)
    second = prepare_excerpt(items, selections, "jd", "2026-07-19T09:00:00+08:00")

    assert first["body"] == "JD: Senior Java Developer"
    assert first["version_id"] == second["version_id"]
    assert first["body_checksum"] == second["body_checksum"]
    assert first["metadata"]["excerpted"] is True
    assert first["metadata"]["confirmed_at"] == CONFIRMED_AT
    assert first["metadata"]["selections"][0]["item_id"] == "item-1"
    assert first["metadata"]["selections"][0]["original_message_checksum"].startswith("sha256:")


def test_prepare_excerpt_sorts_multiple_ranges_by_thread_order():
    items = [
        {
            "thread_id": "thread-1",
            "turn_id": "turn-2",
            "item_id": "item-2",
            "turn_order": 2,
            "item_order": 1,
            "text": "Responsibilities: build services.",
        },
        {
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "item_id": "item-1",
            "turn_order": 1,
            "item_order": 1,
            "text": "Title: Senior Java Developer",
        },
    ]
    selections = [
        {"turn_id": "turn-2", "item_id": "item-2", "start": 0, "end": len(items[0]["text"])},
        {"turn_id": "turn-1", "item_id": "item-1", "start": 0, "end": len(items[1]["text"])},
    ]

    payload = prepare_excerpt(items, selections, "jd", CONFIRMED_AT)

    assert payload["body"] == EXCERPT_SEPARATOR.join([items[1]["text"], items[0]["text"]])
    assert [item["item_id"] for item in payload["metadata"]["selections"]] == ["item-1", "item-2"]


def test_prepare_excerpt_rejects_invalid_character_range():
    items = [
        {
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "item_id": "item-1",
            "turn_order": 1,
            "item_order": 1,
            "text": "JD",
        }
    ]
    with pytest.raises(ValueError, match="invalid excerpt range"):
        prepare_excerpt(
            items,
            [{"turn_id": "turn-1", "item_id": "item-1", "start": 0, "end": 99}],
            "jd",
            CONFIRMED_AT,
        )


def test_prepare_excerpt_rejects_cross_thread_selection():
    items = [
        {
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "item_id": "item-1",
            "turn_order": 1,
            "item_order": 1,
            "text": "JD one",
        },
        {
            "thread_id": "thread-2",
            "turn_id": "turn-2",
            "item_id": "item-2",
            "turn_order": 2,
            "item_order": 1,
            "text": "JD two",
        },
    ]
    selections = [
        {"turn_id": "turn-1", "item_id": "item-1", "start": 0, "end": 6},
        {"turn_id": "turn-2", "item_id": "item-2", "start": 0, "end": 6},
    ]

    with pytest.raises(ValueError, match="single thread"):
        prepare_excerpt(items, selections, "jd", CONFIRMED_AT)


def test_prepare_excerpt_flags_obvious_contact_data_without_claiming_full_privacy():
    text = "JD owner test@example.com or 13800138000"
    items = [
        {
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "item_id": "item-1",
            "turn_order": 1,
            "item_order": 1,
            "text": text,
        }
    ]
    payload = prepare_excerpt(
        items,
        [{"turn_id": "turn-1", "item_id": "item-1", "start": 0, "end": len(text)}],
        "jd",
        CONFIRMED_AT,
    )

    assert payload["risk_flags"] == ["email", "phone"]


def test_write_excerpt_snapshot_is_deterministic(tmp_path):
    text = "Title: Senior Java Developer"
    items = [
        {
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "item_id": "item-1",
            "turn_order": 1,
            "item_order": 1,
            "text": text,
        }
    ]
    payload = prepare_excerpt(
        items,
        [{"turn_id": "turn-1", "item_id": "item-1", "start": 0, "end": len(text)}],
        "jd",
        CONFIRMED_AT,
    )
    output = tmp_path / "jd-snapshot.md"

    write_excerpt_snapshot(payload, output)
    first = output.read_text(encoding="utf-8")
    write_excerpt_snapshot(payload, output)

    assert output.read_text(encoding="utf-8") == first
    assert f"version_id: {payload['version_id']}" in first
    assert f"body_checksum: {payload['body_checksum']}" in first
    assert first.endswith(text + "\n")
    assert json.dumps(payload["metadata"]["selections"], ensure_ascii=False, sort_keys=True) in first
