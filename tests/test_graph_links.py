from __future__ import annotations

from llm_wiki_runtime.graph_collect import CollectedDomain
from llm_wiki_runtime.graph_links import (
    _iter_markdown_targets,
    build_domain_edges,
    resolve_markdown_link,
    resolve_wikilink,
)
from llm_wiki_runtime.graph_models import GraphNode, stable_node_id


DOMAIN = "hr"
DOMAIN_ROOT = "domains/hr"


def _node(node_type: str, path: str, label: str = "") -> GraphNode:
    return GraphNode(
        id=stable_node_id(DOMAIN, node_type, path),
        type=node_type,
        subtype=node_type,
        label=label or path,
        summary="",
        status="",
        tags=(),
        path=path,
    )


def _collected(
    *,
    files: dict[str, tuple[str, dict[str, object]]],
    identities: dict[str, tuple[str, ...]] | None = None,
    reference_fields_by_node: dict[str, tuple[str, ...]] | None = None,
) -> CollectedDomain:
    scope = _node("scope", ".meta/profile.yml", "Scope")
    domain = _node("domain", DOMAIN_ROOT, "Human Resources")
    markdown = [_node("record" if "/candidates/" in path else "document", path) for path in files]
    by_path = {node.path: node for node in markdown}
    return CollectedDomain(
        nodes=(scope, domain, *markdown),
        diagnostics=(),
        frontmatter_by_node={
            by_path[path].id: frontmatter for path, (_, frontmatter) in files.items()
        },
        body_by_node={by_path[path].id: body for path, (body, _) in files.items()},
        identity_index=identities or {},
        path_index={path: (node.id,) for path, node in by_path.items()},
        reference_fields_by_node=reference_fields_by_node or {},
    )


def test_registered_and_structured_edges_have_portable_deterministic_evidence():
    source = _node("source", "sources/originals/hr/resume.pdf", "source-1")
    collected = _collected(
        files={
            "domains/hr/candidates/c-1/profile.md": ("", {"source_id": "source-1"}),
            "domains/hr/handbook.md": ("", {}),
        },
        identities={"source-1": (source.id,)},
    )
    collected = CollectedDomain(
        nodes=(*collected.nodes, source),
        diagnostics=collected.diagnostics,
        frontmatter_by_node=collected.frontmatter_by_node,
        body_by_node=collected.body_by_node,
        identity_index=collected.identity_index,
        path_index=collected.path_index,
    )

    edges, diagnostics = build_domain_edges(collected)

    record = next(node for node in collected.nodes if node.type == "record")
    domain = next(node for node in collected.nodes if node.type == "domain")
    referenced = next(edge for edge in edges if edge.type == "REFERENCED")
    assert referenced.source == record.id
    assert referenced.target == source.id
    assert referenced.label == "source_id"
    assert referenced.evidence == (
        {"method": "frontmatter-reference:source_id", "path": "domains/hr/candidates/c-1/profile.md"},
    )
    assert {(edge.source, edge.target) for edge in edges if edge.type == "REGISTERED"} == {
        (next(node for node in collected.nodes if node.type == "scope").id, domain.id),
        (domain.id, record.id),
        (domain.id, next(node for node in collected.nodes if node.type == "document").id),
    }
    assert all(edge.evidence == ({"method": "profile-registration", "path": ".meta/profile.yml"},) for edge in edges if edge.type == "REGISTERED")
    assert diagnostics == ()


