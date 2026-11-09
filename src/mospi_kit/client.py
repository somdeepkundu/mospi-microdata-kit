"""Client for the microdata.gov.in NADA API.

The portal has three habits this client is built around:

* It allows about 10 requests a minute and answers faster bursts with 401, 429 or 5xx. A 401 is
  often temporary there, so it is retried with exponential backoff before it counts as a bad key.
* Its certificate chain is sometimes incomplete. With ``verify="auto"`` (the default) the client
  verifies first and falls back to an unverified connection to this one host only, says so in the
  log, and still checks every downloaded file's size and records its SHA-256.
* It does not support resuming a download (a ``Range`` request returns 500), so each file is written
  to ``<name>.part`` and renamed only when complete.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import os
import re
import time
import warnings
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import requests
import urllib3

from . import __version__
from .errors import AuthenticationError, DownloadError, MospiError, NotFoundError, RateLimitError

log = logging.getLogger("mospi_kit")

DEFAULT_BASE_URL = "https://microdata.gov.in/NADA/index.php/api"
CATALOG_URL = "https://microdata.gov.in/NADA/index.php/catalog/{id}"
ENV_API_KEY = "MOSPI_API_KEY"
ENV_CACHE_DIR = "MOSPI_KIT_CACHE"
TRANSIENT_STATUS = frozenset({401, 429, 500, 502, 503, 504})
MANIFEST_NAME = "MANIFEST.json"
_CHUNK = 1 << 20

VerifyOption = bool | str


@dataclass(frozen=True)
class Dataset:
    """One study in the portal's catalogue."""

    id: str
    idno: str
    title: str
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def url(self) -> str:
        """The study's page on microdata.gov.in (documentation, terms, variable list)."""
        return CATALOG_URL.format(id=self.id)


@dataclass(frozen=True)
class RemoteFile:
    """One file attached to a study."""

    name: str
    base64: str
    size_text: str = ""
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def size_bytes(self) -> int | None:
        """Approximate size parsed from the portal's text, e.g. ``"12.72 MB"``."""
        return parse_size(self.size_text)


def parse_size(text: str | None) -> int | None:
    """Turn ``"12.72 MB"`` into bytes. Returns ``None`` when the text is not a size."""
    if not text:
        return None
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(B|KB|MB|GB)\s*", text, flags=re.IGNORECASE)
    if not match:
        return None
    number, unit = float(match.group(1)), match.group(2).upper()
    return int(number * {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}[unit])


def default_cache_dir() -> Path:
    """Where the catalogue cache lives: ``$MOSPI_KIT_CACHE`` or ``~/.cache/mospi-kit``."""
    env = os.environ.get(ENV_CACHE_DIR)
    return Path(env) if env else Path.home() / ".cache" / "mospi-kit"


class _Throttle:
    """Keeps requests at least ``60 / per_minute`` seconds apart."""

    def __init__(self, per_minute: float, sleep: Callable[[float], None]) -> None:
        self.interval = 60.0 / per_minute if per_minute > 0 else 0.0
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = time.monotonic()
        if self._last is not None:
            gap = self.interval - (now - self._last)
            if gap > 0:
                self._sleep(gap)
        self._last = time.monotonic()


