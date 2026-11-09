from __future__ import annotations

import pytest

from mospi_kit import __version__
from mospi_kit.cli import build_parser, main


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_api_key_is_not_a_command_line_option():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--api-key", "x", "search", "plfs"])


def test_missing_key_is_a_clean_error(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["search", "plfs"]) == 1
    assert "API key" in capsys.readouterr().err


def test_codebook_and_farm_income_on_demo_data(demo_folder, tmp_path, capsys):
    assert main(["extract", str(next(demo_folder.glob("*.zip")))]) == 0
    out = tmp_path / "codebook.csv"
    assert main(["codebook", str(demo_folder), "-o", str(out)]) == 0
    assert "b5a_q18" in out.read_text()
    # demo data fails the NSSO checks, so the command exits with 2
    assert main(["farm-income", "--data", str(demo_folder), "--out", str(tmp_path / "r")]) == 2
    printed = capsys.readouterr().out
    assert "[FAIL] Households surveyed" in printed
    assert (tmp_path / "r" / "farm_income_by_state.json").exists()
