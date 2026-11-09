"""Errors raised by mospi-microdata-kit. Every message says what to do next."""

from __future__ import annotations


class MospiError(Exception):
    """Base class for every error this package raises."""


class AuthenticationError(MospiError):
    """The portal kept refusing the API key."""


class NotFoundError(MospiError):
    """The dataset or file does not exist on the portal."""


class RateLimitError(MospiError):
    """The portal kept asking us to slow down."""


class DownloadError(MospiError):
    """A file did not arrive complete."""
