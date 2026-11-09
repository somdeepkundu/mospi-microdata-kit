#!/usr/bin/env python3
"""Check committed notebooks: valid, no outputs, no API keys. With --execute, run them."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

import nbformat

KEY_PATTERN = re.compile(r"(X-API-KEY|MOSPI_API_KEY)\s*[:=]\s*['\"][A-Za-z0-9]{12,}")


def check(path: Path) -> list[str]:
    nb = nbformat.read(path, as_version=4)
    nbformat.validate(nb)
    found = []
    for i, cell in enumerate(nb.cells):
        if cell.cell_type == "code" and (cell.get("outputs") or cell.get("execution_count")):
            found.append(f"{path.name} cell {i}: has outputs (clear them before committing)")
        if KEY_PATTERN.search(cell.source):
            found.append(f"{path.name} cell {i}: looks like a hard-coded API key")
    return found


def execute(path: Path) -> None:
    from nbclient import NotebookClient

    nb = nbformat.read(path, as_version=4)
    with tempfile.TemporaryDirectory() as tmp:
        NotebookClient(
            nb, timeout=900, kernel_name="python3", resources={"metadata": {"path": tmp}}
        ).execute()
    print(f"executed: {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("notebooks", nargs="+", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.execute:
        for path in args.notebooks:
            execute(path)
        return 0
    problems = [p for path in args.notebooks for p in check(path)]
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"{len(args.notebooks)} notebooks checked, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
