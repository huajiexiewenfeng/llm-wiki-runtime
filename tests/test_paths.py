from pathlib import Path

import pytest

from llm_wiki_runtime.paths import ensure_under_root, render_logical_path, validate_slug


@pytest.mark.parametrize("value", ["../x", "a/b", "a\\b", "", ".", "..", "C:bad"])
def test_validate_slug_rejects_unsafe_values(value):
    with pytest.raises(ValueError):
        validate_slug(value)


def test_render_logical_path_substitutes_safe_vars():
    path = render_logical_path("domains/hr/candidates/{candidate_id}/profile.md", {"candidate_id": "zhang-san"})
    assert path == Path("domains/hr/candidates/zhang-san/profile.md")


def test_ensure_under_root_rejects_escape(tmp_path):
    with pytest.raises(ValueError):
        ensure_under_root(tmp_path, Path("../escape.md"))