def test_references_accept_suffix_shapes_and_explicit_required_reference_fields():
    target = _node("source", "sources/originals/hr/resume.pdf", "source-1")
    files = {
        "domains/hr/candidates/c-1/profile.md": (
            "",
            {"related_id": "source-1", "related_ids": ("source-1",), "custom_ref": ("source-1",)},
        ),
    }
    collected = _collected(files=files, identities={"source-1": (target.id,)})
    record = next(node for node in collected.nodes if node.type == "record")
    collected = CollectedDomain(
        nodes=(*collected.nodes, target), diagnostics=(), frontmatter_by_node=collected.frontmatter_by_node,
        body_by_node=collected.body_by_node, identity_index=collected.identity_index, path_index=collected.path_index,
        reference_fields_by_node={record.id: ("custom_ref",)},
    )

    edges, diagnostics = build_domain_edges(collected)

    referenced = next(edge for edge in edges if edge.type == "REFERENCED")
    assert referenced.label == "custom_ref"
    assert tuple(item["method"] for item in referenced.evidence) == (
        "frontmatter-reference:custom_ref",
        "frontmatter-reference:related_id",
        "frontmatter-reference:related_ids",
    )
    assert diagnostics == ()


def test_structured_references_ignore_tags_unmapped_fields_and_wrong_suffix_shapes():
    target = _node("source", "sources/originals/hr/resume.pdf", "source-1")
    collected = _collected(
        files={
            "domains/hr/candidates/c-1/profile.md": (
                "",
                {
                    "tags": ("source-1",),
                    "custom_ref": "source-1",
                    "related_id": ("source-1",),
                    "related_ids": "source-1",
                },
            ),
        },
        identities={"source-1": (target.id,)},
    )
    collected = CollectedDomain(
        nodes=(*collected.nodes, target), diagnostics=(), frontmatter_by_node=collected.frontmatter_by_node,
        body_by_node=collected.body_by_node, identity_index=collected.identity_index, path_index=collected.path_index,
    )

    edges, diagnostics = build_domain_edges(collected)

    assert not [edge for edge in edges if edge.type == "REFERENCED"]
    assert diagnostics == ()


def test_structured_reference_booleans_use_task_three_identity_normalization():
    target = _node("source", "sources/originals/hr/true.pdf", "true")
    collected = _collected(
        files={"domains/hr/candidates/c-1/profile.md": ("", {"approved_id": True})},
        identities={"true": (target.id,)},
    )
    collected = CollectedDomain(
        nodes=(*collected.nodes, target), diagnostics=(), frontmatter_by_node=collected.frontmatter_by_node,
        body_by_node=collected.body_by_node, identity_index=collected.identity_index, path_index=collected.path_index,
    )

    edges, diagnostics = build_domain_edges(collected)

    assert [(edge.source, edge.target) for edge in edges if edge.type == "REFERENCED"] == [
        (next(node for node in collected.nodes if node.type == "record").id, target.id)
    ]
    assert diagnostics == ()


def test_missing_ambiguous_and_self_structured_references_are_diagnosed_without_edges():
    record = _node("record", "domains/hr/candidates/c-1/profile.md")
    duplicate_a = _node("source", "sources/originals/hr/a.pdf")
    duplicate_b = _node("source", "sources/originals/hr/b.pdf")
    collected = CollectedDomain(
        nodes=(_node("scope", ".meta/profile.yml"), _node("domain", DOMAIN_ROOT), record, duplicate_a, duplicate_b),
        diagnostics=(),
        frontmatter_by_node={record.id: {"missing_id": "missing", "ambiguous_id": "same", "self_id": "record"}},
        body_by_node={record.id: ""},
        identity_index={"same": (duplicate_a.id, duplicate_b.id), "record": (record.id,)},
        path_index={record.path: (record.id,)},
    )

    edges, diagnostics = build_domain_edges(collected)

    assert not [edge for edge in edges if edge.type == "REFERENCED"]
    assert [(item.code, item.path) for item in diagnostics] == [
        ("ambiguous_structured_reference", record.path),
        ("self_structured_reference", record.path),
        ("unresolved_structured_reference", record.path),
    ]
    assert "missing" not in " ".join(item.message for item in diagnostics)


