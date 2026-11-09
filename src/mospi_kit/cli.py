"""Command line: ``mospi-kit search | files | download | extract | codebook | farm-income``.

The API key is read from ``$MOSPI_API_KEY`` or typed at a hidden prompt. It is never accepted as
a command-line argument, because those end up in shell history.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .client import ENV_API_KEY, MicrodataClient
from .errors import MospiError
from .files import codebook, extract


def _client(args: argparse.Namespace) -> MicrodataClient:
    key = os.environ.get(ENV_API_KEY, "")
    if not key and sys.stdin.isatty():
        key = getpass.getpass("microdata.gov.in API key (input hidden): ")
    verify: bool | str = "auto"
    if args.ca_bundle:
        verify = args.ca_bundle
    elif args.strict_tls:
        verify = True
    return MicrodataClient(key or None, verify=verify)


def _cmd_search(args: argparse.Namespace) -> int:
    found = _client(args).search(" ".join(args.words), refresh=args.refresh)
    for d in found:
        print(f"{d.idno}\t{d.title}")
    print(f"{len(found)} studies", file=sys.stderr)
    return 0


def _cmd_files(args: argparse.Namespace) -> int:
    for f in _client(args).list_files(args.idno):
        print(f"{f.size_text:>10}  {f.name}")
    return 0


def _cmd_download(args: argparse.Namespace) -> int:
    client = _client(args)
    paths = client.download_dataset(
        args.idno,
        args.out,
        include=args.include or None,
        exclude=args.exclude or None,
        overwrite=args.overwrite,
    )
    if args.extract:
        for path in paths:
            if path.suffix.lower() == ".zip":
                extract(path)
    for path in paths:
        print(path)
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    for archive in args.archives:
        print(extract(archive, overwrite=args.overwrite))
    return 0


def _cmd_codebook(args: argparse.Namespace) -> int:
    book = codebook(args.path, counts=not args.labels_only)
    if args.out:
        book.to_csv(args.out, index=False, encoding="utf-8")
        print(f"{len(book)} variables written to {args.out}", file=sys.stderr)
    else:
        book.to_csv(sys.stdout, index=False)
    return 0


def _cmd_farm_income(args: argparse.Namespace) -> int:
    from . import nss70

    data = Path(args.data)
    if args.download:
        client = _client(args)
        client.download(nss70.VISIT2_IDNO, nss70.VISIT2_STATA_ZIP, data)
    results = nss70.run(data, args.out)
    for check in results.checks:
        print(
            f"[{check.status.upper():4}] {check.label}: expected {check.expected:,.1f}, "
            f"got {check.observed:,.1f}"
        )
    for path in results.files.values():
        print(path)
    return 0 if results.validated else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mospi-kit",
        description="Search, download and read unit-level data from microdata.gov.in.",
        epilog=f"The API key comes from ${ENV_API_KEY} or a hidden prompt.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="show every request")
    parser.add_argument(
        "--strict-tls",
        action="store_true",
        help="never fall back to an unverified HTTPS connection",
    )
    parser.add_argument("--ca-bundle", metavar="PEM", help="verify HTTPS with this CA bundle")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="find studies by words in their title or idno")
    p.add_argument("words", nargs="+")
    p.add_argument("--refresh", action="store_true", help="ignore the cached catalogue")
    p.set_defaults(func=_cmd_search)

    p = sub.add_parser("files", help="list a study's files")
    p.add_argument("idno")
    p.set_defaults(func=_cmd_files)

    p = sub.add_parser("download", help="download a study's files")
    p.add_argument("idno")
    p.add_argument("-o", "--out", default="data", help="folder (default: data)")
    p.add_argument(
        "-i",
        "--include",
        action="append",
        metavar="GLOB",
        help="only files matching, e.g. 'STATA*' (repeatable)",
    )
    p.add_argument("-x", "--exclude", action="append", metavar="GLOB")
    p.add_argument("--extract", action="store_true", help="unzip downloaded archives")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=_cmd_download)

    p = sub.add_parser("extract", help="unzip archives safely")
    p.add_argument("archives", nargs="+")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=_cmd_extract)

    p = sub.add_parser("codebook", help="variables and labels of every table in a folder")
    p.add_argument("path")
    p.add_argument("-o", "--out", help="CSV file (default: print)")
    p.add_argument("--labels-only", action="store_true", help="skip counts (much faster)")
    p.set_defaults(func=_cmd_codebook)

    p = sub.add_parser(
        "farm-income", help="NSS 70th round recipe: income from crops by state, Jan–Jun 2013"
    )
    p.add_argument("--data", default="data/nss70-visit2")
    p.add_argument("--out", default="results")
    p.add_argument("--download", action="store_true", help="download the Stata files first")
    p.set_defaults(func=_cmd_farm_income)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s"
    )
    if not args.verbose:
        logging.getLogger("urllib3").setLevel(logging.WARNING)
    try:
        return int(args.func(args))
    except MospiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
