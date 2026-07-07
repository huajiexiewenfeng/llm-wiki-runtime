import json
import subprocess
import sys


def test_cli_help_module_imports():
    result = subprocess.run(
        [sys.executable, "-m", "llm_wiki_runtime.cli", "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "llm-wiki" in result.stdout


def test_cli_version_outputs_json():
    result = subprocess.run(
        [sys.executable, "-m", "llm_wiki_runtime.cli", "version"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["version"]
