"""Unpack downloads and read survey tables with their variable labels."""

from __future__ import annotations

import logging
import os
import re
import zipfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from .errors import DownloadError, MospiError, NotFoundError

log = logging.getLogger("mospi_kit")

TABLE_SUFFIXES = (".dta", ".sav", ".csv", ".parquet")


def extract(
    archive: str | os.PathLike[str],
    dest: str | os.PathLike[str] | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    """Unzip ``archive`` into ``dest`` (default: a folder named after the archive).

    Every member is checked before anything is written: a damaged archive raises
    :class:`DownloadError`, and a member that would land outside ``dest`` (a "zip slip") raises
    :class:`MospiError`. Existing files are kept unless ``overwrite=True``.
    """
    archive = Path(archive)
    target = Path(dest) if dest is not None else archive.with_suffix("")
    root = target.resolve()
    try:
        with zipfile.ZipFile(archive) as zf:
            broken = zf.testzip()
            if broken is not None:
                raise DownloadError(
                    f"{archive.name} is damaged at {broken!r}. Download it again (overwrite=True)."
                )
            members = zf.infolist()
            for member in members:
                path = (root / member.filename).resolve()
                if path != root and root not in path.parents:
                    raise MospiError(
                        f"{archive.name} tries to write outside {target}: {member.filename!r}"
                    )
            written = 0
            for member in members:
                path = root / member.filename
                if member.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                    continue
                if path.exists() and not overwrite:
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, path.open("wb") as out:
                    while chunk := src.read(1 << 20):
                        out.write(chunk)
                written += 1
    except zipfile.BadZipFile as exc:
        raise DownloadError(
            f"{archive.name} is not a valid zip file ({exc}). Download it again (overwrite=True)."
        ) from exc
    log.info("Extracted %d files from %s into %s", written, archive.name, target)
    return target


def list_tables(
    folder: str | os.PathLike[str], suffixes: Sequence[str] = TABLE_SUFFIXES
) -> list[Path]:
    """Every data table under ``folder``, sorted by path."""
    wanted = tuple(s.lower() for s in suffixes)
    return sorted(
        p
        for p in Path(folder).rglob("*")
        if p.is_file() and p.suffix.lower() in wanted and not p.name.startswith("._")
    )


def _normalise(text: str) -> str:
    return re.sub(r"[\s_]+", " ", text.lower()).strip()


def find_table(
    folder: str | os.PathLike[str],
    *phrases: str,
    suffixes: Sequence[str] = (".dta",),
) -> Path:
    """The one table whose file name contains every phrase as a whole word.

    Spaces and underscores are treated alike, and case is ignored, so ``"block 5a"`` finds
    ``Visit 2_Block 5a_value of output….dta`` but ``"block 1"`` does not match ``Block 10``.
    Raises :class:`NotFoundError` when no file or more than one file matches.
    """
    if not phrases:
        raise ValueError("Give at least one phrase, e.g. find_table(folder, 'block 5a')")
    patterns = [
        re.compile(r"(?<![0-9a-z])" + re.escape(_normalise(p)) + r"(?![0-9a-z])") for p in phrases
    ]
    hits = [
        p
        for p in list_tables(folder, suffixes)
        if all(pattern.search(_normalise(p.name)) for pattern in patterns)
    ]
    if len(hits) == 1:
        return hits[0]
    wanted = " + ".join(repr(p) for p in phrases)
    if not hits:
        raise NotFoundError(f"No table under {folder} matches {wanted}.")
    names = "; ".join(h.name for h in hits)
    raise NotFoundError(f"{len(hits)} tables match {wanted}: {names}. Add another phrase.")


def clean_label(label: Any) -> str:
    """Repair labels that were stored as UTF-8 but read as Latin-1 (e.g. ``âLevel 5â``)."""
    text = "" if label is None else str(label)
    for wrong in ("latin-1", "cp1252"):
        try:
            repaired = text.encode(wrong).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired != text:
            text = repaired
            break
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)
    return text.strip().strip("\"'“”‘’").strip()


def variable_labels(path: str | os.PathLike[str]) -> dict[str, str]:
    """Variable labels of a Stata (.dta) or SPSS (.sav) file, without reading its data."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".dta":
        with pd.io.stata.StataReader(path) as reader:
            labels = reader.variable_labels()
        return {k: clean_label(v) for k, v in labels.items()}
    if suffix == ".sav":
        pyreadstat = _pyreadstat()
        _, meta = pyreadstat.read_sav(str(path), metadataonly=True)
        return {
            k: clean_label(v) for k, v in zip(meta.column_names, meta.column_labels, strict=False)
        }
    return {}


def read_table(
    path: str | os.PathLike[str],
    *,
    columns: Sequence[str] | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    """Read a .dta, .sav, .csv or .parquet table.

    Stata value labels are not applied (codes stay as the survey recorded them, so ``"09"`` stays
    ``"09"``). The variable labels are in ``df.attrs["variable_labels"]`` and the file in
    ``df.attrs["source"]``. Extra keyword arguments go to the pandas reader.
    """
    path = Path(path)
    if not path.exists():
        raise NotFoundError(f"No such file: {path}")
    suffix = path.suffix.lower()
    cols = list(columns) if columns is not None else None
    if suffix == ".dta":
        kwargs.setdefault("convert_categoricals", False)
        frame: pd.DataFrame = pd.read_stata(path, columns=cols, **kwargs)
    elif suffix == ".sav":
        frame, _ = _pyreadstat().read_sav(str(path), usecols=cols, **kwargs)
    elif suffix == ".csv":
        frame = pd.read_csv(path, usecols=cols, **kwargs)
    elif suffix == ".parquet":
        frame = pd.read_parquet(path, columns=cols, **kwargs)
    else:
        raise MospiError(
            f"Cannot read {path.suffix} files. Use one of {', '.join(TABLE_SUFFIXES)}."
        )
    labels = variable_labels(path)
    frame.attrs["variable_labels"] = {c: labels.get(c, "") for c in frame.columns}
    frame.attrs["source"] = str(path)
    return frame


def codebook(
    paths: str | os.PathLike[str] | Iterable[str | os.PathLike[str]], *, counts: bool = True
) -> pd.DataFrame:
    """One row per variable: file, variable, label, type and (if ``counts``) filled/distinct counts.

    Pass a folder to document every table in it. The codebook holds no data values, so it is safe
    to share alongside your analysis.
    """
    if isinstance(paths, (str, os.PathLike)) and Path(paths).is_dir():
        files = list_tables(paths)
    elif isinstance(paths, (str, os.PathLike)):
        files = [Path(paths)]
    else:
        files = [Path(p) for p in paths]
    rows: list[dict[str, Any]] = []
    for file in files:
        if counts:
            frame = read_table(file)
            labels = frame.attrs["variable_labels"]
            for col in frame.columns:
                series = frame[col]
                rows.append(
                    {
                        "file": file.name,
                        "variable": col,
                        "label": labels.get(col, ""),
                        "dtype": str(series.dtype),
                        "rows": len(series),
                        "filled": int(series.notna().sum()),
                        "distinct": int(series.nunique()),
                    }
                )
        else:
            for col, label in variable_labels(file).items():
                rows.append({"file": file.name, "variable": col, "label": label})
    return pd.DataFrame(rows)


def _pyreadstat() -> Any:
    try:
        import pyreadstat
    except ImportError as exc:
        raise MospiError(
            "Reading SPSS files needs pyreadstat: pip install 'mospi-microdata-kit[spss]'"
        ) from exc
    return pyreadstat
