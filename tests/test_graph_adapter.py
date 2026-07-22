from pathlib import Path

import pytest

from llm_wiki_runtime.graph_adapter import load_graph_adapter, snapshot_graph_adapter


def test_graph_adapter_parses_only_declarative_fields(tmp_path):
    path = tmp_path / "graph-adapter.yml"
    path.write_text(
        "\n".join(
            [
                "version: v0.1",
                "domain_id: hr",
                "display_name: Human Resources",
                "defaults:",
                "  label_field: candidate_id",
                "  subtype_field: record_type",
                "  summary_field: summary",
                "  status_field: status",
                "  tags_field: tags",
                "  metadata_allowlist: [education_level, years_experience]",
                "subtype_map:",
                "  candidate_profile: candidate",
            ]
        ),
        encoding="utf-8",
    )

    adapter = load_graph_adapter(path, "hr")

    assert adapter.domain_id == "hr"
    assert adapter.defaults.label_field == "candidate_id"
    assert adapter.defaults.metadata_allowlist == ("education_level", "years_experience")
    assert adapter.subtype_map == {"candidate_profile": "candidate"}


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("version: v0.2\ndomain_id: hr\n", "unsupported graph adapter version"),
        ("version: v0.1\ndomain_id: learning\n", "graph adapter domain_id does not match"),
        ("version: v0.1\ndomain_id: hr\ncallback: import.module\n", "unsupported graph adapter field"),
        ("version: v0.1\ndomain_id: hr\ndomain_id: hr\n", "duplicate graph adapter field"),
        (
            "version: v0.1\ndomain_id: hr\ndefaults:\n  label_field: candidate_id\n  callback: import.module\n",
            "unsupported graph adapter defaults field",
        ),
    ],
)
def test_graph_adapter_rejects_invalid_declarative_shape(tmp_path, contents, message):
    path = tmp_path / "graph-adapter.yml"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_graph_adapter(path, "hr")


def test_snapshot_graph_adapter_writes_the_single_validated_source_text(tmp_path, monkeypatch):
    profile = tmp_path / "llm-wiki-profile.yml"
    source_path = tmp_path / "graph-adapter.yml"
    validated_text = "version: v0.1\ndomain_id: hr\ndisplay_name: Validated\n"
    changed_text = "version: v0.1\ndomain_id: hr\ndisplay_name: Changed\n"
    source_path.write_text(validated_text, encoding="utf-8")
    original_read_text = Path.read_text
    source_read_count = 0

    def changing_read_text(path, *args, **kwargs):
        nonlocal source_read_count
        if path == source_path:
            source_read_count += 1
            return validated_text if source_read_count == 1 else changed_text
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", changing_read_text)

    snapshot_graph_adapter(profile, tmp_path / ".llm-wiki", "hr")

    snapshot_path = tmp_path / ".llm-wiki" / ".meta" / "graph-adapters" / "hr.yml"
    assert snapshot_path.read_text(encoding="utf-8") == validated_text
    assert source_read_count == 1


def test_hr_example_adapter_uses_display_name_and_person_detail_allowlist():
    adapter = load_graph_adapter(Path(__file__).parents[1] / "examples/hr/graph-adapter.yml", "hr")

    assert adapter.defaults.label_field == "display_name"
    assert adapter.defaults.metadata_allowlist == (
        "age",
        "years_experience",
        "education_level",
    )
