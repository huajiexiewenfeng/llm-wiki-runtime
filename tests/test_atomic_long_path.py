from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
from llm_wiki_runtime.io import atomic_write_text


def check_long_path(tmp_path):
    parent = tmp_path / 'records'
    parent.mkdir()
    name_size = 245 - len(str(parent)) - 1
    assert name_size > 40
    target = parent / ('r' * (name_size - 3) + '.md')
    original_open = Path.open
    def limited_open(path, *args, **kwargs):
        if len(str(path)) >= 260:
            raise FileNotFoundError(2, 'Windows MAX_PATH exceeded', str(path))
        return original_open(path, *args, **kwargs)
    with patch.object(Path, 'open', limited_open):
        atomic_write_text(target, 'before\n')
        atomic_write_text(target, 'after 中文\n')
    assert target.read_bytes() == 'after 中文\n'.encode('utf-8')
    assert list(parent.iterdir()) == [target]


def check_replace_failure(tmp_path):
    target = tmp_path / 'record.md'
    target.write_text('original', encoding='utf-8')
    def fail_replace(source, destination):
        assert Path(source).parent == target.parent
        raise PermissionError('simulated replace failure')
    with patch.object(os, 'replace', fail_replace):
        try:
            atomic_write_text(target, 'replacement')
        except PermissionError:
            pass
        else:
            raise AssertionError('Expected replace failure')
    assert target.read_text(encoding='utf-8') == 'original'
    assert list(tmp_path.iterdir()) == [target]


class AtomicWriteTests(unittest.TestCase):
    def test_long_windows_path(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            check_long_path(Path(directory))

    def test_replace_failure_preserves_target(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            check_replace_failure(Path(directory))


if __name__ == '__main__':
    unittest.main()
