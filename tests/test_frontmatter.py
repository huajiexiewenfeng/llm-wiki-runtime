import pytest

from llm_wiki_runtime.frontmatter import parse_frontmatter


def test_parse_frontmatter_returns_scalars_flow_lists_and_body_offset():
    text = """---
title: Hiring plan
priority: 3
ratio: 1.25
published: true
owner: null
tags: [hr, 2026, false, null, 2.5]
---
# Content
"""

    metadata, offset = parse_frontmatter(text)

    assert metadata == {
        "title": "Hiring plan",
        "priority": 3,
        "ratio": 1.25,
        "published": True,
        "owner": None,
        "tags": ["hr", 2026, False, None, 2.5],
    }
    assert text[offset:] == "# Content\n"


def test_parse_frontmatter_returns_empty_metadata_without_leading_delimiter():
    text = "# No frontmatter\n"

    assert parse_frontmatter(text) == ({}, 0)


@pytest.mark.parametrize(
    "text",
    [
        "---\ntitle: one\ntitle: two\n---\nbody",
        "---\nowner:\n  name: Ada\n---\nbody",
        "---\ntags:\n  - hr\n---\nbody",
        "---\ntitle: &name Hiring\n---\nbody",
        "---\ntitle: *name\n---\nbody",
        "---\ntitle: !!python/object value\n---\nbody",
        "---\ntitle: |\n  line one\n---\nbody",
        "---\ntags: [hr, {name: Ada}]\n---\nbody",
        "---\ntags: [hr, [nested]]\n---\nbody",
        "---\ntitle:\tHiring\n---\nbody",
        "---\ntitle: Hiring\nbody",
        "--- \ntitle: Hiring\n---\nbody",
    ],
)
def test_parse_frontmatter_rejects_unsupported_or_malformed_yaml(text):
    with pytest.raises(ValueError):
        parse_frontmatter(text)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("false", False),
        ("null", None),
        ("-12", -12),
        ("1.5", 1.5),
        ("\"007\"", "007"),
        ("'hello: world'", "hello: world"),
    ],
)
def test_parse_frontmatter_coerces_only_supported_scalar_values(value, expected):
    metadata, _ = parse_frontmatter(f"---\nvalue: {value}\n---\n")

    assert metadata == {"value": expected}


@pytest.mark.parametrize("value", ["1e999", "-1e999"])
def test_parse_frontmatter_rejects_non_finite_float_scalars(value):
    with pytest.raises(ValueError):
        parse_frontmatter(f"---\nvalue: {value}\n---\n")


@pytest.mark.parametrize("value", ["1e999", "-1e999"])
def test_parse_frontmatter_rejects_non_finite_float_flow_list_items(value):
    with pytest.raises(ValueError):
        parse_frontmatter(f"---\nvalues: [1.25, {value}]\n---\n")


def test_parse_frontmatter_allows_brackets_and_braces_inside_quoted_scalars():
    metadata, _ = parse_frontmatter('---\ntitle: "Draft [internal] {review}"\n---\n')

    assert metadata == {"title": "Draft [internal] {review}"}


@pytest.mark.parametrize("value", [r'"escaped\t"', r'"escaped\u0009"'])
def test_parse_frontmatter_rejects_double_quoted_scalars_that_decode_to_tabs(value):
    with pytest.raises(ValueError):
        parse_frontmatter(f"---\nvalue: {value}\n---\n")


@pytest.mark.parametrize("value", [r'"escaped\t"', r'"escaped\u0009"'])
def test_parse_frontmatter_rejects_flow_list_items_that_decode_to_tabs(value):
    with pytest.raises(ValueError):
        parse_frontmatter(f"---\ntags: [safe, {value}]\n---\n")
