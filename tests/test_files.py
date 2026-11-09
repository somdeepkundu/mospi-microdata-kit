from __future__ import annotations

import zipfile

import pandas as pd
import pytest

from mospi_kit import codebook, extract, find_table, read_table, variable_labels
from mospi_kit.errors import DownloadError, MospiError, NotFoundError
from mospi_kit.files import clean_label


def test_extract_and_find_tables(demo_folder, tmp_path):
    archive = next(demo_folder.glob("*.zip"))
    target = extract(archive, tmp_path / "x")
    assert find_table(target, "block 5a").name.startswith("Visit 2_Block 5a")
    assert "Block 1&2" in find_table(target, "Block 1&2").name
    assert find_table(target, "block 1").name == find_table(target, "Block 1&2").name
    with pytest.raises(NotFoundError, match="No table"):
        find_table(target, "block 7")


def test_find_table_needs_whole_words(tmp_path):
    for name in ["Block 1_ids.dta", "Block 10_assets.dta", "Block 12_spend.dta"]:
        (tmp_path / name).write_bytes(b"")
    assert find_table(tmp_path, "block 1").name == "Block 1_ids.dta"
    with pytest.raises(NotFoundError, match="3 tables"):
        find_table(tmp_path, "block")
    with pytest.raises(ValueError):
        find_table(tmp_path)


def test_zip_slip_is_refused(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../outside.txt", "nope")
    with pytest.raises(MospiError, match="outside"):
        extract(archive, tmp_path / "out")
    assert not (tmp_path / "outside.txt").exists()


def test_damaged_zip_is_reported(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"PK\x03\x04 not really a zip")
    with pytest.raises(DownloadError, match="Download it again"):
        extract(bad)


def test_read_table_keeps_codes_and_labels(tmp_path):
    frame = pd.DataFrame({"State": ["01", "19"], "Weight_SC": [7774.0, 422.5]})
    path = tmp_path / "t.dta"
    frame.to_stata(
        path,
        write_index=False,
        version=118,
        variable_labels={"State": "State", "Weight_SC": "Final weight"},
    )
    out = read_table(path)
    assert list(out["State"]) == ["01", "19"]
    assert out.attrs["variable_labels"] == {"State": "State", "Weight_SC": "Final weight"}
    assert variable_labels(path)["Weight_SC"] == "Final weight"
    book = codebook(tmp_path)
    assert set(book.columns) >= {"file", "variable", "label", "filled", "distinct"}
    assert "7774" not in book.to_csv()  # a codebook holds no data values
    assert list(codebook(path, counts=False)["label"]) == ["State", "Final weight"]


def test_read_table_errors(tmp_path):
    with pytest.raises(NotFoundError):
        read_table(tmp_path / "missing.dta")
    odd = tmp_path / "x.xyz"
    odd.write_text("1")
    with pytest.raises(MospiError, match="Cannot read"):
        read_table(odd)


@pytest.mark.parametrize(
    "raw,clean",
    [
        ("â\u0080\u009cLevel 5 - block 5aâ\u0080\u009d", "Level 5 - block 5a"),
        ("Total value (Rs.)", "Total value (Rs.)"),
        (None, ""),
        ("  'quoted'  ", "quoted"),
    ],
)
def test_clean_label(raw, clean):
    assert clean_label(raw) == clean