def test_identical_structured_reference_diagnostics_are_deduplicated():
    record = _node("record", "domains/hr/candidates/c-1/profile.md")
    collected = CollectedDomain(
        nodes=(_node("scope", ".meta/profile.yml"), _node("domain", DOMAIN_ROOT), record),
        diagnostics=(),
        frontmatter_by_node={record.id: {"first_id": "missing", "second_id": "missing"}},
        body_by_node={record.id: ""},
        identity_index={},
        path_index={record.path: (record.id,)},
    )

    _, diagnostics = build_domain_edges(collected)

    assert [(item.code, item.path) for item in diagnostics] == [("unresolved_structured_reference", record.path)]


def test_wikilink_resolution_follows_the_six_step_domain_algorithm():
    paths = {
        "domains/hr/a/source.md": ("source",),
        "domains/hr/a/peer.md": ("peer",),
        "domains/hr/shared.md": ("shared",),
        "domains/hr/jobs/j-1.md": ("job",),
        "domains/hr/topics/topic.md": ("topic",),
        "domains/hr/unique.md": ("unique",),
    }
    index = {path: ids for path, ids in paths.items()}
    source = "domains/hr/a/source.md"

    assert resolve_wikilink(source, "./peer|Alias", DOMAIN_ROOT, index).path == "domains/hr/a/peer.md"
    assert resolve_wikilink(source, "../shared#Section", DOMAIN_ROOT, index).path == "domains/hr/shared.md"
    assert resolve_wikilink(source, "jobs/j-1", DOMAIN_ROOT, index).path == "domains/hr/jobs/j-1.md"
    assert resolve_wikilink(source, "topic", DOMAIN_ROOT, index).path == "domains/hr/topics/topic.md"
    assert resolve_wikilink(source, "UNIQUE", DOMAIN_ROOT, index).path == "domains/hr/unique.md"


def test_wikilinks_reject_ambiguous_external_anchor_escape_and_cross_domain_targets():
    source = "domains/hr/a/source.md"
    index = {
        source: ("source",),
        "domains/hr/one/duplicate.md": ("one",),
        "domains/hr/two/Duplicate.md": ("two",),
    }

    assert resolve_wikilink(source, "duplicate", DOMAIN_ROOT, index).status == "ambiguous"
    for target in ("https://example.test/x", "#heading", "../../outside", "domains/ops/secret"):
        assert resolve_wikilink(source, target, DOMAIN_ROOT, index).path is None


def test_wikilink_filename_search_does_not_prefer_a_domain_root_match_over_ambiguity():
    source = "domains/hr/a/source.md"
    index = {
        source: ("source",),
        "domains/hr/topic.md": ("root",),
        "domains/hr/topics/topic.md": ("nested",),
    }

    assert resolve_wikilink(source, "topic", DOMAIN_ROOT, index).status == "ambiguous"


def test_markdown_links_resolve_relative_destinations_and_reject_nonlocal_forms():
    source = "domains/hr/a/source.md"
    index = {
        source: ("source",),
        "domains/hr/a/peer.md": ("peer",),
        "domains/hr/shared.md": ("shared",),
    }

    assert resolve_markdown_link(source, "<peer.md> \"title\"", DOMAIN_ROOT, index).path == "domains/hr/a/peer.md"
    assert resolve_markdown_link(source, "../shared.md?view=1#part", DOMAIN_ROOT, index).path == "domains/hr/shared.md"
    assert resolve_markdown_link(source, "..\\shared.md", DOMAIN_ROOT, index).path == "domains/hr/shared.md"
    for target in ("https://example.test/x", "//cdn.example.test/x", "mailto:a@b.test", "data:text/plain,x", "javascript:x", "#anchor", "../../outside.md", "domains/ops/a.md"):
        assert resolve_markdown_link(source, target, DOMAIN_ROOT, index).path is None