class MicrodataClient:
    """Search the catalogue, list a study's files and download them.

    Parameters
    ----------
    api_key:
        Your microdata.gov.in API key. If omitted, ``$MOSPI_API_KEY`` is used. Never hard-code it
        in a notebook you share.
    verify:
        ``"auto"`` (default) verifies HTTPS and falls back to an unverified connection to this host
        only if its certificate chain is broken. ``True`` never falls back. ``False`` never
        verifies. A path uses that CA bundle.
    requests_per_minute:
        The portal's limit is about 10. Lower it if you share a network with other users.
    max_retries:
        Tries per request for timeouts, dropped connections and status 401/429/5xx.
    cache_dir:
        Where the catalogue is cached for ``catalog_ttl_hours`` (default 24) so repeated searches
        do not page through the whole catalogue again.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        verify: VerifyOption = "auto",
        requests_per_minute: float = 10.0,
        max_retries: int = 6,
        backoff_seconds: float = 2.0,
        timeout: tuple[float, float] = (15.0, 600.0),
        cache_dir: str | os.PathLike[str] | None = None,
        catalog_ttl_hours: float = 24.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = (api_key or os.environ.get(ENV_API_KEY, "")).strip()
        if not key:
            raise AuthenticationError(
                "No API key. Sign in at https://microdata.gov.in, open your profile, create an API "
                f"key, then pass it as MicrodataClient(api_key=...) or set ${ENV_API_KEY}."
            )
        if verify not in ("auto", True, False) and not isinstance(verify, str):
            raise ValueError('verify must be "auto", True, False or a path to a CA bundle')
        self._key = key
        self.base_url = base_url.rstrip("/")
        self.host = urlsplit(self.base_url).hostname or ""
        self.max_retries = max(1, int(max_retries))
        self.backoff_seconds = backoff_seconds
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        self.catalog_ttl_hours = catalog_ttl_hours
        self._verify_option = verify
        self._verify_active: bool | str = (
            False if verify is False else (True if verify in ("auto", True) else verify)
        )
        self._warned_insecure = False
        self._sleep = sleep
        self._throttle = _Throttle(requests_per_minute, sleep)
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "X-API-KEY": self._key,
                "Accept": "application/json",
                "User-Agent": f"mospi-microdata-kit/{__version__} "
                "(+https://github.com/somdeepkundu/mospi-microdata-kit)",
            }
        )
        self._files_cache: dict[str, list[RemoteFile]] = {}
        if verify is False:
            self._warn_insecure("verify=False was requested")

    def __repr__(self) -> str:
        return f"MicrodataClient(base_url={self.base_url!r}, api_key='…{self._key[-4:]}')"

    # ------------------------------------------------------------------ HTTP

    @property
    def verifying(self) -> bool:
        """``False`` once the client has fallen back to an unverified connection."""
        return self._verify_active is not False

    def _warn_insecure(self, reason: str) -> None:
        if not self._warned_insecure:
            log.warning(
                "HTTPS certificate not verified for %s (%s). Downloads are still size-checked and "
                "their SHA-256 is recorded in %s.",
                self.host,
                reason,
                MANIFEST_NAME,
            )
            self._warned_insecure = True

    @contextmanager
    def _quiet_insecure(self) -> Iterator[None]:
        with warnings.catch_warnings():
            if self._verify_active is False:
                warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            yield

    def _backoff(self, attempt: int, response: requests.Response | None = None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                return min(float(retry_after), 300.0)
        return float(min(self.backoff_seconds * (2**attempt), 120.0))

    def _request(
        self, path: str, *, params: dict[str, Any] | None = None, stream: bool = False
    ) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        attempt = 0
        while True:
            self._throttle.wait()
            try:
                with self._quiet_insecure():
                    response = self._session.get(
                        url,
                        params=params,
                        timeout=self.timeout,
                        stream=stream,
                        verify=self._verify_active,
                    )
            except requests.exceptions.SSLError as exc:
                if self._verify_option == "auto" and self._verify_active is True:
                    self._verify_active = False
                    self._warn_insecure("the server's certificate chain could not be verified")
                    continue
                raise MospiError(
                    f"Secure connection to {self.host} failed: {exc}. If your network inspects "
                    'HTTPS, pass verify="/path/to/your/ca-bundle.pem".'
                ) from exc
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt + 1 >= self.max_retries:
                    raise MospiError(
                        f"Could not reach {self.host} after {self.max_retries} tries ({exc}). "
                        "Check the internet connection, or try again in a few minutes."
                    ) from exc
                delay = self._backoff(attempt)
                log.info("Connection problem, retrying in %.0f s (%s)", delay, exc)
                self._sleep(delay)
                attempt += 1
                continue

            if response.status_code in TRANSIENT_STATUS and attempt + 1 < self.max_retries:
                delay = self._backoff(attempt, response)
                log.info("Portal answered %s, retrying in %.0f s", response.status_code, delay)
                response.close()
                self._sleep(delay)
                attempt += 1
                continue
            return self._check_status(response)

    def _check_status(self, response: requests.Response) -> requests.Response:
        status = response.status_code
        if status < 400:
            return response
        body = _snippet(response)
        response.close()
        if status in (401, 403):
            raise AuthenticationError(
                f"The portal refused the API key ({status}: {body}). Check the key on your "
                "microdata.gov.in profile page; create a new one if it has expired."
            )
        if status == 404:
            raise NotFoundError(f"Not found on the portal ({body}).")
        if status == 429:
            raise RateLimitError(
                "The portal is limiting requests. Wait a few minutes, or lower requests_per_minute."
            )
        raise MospiError(f"The portal answered {status}: {body}")

    def _json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._request(path, params=params)
        try:
            payload = response.json()
        except ValueError as exc:
            raise MospiError(
                f"The portal did not return JSON for {path}: {_snippet(response)}"
            ) from exc
        if not isinstance(payload, dict):
            raise MospiError(f"Unexpected answer for {path}: {str(payload)[:200]}")
        status = str(payload.get("status", "")).lower()
        if status in {"failed", "error", "fail"}:
            message = str(payload.get("message") or payload.get("error") or payload)[:300]
            if "NOT-FOUND" in message.upper() or "NOT FOUND" in message.upper():
                raise NotFoundError(message)
            raise MospiError(message)
        return payload

    # ------------------------------------------------------------- catalogue

    def list_datasets(self, page: int | None = None, *, refresh: bool = False) -> list[Dataset]:
        """List studies. One ``page``, or the whole catalogue (cached) when ``page`` is ``None``."""
        if page is not None:
            rows, _, _ = self._catalog_page(page)
            return [_dataset(row) for row in rows]
        cached = None if refresh else self._read_catalog_cache()
        if cached is not None:
            return [_dataset(row) for row in cached]
        rows, total, limit = self._catalog_page(1)
        pages = -(-total // limit) if total and limit else 1
        for number in range(2, pages + 1):
            log.info("Reading catalogue page %d of %d", number, pages)
            more, _, _ = self._catalog_page(number)
            if not more:
                break
            rows.extend(more)
        self._write_catalog_cache(rows)
        return [_dataset(row) for row in rows]

    def search(self, query: str, *, refresh: bool = False) -> list[Dataset]:
        """Studies whose title or idno contain every word of ``query`` (any order, any case)."""
        words = [w for w in query.lower().split() if w]
        found = []
        for dataset in self.list_datasets(refresh=refresh):
            haystack = f"{dataset.title} {dataset.idno}".lower()
            if all(word in haystack for word in words):
                found.append(dataset)
        return found

    def _catalog_page(self, page: int) -> tuple[list[dict[str, Any]], int, int]:
        payload = self._json("listdatasets", params={"page": page})
        result = payload.get("result") or {}
        rows: Any = result.get("rows", [])
        if isinstance(rows, dict):
            rows = rows.get("row", [])
            rows = [rows] if isinstance(rows, dict) else rows
        if not isinstance(rows, list):
            rows = []
        return list(rows), _int(result.get("total")), _int(result.get("limit"))

    def _catalog_cache_path(self) -> Path:
        slug = re.sub(r"[^a-z0-9]+", "-", self.host.lower()).strip("-") or "portal"
        return self.cache_dir / f"catalog-{slug}.json"

    def _read_catalog_cache(self) -> list[dict[str, Any]] | None:
        path = self._catalog_cache_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            age_hours = (time.time() - float(data["fetched_at"])) / 3600
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if age_hours > self.catalog_ttl_hours or not isinstance(data.get("rows"), list):
            return None
        rows: list[dict[str, Any]] = data["rows"]
        return rows

    def _write_catalog_cache(self, rows: list[dict[str, Any]]) -> None:
        path = self._catalog_cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(path, {"fetched_at": time.time(), "rows": rows})
        except OSError as exc:  # a read-only home directory must not break a search
            log.debug("Catalogue cache not written: %s", exc)

    def _resolve_idno(self, idno_or_id: str) -> str:
        value = str(idno_or_id).strip()
        if value.isdigit():
            for dataset in self.list_datasets():
                if dataset.id == value:
                    log.info("Catalogue id %s is %s", value, dataset.idno)
                    return dataset.idno
            raise NotFoundError(
                f"No study has catalogue id {value}. Use the idno (the long code such as "
                "DDI-IND-MOSPI-NSSO-70Rnd-Sch33-visit2-Jan-Dec2013)."
            )
        if not value or "/" in value:
            raise ValueError(f"Not a study idno: {idno_or_id!r}")
        return value

    # ----------------------------------------------------------------- files

    def list_files(self, idno: str) -> list[RemoteFile]:
        """Files attached to a study (data in several formats, schedules, reports)."""
        idno = self._resolve_idno(idno)
        if idno not in self._files_cache:
            payload = self._json(f"datasets/{quote(idno, safe='')}/fileslist")
            entries = payload.get("files") or []
            self._files_cache[idno] = [
                RemoteFile(
                    name=str(e.get("name", "")),
                    base64=str(e.get("base64", "")),
                    size_text=str(e.get("size", "")),
                    raw=e,
                )
                for e in entries
                if isinstance(e, dict) and e.get("name") and e.get("base64")
            ]
        return list(self._files_cache[idno])

    def download(
        self,
        idno: str,
        name: str,
        dest_dir: str | os.PathLike[str] = ".",
        *,
        overwrite: bool = False,
        progress: bool = True,
    ) -> Path:
        """Download one file by its name as shown by :meth:`list_files`. Returns its path.

        A file already in ``dest_dir`` with a matching size and recorded SHA-256 is not
        downloaded again unless ``overwrite=True``.
        """
        idno = self._resolve_idno(idno)
        remote = self._find_file(idno, name)
        folder = Path(dest_dir)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / _safe_name(remote.name)
        manifest = _read_manifest(folder)

        if target.exists() and not overwrite:
            entry = manifest.get("files", {}).get(remote.name, {})
            if entry.get("sha256") and entry["sha256"] == _sha256(target):
                log.info("Already downloaded: %s", target)
                return target
            log.info("%s exists but is not in %s; downloading again", target.name, MANIFEST_NAME)

        part = target.with_name(target.name + ".part")
        part.unlink(missing_ok=True)  # the portal cannot resume, so start clean
        response = self._request(
            # the token is used exactly as the portal gave it, as mospiR and the portal docs do
            f"fileslist/download/{quote(idno, safe='')}/{quote(remote.base64, safe='=+/')}",
            stream=True,
        )
        content_type = response.headers.get("Content-Type", "").lower()
        if any(t in content_type for t in ("application/json", "text/html")) and not (
            remote.name.lower().endswith((".json", ".html", ".htm"))
        ):
            raise DownloadError(
                f"The portal sent a message instead of {remote.name}: {_snippet(response)}"
            )

        digest = hashlib.sha256()
        written = 0
        expected = remote.size_bytes
        bar = _progress_bar(expected, remote.name) if progress else None
        try:
            with self._quiet_insecure(), part.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=_CHUNK):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    if bar is not None:
                        bar.update(len(chunk))
        except (requests.RequestException, OSError) as exc:
            part.unlink(missing_ok=True)
            raise DownloadError(
                f"{remote.name} stopped after {written:,} bytes ({exc}). Run the download again."
            ) from exc
        finally:
            response.close()
            if bar is not None:
                bar.close()

        if written == 0:
            part.unlink(missing_ok=True)
            raise DownloadError(f"{remote.name} arrived empty. Try again in a few minutes.")
        if expected and written < 0.9 * expected:
            part.unlink(missing_ok=True)
            raise DownloadError(
                f"{remote.name} is incomplete: {written:,} bytes, expected about "
                f"{remote.size_text}. Run the download again."
            )
        os.replace(part, target)

        manifest.setdefault("files", {})[remote.name] = {
            "path": target.name,
            "idno": idno,
            "bytes": written,
            "size_on_portal": remote.size_text,
            "sha256": digest.hexdigest(),
            "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tls_verified": self.verifying,
            "tool": f"mospi-microdata-kit {__version__}",
        }
        _atomic_write_json(folder / MANIFEST_NAME, manifest)
        log.info("Downloaded %s (%s bytes)", target, f"{written:,}")
        return target

    def download_dataset(
        self,
        idno: str,
        dest_dir: str | os.PathLike[str] = ".",
        *,
        include: str | Sequence[str] | None = None,
        exclude: str | Sequence[str] | None = None,
        overwrite: bool = False,
        progress: bool = True,
    ) -> list[Path]:
        """Download every file of a study, or those matching ``include`` glob patterns.

        >>> client.download_dataset(idno, "data/", include=["STATA*", "*.pdf"])
        """
        idno = self._resolve_idno(idno)
        wanted = _patterns(include)
        unwanted = _patterns(exclude)
        files = [
            f
            for f in self.list_files(idno)
            if (not wanted or _matches(f.name, wanted)) and not _matches(f.name, unwanted)
        ]
        if not files:
            raise NotFoundError(f"No file of {idno} matches include={include!r}.")
        return [
            self.download(idno, f.name, dest_dir, overwrite=overwrite, progress=progress)
            for f in files
        ]

    def _find_file(self, idno: str, name: str) -> RemoteFile:
        files = self.list_files(idno)
        for f in files:
            if f.name == name:
                return f
        folded = [f for f in files if f.name.casefold() == name.casefold()]
        if len(folded) == 1:
            return folded[0]
        names = ", ".join(f.name for f in files[:40])
        raise NotFoundError(f"{idno} has no file named {name!r}. Files: {names}")


# --------------------------------------------------------------------- helpers


def _dataset(row: dict[str, Any]) -> Dataset:
    return Dataset(
        id=str(row.get("id", "")),
        idno=str(row.get("idno", "")),
        title=str(row.get("title", "")).strip(),
        raw=row,
    )


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _snippet(response: requests.Response, limit: int = 300) -> str:
    try:
        text = response.text
    except (requests.RequestException, RuntimeError):
        return "(no readable body)"
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:limit] or "(empty body)"


def _safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    if base in {"", ".", ".."}:
        raise DownloadError(f"Refusing to write a file named {name!r}")
    return base


def _patterns(value: str | Sequence[str] | None) -> list[str]:
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def _matches(name: str, patterns: list[str]) -> bool:
    folded = name.casefold()
    return any(fnmatch.fnmatchcase(folded, p.casefold()) for p in patterns)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(folder: Path) -> dict[str, Any]:
    try:
        data = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _atomic_write_json(path: Path, data: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class _Bar:
    def __init__(self, total: int | None, name: str) -> None:
        try:
            from tqdm.auto import tqdm
        except ImportError:  # progress is optional
            self._tqdm: Any = None
            log.info("Downloading %s", name)
        else:
            self._tqdm = tqdm(total=total, unit="B", unit_scale=True, desc=name[:40])

    def update(self, n: int) -> None:
        if self._tqdm is not None:
            self._tqdm.update(n)

    def close(self) -> None:
        if self._tqdm is not None:
            self._tqdm.close()


def _progress_bar(total: int | None, name: str) -> _Bar:
    return _Bar(total, name)
