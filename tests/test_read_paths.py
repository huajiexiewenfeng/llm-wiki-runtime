from llm_wiki_runtime.read_paths import iter_readable_files


def test_iter_readable_files_uses_posix_order_and_forces_meta_exclusion(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    (wiki_root / "domains/projects/b").mkdir(parents=True)
    (wiki_root / "domains/projects/a").mkdir(parents=True)
    (wiki_root / ".meta").mkdir(parents=True)
    (wiki_root / "domains/projects/b/profile.md").write_text("b", encoding="utf-8")
    (wiki_root / "domains/projects/a/profile.md").write_text("a", encoding="utf-8")
    (wiki_root / ".meta/profile.yml").write_text("secret", encoding="utf-8")

    paths = iter_readable_files(wiki_root, ["**"], [], "path_asc")

    assert [path.relative_to(wiki_root).as_posix() for path in paths] == [
        "domains/projects/a/profile.md",
        "domains/projects/b/profile.md",
    ]