def test_markdown_links_decode_escaped_spaces_and_preserve_escaped_parentheses():
    source = "domains/hr/a/source.md"
    index = {
        source: ("source",),
        "domains/hr/a/file name.md": ("space",),
        "domains/hr/a/folder/peer.md": ("backslash",),
        "domains/hr/a/guide(draft).md": ("parentheses",),
    }

    assert resolve_markdown_link(source, r"file\ name.md", DOMAIN_ROOT, index).path == "domains/hr/a/file name.md"
    assert resolve_markdown_link(source, r"folder\\peer.md", DOMAIN_ROOT, index).path == "domains/hr/a/folder/peer.md"
    assert resolve_markdown_link(source, r"guide\(draft\).md", DOMAIN_ROOT, index).path == "domains/hr/a/guide(draft).md"


def test_markdown_links_accept_only_strict_optional_titles():
    source = "domains/hr/a/source.md"
    index = {source: ("source",), "domains/hr/a/peer.md": ("peer",)}

    for target in ('peer.md "title"', "peer.md 'title'", "peer.md (title)", '<peer.md> "title"'):
        assert resolve_markdown_link(source, target, DOMAIN_ROOT, index).path == "domains/hr/a/peer.md"
    for target in ("peer.md arbitrary", 'peer.md "unterminated', "<peer.md> unexpected"):
        assert resolve_markdown_link(source, target, DOMAIN_ROOT, index).path is None


def test_markdown_scanner_pairs_only_matching_label_delimiters():
    assert list(_iter_markdown_targets("[[not-a-link]] ![image](peer.md)")) == []
    assert list(_iter_markdown_targets("[unmatched [ordinary](peer.md)")) == ["peer.md"]
    assert list(_iter_markdown_targets("[unmatched ![image](peer.md)")) == []
    assert list(_iter_markdown_targets(r"[escaped \] label](peer.md)")) == ["peer.md"]
    assert list(_iter_markdown_targets("[outer [inner]](peer.md)")) == ["peer.md"]
    assert list(_iter_markdown_targets("[ordinary](peer.md)")) == ["peer.md"]


def test_nonlocal_anchor_and_image_markdown_forms_are_ignored_without_diagnostics():
    collected = _collected(
        files={
            "domains/hr/a/source.md": (
                "[web](https://example.test) [anchor](#part) ![image](peer.md) [mail](mailto:x@y.test)",
                {},
            ),
            "domains/hr/a/peer.md": ("", {}),
        }
    )

    edges, diagnostics = build_domain_edges(collected)

    assert not [edge for edge in edges if edge.type == "LINKED"]
    assert diagnostics == ()


def test_links_merge_evidence_and_emit_stable_diagnostics_without_body_leakage():
    files = {
        "domains/hr/a/source.md": ("[[peer]] and [other](peer.md)", {}),
        "domains/hr/a/peer.md": ("[[missing-secret-value]]", {}),
    }
    first = _collected(files=files)
    second = CollectedDomain(
        nodes=tuple(reversed(first.nodes)), diagnostics=(),
        frontmatter_by_node=dict(reversed(list(first.frontmatter_by_node.items()))),
        body_by_node=dict(reversed(list(first.body_by_node.items()))),
        identity_index={}, path_index=dict(reversed(list(first.path_index.items()))),
    )

    edges, diagnostics = build_domain_edges(first)
    reordered_edges, reordered_diagnostics = build_domain_edges(second)

    linked = next(edge for edge in edges if edge.type == "LINKED")
    assert linked.evidence == (
        {"method": "markdown-link", "path": "domains/hr/a/source.md"},
        {"method": "wikilink", "path": "domains/hr/a/source.md"},
    )
    assert [edge.id for edge in edges] == sorted(edge.id for edge in edges)
    assert [(item.code, item.path) for item in diagnostics] == [("unresolved_wikilink", "domains/hr/a/peer.md")]
    assert "missing-secret-value" not in diagnostics[0].message
    assert [edge.to_dict() for edge in edges] == [edge.to_dict() for edge in reordered_edges]
    assert [item.to_dict() for item in diagnostics] == [item.to_dict() for item in reordered_diagnostics]
