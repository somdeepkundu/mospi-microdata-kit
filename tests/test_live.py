"""Live checks against microdata.gov.in. Skipped unless run with ``pytest -m live`` and a key."""

from __future__ import annotations

import os

import pytest

from mospi_kit import MicrodataClient
from mospi_kit.nss70 import VISIT2_IDNO, VISIT2_STATA_ZIP

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("MOSPI_API_KEY"), reason="needs MOSPI_API_KEY"),
]


def test_catalogue_first_page_has_studies():
    datasets = MicrodataClient().list_datasets(page=1)
    assert datasets and all(d.idno for d in datasets)


def test_visit2_files_are_listed():
    names = [f.name for f in MicrodataClient().list_files(VISIT2_IDNO)]
    assert VISIT2_STATA_ZIP in names
