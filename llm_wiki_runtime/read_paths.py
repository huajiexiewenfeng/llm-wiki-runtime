from __future__ import annotations

import fnmatch
from pathlib import Path


FORCED_EXCLUDES = (".meta/**",)


def effective_excludes(exclude: list[str]) -> list[str]:
    return list(dict.fromkeys([*exclude, *FORCED_EXCLUDES]))


def is_included(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def is_excluded(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def iter_readable_files(
    wiki_root: Path,
    include: list[str],
    exclude: list[str],
    order: str = "path_asc",
) -> list[Path]:
    excluded = effective_excludes(exclude)
    paths = []
    for path in wiki_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(wiki_root).as_posix()
        if is_included(relative, include) and not is_excluded(relative, excluded):
            paths.append(path)
    if order == "mtime_desc":
        return sorted(
            paths,
            key=lambda item: (
                -item.stat().st_mtime,
                item.relative_to(wiki_root).as_posix(),
            ),
        )
    if order != "path_asc":
        raise ValueError(f"unsupported read order: {order}")
    return sorted(paths, key=lambda item: item.relative_to(wiki_root).as_posix())
