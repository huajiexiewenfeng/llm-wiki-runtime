import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wheel_contains_offline_graph_assets(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(tmp_path),
            str(ROOT),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheel = next(tmp_path.glob("llm_wiki_runtime-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    required = {
        "llm_wiki_runtime/assets/graph/domain.html.tpl",
        "llm_wiki_runtime/assets/graph/index.html.tpl",
        "llm_wiki_runtime/assets/graph/graph.css",
        "llm_wiki_runtime/assets/graph/graph-app.bundle.js",
        "llm_wiki_runtime/assets/graph/index-app.bundle.js",
        "llm_wiki_runtime/assets/graph/ASSET_CHECKSUMS.json",
        "llm_wiki_runtime/assets/graph/THIRD_PARTY_NOTICES.md",
    }
    assert required <= names
