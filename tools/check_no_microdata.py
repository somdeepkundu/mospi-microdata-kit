#!/usr/bin/env python3
"""Fail if any survey microdata is tracked by git (or passed as arguments by pre-commit).

Checks file extensions and also file contents, so a renamed Stata or SPSS file is still caught:
Stata files start with ``<stata_dta>`` (format 117+) or bytes 0x71-0x77; SPSS files with
``$FL2``/``$FL3``. Zip files are opened and refused if they contain any such member.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

BLOCKED_SUFFIXES = {".dta", ".sav", ".zsav", ".por", ".sas7bdat", ".xpt", ".rdata", ".rds"}
ALLOWED_DIRS = ("tests/fixtures/",)  # tiny synthetic files only, never real data


def looks_like_microdata(head: bytes) -> bool:
    if head.startswith(b"<stata_dta>") or head.startswith((b"$FL2", b"$FL3")):
        return True
    return len(head) > 1 and head[0] in range(0x71, 0x78) and head[1] in (1, 2)


def problems(path: Path) -> list[str]:
    name = path.as_posix()
    if any(name.startswith(d) for d in ALLOWED_DIRS) or not path.is_file():
        return []
    found = []
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        found.append(f"{name}: survey data file type {path.suffix}")
    with path.open("rb") as handle:
        head = handle.read(16)
    if looks_like_microdata(head):
        found.append(f"{name}: contents look like Stata or SPSS data")
    if path.suffix.lower() == ".zip" or head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as zf:
                for member in zf.namelist():
                    if Path(member).suffix.lower() in BLOCKED_SUFFIXES:
                        found.append(f"{name}: archive contains {member}")
                        break
        except zipfile.BadZipFile:
            pass
    return found


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True)  # noqa: S607
    return [Path(p) for p in out.stdout.decode().split("\0") if p]


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] if argv else tracked_files()
    found = [msg for p in paths for msg in problems(p)]
    for msg in found:
        print(f"refused: {msg}", file=sys.stderr)
    if found:
        print("Survey microdata must not be committed. See docs/DATA_TERMS.md.", file=sys.stderr)
        return 1
    print(f"ok: {len(paths)} files checked, no survey microdata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
