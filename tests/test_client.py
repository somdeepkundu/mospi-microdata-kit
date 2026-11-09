from __future__ import annotations

import hashlib
import json

import pytest
import requests
import responses

from mospi_kit import (
    AuthenticationError,
    DownloadError,
    MicrodataClient,
    MospiError,
    NotFoundError,
)
from mospi_kit.client import DEFAULT_BASE_URL, parse_size

API = DEFAULT_BASE_URL
IDNO = "DDI-IND-MOSPI-NSSO-70Rnd-Sch33-visit2-Jan-Dec2013"
ZIP_NAME = "STATA_SASAH_70th_Round_2013_Visit 2.zip"
TOKEN = "U1RBVEFfU0FTQUhfNzB0aF9Sb3VuZF8yMDEzX1Zpc2l0IDIuemlw"


class Sleeps(list):
    def __call__(self, seconds: float) -> None:
        self.append(seconds)


def make(**kw) -> tuple[MicrodataClient, Sleeps]:
    sleeps = Sleeps()
    kw.setdefault("requests_per_minute", 0)
    return MicrodataClient("test-key-1234", sleep=sleeps, **kw), sleeps


def page(rows, total=3, limit=2):
    return {"result": {"rows": rows, "total": total, "limit": limit}}


def files_payload(size="1 KB", pdf_size="3.67 MB"):
    return {
        "status": "success",
        "files": [
            {"name": ZIP_NAME, "base64": TOKEN, "size": size},
            {"name": "KI_70_33_19dec14.pdf", "base64": "S0k=", "size": pdf_size},
        ],
    }


ROWS = [
    {
        "id": "134",
        "idno": IDNO,
        "title": "Situation Assessment Survey of Agricultural Households, Visit 2",
    },
    {"id": "135", "idno": "DDI-IND-PLFS-2023", "title": "Periodic Labour Force Survey 2023"},
    {"id": "136", "idno": "DDI-IND-HCES-2022", "title": "Household Consumption Expenditure Survey"},
]


def test_missing_key_explains_where_to_get_one():
    with pytest.raises(AuthenticationError, match=r"microdata\.gov\.in"):
        MicrodataClient()


def test_key_from_environment_and_never_in_repr(monkeypatch):
    monkeypatch.setenv("MOSPI_API_KEY", "secret-abcd")
    client = MicrodataClient()
    assert "secret" not in repr(client) and repr(client).endswith("'…abcd')")


@responses.activate
def test_catalogue_pages_dict_rows_cache_and_search():
    responses.get(
        f"{API}/listdatasets",
        json=page(ROWS[:2]),
        match=[responses.matchers.query_param_matcher({"page": "1"})],
    )
    responses.get(
        f"{API}/listdatasets",
        json={"result": {"rows": {"row": ROWS[2]}, "total": 3, "limit": 2}},
        match=[responses.matchers.query_param_matcher({"page": "2"})],
    )
    client, _ = make()
    datasets = client.list_datasets()
    assert [d.id for d in datasets] == ["134", "135", "136"]
    assert datasets[0].url.endswith("/catalog/134")
    assert len(responses.calls) == 2
    # second call is served from the cache, search matches every word in any order
    assert [d.idno for d in client.search("visit 2 AGRICULTURAL")] == [IDNO]
    assert len(responses.calls) == 2
    assert client.search("labour 2023")[0].idno == "DDI-IND-PLFS-2023"


@responses.activate
def test_numeric_id_is_resolved_to_idno():
    responses.get(f"{API}/listdatasets", json=page(ROWS, total=3, limit=3))
    responses.get(f"{API}/datasets/{IDNO}/fileslist", json=files_payload())
    client, _ = make()
    assert client.list_files("134")[0].name == ZIP_NAME
    with pytest.raises(NotFoundError, match="idno"):
        client.list_files("999")


@responses.activate
def test_download_writes_part_then_file_and_manifest(tmp_path):
    body = b"PK" + b"x" * 1100
    responses.get(f"{API}/datasets/{IDNO}/fileslist", json=files_payload("1.07 KB"))
    responses.get(
        f"{API}/fileslist/download/{IDNO}/{TOKEN}", body=body, content_type="application/zip"
    )
    client, _ = make()
    path = client.download(IDNO, ZIP_NAME, tmp_path, progress=False)
    assert path.read_bytes() == body
    assert not path.with_name(path.name + ".part").exists()
    manifest = json.loads((tmp_path / "MANIFEST.json").read_text())
    entry = manifest["files"][ZIP_NAME]
    assert entry["sha256"] == hashlib.sha256(body).hexdigest()
    assert entry["bytes"] == len(body) and entry["idno"] == IDNO and entry["tls_verified"]
    # an intact copy is not downloaded again
    calls = len(responses.calls)
    assert client.download(IDNO, ZIP_NAME, tmp_path, progress=False) == path
    assert len(responses.calls) == calls


@responses.activate
def test_name_match_is_case_insensitive_and_lists_files_when_missing(tmp_path):
    responses.get(f"{API}/datasets/{IDNO}/fileslist", json=files_payload())
    client, _ = make()
    with pytest.raises(NotFoundError, match="KI_70_33"):
        client.download(IDNO, "nope.zip", tmp_path)
    assert client._find_file(IDNO, ZIP_NAME.lower()).name == ZIP_NAME


