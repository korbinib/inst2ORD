"""Tests for CLI helpers (argument resolution, error handling)."""

from inst2ord.cli import _resolve_madmp_path


def test_resolve_madmp_path_accepts_file(tmp_path):
    f = tmp_path / "dmp.json"
    f.write_text("{}", encoding="utf-8")
    assert _resolve_madmp_path(str(f)) == str(f)


def test_resolve_madmp_path_finds_single_json_in_dir(tmp_path):
    f = tmp_path / "ex9.json"
    f.write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    # A directory with exactly one *.json resolves to it (the reported bug:
    # passing the folder used to raise IsADirectoryError).
    assert _resolve_madmp_path(str(tmp_path)) == str(f)


def test_resolve_madmp_path_empty_dir_is_clean_error(tmp_path, capsys):
    assert _resolve_madmp_path(str(tmp_path)) is None
    assert "No maDMP JSON file" in capsys.readouterr().err


def test_resolve_madmp_path_ambiguous_dir_is_clean_error(tmp_path, capsys):
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b.json").write_text("{}", encoding="utf-8")
    assert _resolve_madmp_path(str(tmp_path)) is None
    assert "Multiple JSON files" in capsys.readouterr().err


def test_resolve_madmp_path_missing_is_clean_error(tmp_path, capsys):
    assert _resolve_madmp_path(str(tmp_path / "nope.json")) is None
    assert "not found" in capsys.readouterr().err
