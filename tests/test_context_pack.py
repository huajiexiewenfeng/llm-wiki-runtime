from llm_wiki_runtime.runtime import load_context_pack


def test_context_pack_respects_max_files_and_chars(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    (wiki_root / "domains/hr").mkdir(parents=True)
    (wiki_root / "domains/hr/001.md").write_text("abcdef", encoding="utf-8")
    (wiki_root / "domains/hr/002.md").write_text("ghijkl", encoding="utf-8")
    payload = load_context_pack(wiki_root, ["domains/hr/**"], [], 1, 3)
    assert payload["items"] == [{"path": "domains/hr/001.md", "content": "abc"}]