@responses.activate
def test_truncated_download_is_rejected(tmp_path):
    responses.get(f"{API}/datasets/{IDNO}/fileslist", json=files_payload("12.72 MB"))
    responses.get(
        f"{API}/fileslist/download/{IDNO}/{TOKEN}", body=b"PK" * 100, content_type="application/zip"
    )
    client, _ = make()
    with pytest.raises(DownloadError, match="incomplete"):
        client.download(IDNO, ZIP_NAME, tmp_path, progress=False)
    assert list(tmp_path.iterdir()) == []


@responses.activate
def test_message_instead_of_file_is_an_error(tmp_path):
    responses.get(f"{API}/datasets/{IDNO}/fileslist", json=files_payload())
    responses.get(
        f"{API}/fileslist/download/{IDNO}/{TOKEN}",
        json={"status": "failed", "message": "Access denied"},
    )
    client, _ = make()
    with pytest.raises(DownloadError, match="Access denied"):
        client.download(IDNO, ZIP_NAME, tmp_path, progress=False)


@responses.activate
def test_transient_401_is_retried_with_exponential_backoff():
    responses.get(f"{API}/datasets/{IDNO}/fileslist", status=401, body="busy")
    responses.get(f"{API}/datasets/{IDNO}/fileslist", status=503, body="busy")
    responses.get(f"{API}/datasets/{IDNO}/fileslist", json=files_payload())
    client, sleeps = make()
    assert len(client.list_files(IDNO)) == 2
    assert sleeps == [2.0, 4.0]


@responses.activate
def test_retry_after_header_is_honoured():
    responses.get(f"{API}/listdatasets", status=429, headers={"Retry-After": "17"})
    responses.get(f"{API}/listdatasets", json=page(ROWS[:1], total=1, limit=1))
    client, sleeps = make()
    client.list_datasets(page=1)
    assert sleeps == [17.0]


@responses.activate
def test_persistent_401_means_the_key_is_wrong():
    responses.get(f"{API}/listdatasets", status=401, body="Invalid API key")
    client, sleeps = make(max_retries=3)
    with pytest.raises(AuthenticationError, match="Invalid API key"):
        client.list_datasets(page=1)
    assert len(sleeps) == 2


@responses.activate
def test_portal_error_status_in_json_body():
    responses.get(
        f"{API}/datasets/134/fileslist", json={"status": "failed", "message": "IDNO-NOT-FOUND"}
    )
    client, _ = make()
    with pytest.raises(NotFoundError, match="IDNO-NOT-FOUND"):
        client._json("datasets/134/fileslist")


@responses.activate
def test_connection_errors_give_up_with_advice():
    responses.get(f"{API}/listdatasets", body=requests.ConnectionError("reset"))
    client, sleeps = make(max_retries=3)
    with pytest.raises(MospiError, match="after 3 tries"):
        client.list_datasets(page=1)
    assert sleeps == [2.0, 4.0]


@responses.activate
def test_auto_tls_falls_back_once_and_records_it(tmp_path, caplog):
    responses.get(f"{API}/datasets/{IDNO}/fileslist", body=requests.exceptions.SSLError("chain"))
    responses.get(f"{API}/datasets/{IDNO}/fileslist", json=files_payload())
    responses.get(f"{API}/fileslist/download/{IDNO}/{TOKEN}", body=b"PK" + b"y" * 1100)
    client, _ = make()
    client.download(IDNO, ZIP_NAME, tmp_path, progress=False)
    assert client.verifying is False
    assert "not verified" in caplog.text
    manifest = json.loads((tmp_path / "MANIFEST.json").read_text())
    assert manifest["files"][ZIP_NAME]["tls_verified"] is False


@responses.activate
def test_strict_tls_never_falls_back():
    responses.get(f"{API}/listdatasets", body=requests.exceptions.SSLError("chain"))
    client, _ = make(verify=True)
    with pytest.raises(MospiError, match="ca-bundle"):
        client.list_datasets(page=1)


def test_throttle_spaces_requests():
    sleeps = Sleeps()
    client = MicrodataClient("k", sleep=sleeps, requests_per_minute=10)
    client._throttle.wait()
    client._throttle.wait()
    assert len(sleeps) == 1 and 5.9 < sleeps[0] <= 6.0


@responses.activate
def test_download_dataset_filters_with_globs(tmp_path):
    responses.get(f"{API}/datasets/{IDNO}/fileslist", json=files_payload(pdf_size="15 B"))
    responses.get(f"{API}/fileslist/download/{IDNO}/S0k=", body=b"%PDF-1.4 report")
    client, _ = make()
    paths = client.download_dataset(IDNO, tmp_path, include="*.PDF", progress=False)
    assert [p.name for p in paths] == ["KI_70_33_19dec14.pdf"]
    with pytest.raises(NotFoundError):
        client.download_dataset(IDNO, tmp_path, include="*.sav")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("12.72 MB", int(12.72 * 1024**2)),
        ("74 KB", 75776),
        ("1 GB", 1024**3),
        ("", None),
        ("big", None),
    ],
)
def test_parse_size(text, expected):
    assert parse_size(text) == expected


def test_unsafe_file_names_are_refused():
    from mospi_kit.client import _safe_name

    assert _safe_name("../../etc/passwd") == "passwd"
    with pytest.raises(DownloadError):
        _safe_name("..")
