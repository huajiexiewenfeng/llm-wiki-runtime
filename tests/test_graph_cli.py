import json

from llm_wiki_runtime.cli import build_parser, main

from test_graph_export import _scope


def test_graph_export_parser_uses_flat_command_and_config_arguments():
    args = build_parser().parse_args(
        ["graph-export", "--cwd", "C:/scope", "--profile", "hr", "--scope", "C:/scope", "--domain", "hr"]
    )
    assert args.command == "graph-export"
    assert args.domain == "hr"


def test_graph_export_cli_resolves_scope_and_emits_result(tmp_path, capsys):
    scope_root = _scope(tmp_path)
    (scope_root / ".llm-wiki.yml").write_text("enabled: true\nstorage: .llm-wiki\n", encoding="utf-8")

    exit_code = main(["graph-export", "--cwd", str(scope_root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["domains"]["hr"]["status"] == "ok"


def test_graph_export_cli_maps_lock_timeout_to_scope_busy(tmp_path, capsys, monkeypatch):
    scope_root = _scope(tmp_path)
    (scope_root / ".llm-wiki.yml").write_text("enabled: true\nstorage: .llm-wiki\n", encoding="utf-8")

    def busy(*args, **kwargs):
        raise TimeoutError("private lock path")

    monkeypatch.setattr("llm_wiki_runtime.cli.export_graphs", busy)
    exit_code = main(["graph-export", "--cwd", str(scope_root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 3
    assert payload["status"] == "scope_busy"
    assert "private" not in json.dumps(payload)


def test_graph_export_cli_sanitizes_io_failures(tmp_path, capsys, monkeypatch):
    scope_root = _scope(tmp_path)
    (scope_root / ".llm-wiki.yml").write_text("enabled: true\nstorage: .llm-wiki\n", encoding="utf-8")

    def fail(*args, **kwargs):
        raise OSError(r"C:\private\graph directory failed")

    monkeypatch.setattr("llm_wiki_runtime.cli.export_graphs", fail)
    exit_code = main(["graph-export", "--cwd", str(scope_root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 3
    assert payload["status"] == "io_error"
    assert payload["errors"] == ["graph_export_io_error"]
    assert "private" not in json.dumps(payload)


def test_graph_export_cli_returns_non_enabled_config_payload_unchanged(tmp_path, capsys):
    exit_code = main(["graph-export", "--cwd", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["status"] == "missing_config"
    assert payload["enabled"] is False
