"""mospi-microdata-kit: get unit-level survey data from microdata.gov.in and turn it into
estimates you can defend.

    >>> from mospi_kit import MicrodataClient
    >>> client = MicrodataClient()                 # reads MOSPI_API_KEY
    >>> client.search("situation assessment 2013")
    >>> client.download("DDI-IND-MOSPI-NSSO-70Rnd-Sch33-visit2-Jan-Dec2013",
    ...                 "STATA_SASAH_70th_Round_2013_Visit 2.zip", "data/")
"""

from __future__ import annotations

__version__ = "1.0.0"

from .client import Dataset, MicrodataClient, RemoteFile
from .errors import (
    AuthenticationError,
    DownloadError,
    MospiError,
    NotFoundError,
    RateLimitError,
)
from .files import codebook, extract, find_table, list_tables, read_table, variable_labels
from .survey import (
    Estimate,
    estimate_by,
    ratio_mean,
    subsample_se,
    t_quantile,
    weighted_quantile,
)

__all__ = [
    "AuthenticationError",
    "Dataset",
    "DownloadError",
    "Estimate",
    "MicrodataClient",
    "MospiError",
    "NotFoundError",
    "RateLimitError",
    "RemoteFile",
    "__version__",
    "codebook",
    "estimate_by",
    "extract",
    "find_table",
    "list_tables",
    "ratio_mean",
    "read_table",
    "subsample_se",
    "t_quantile",
    "variable_labels",
    "weighted_quantile",
]
