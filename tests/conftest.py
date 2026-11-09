from __future__ import annotations

from pathlib import Path

import pytest

from mospi_kit.demo import make_visit2_demo


@pytest.fixture
def demo_folder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A fresh copy per test, so one test's extraction cannot confuse another."""
    folder = tmp_path_factory.mktemp("visit2")
    make_visit2_demo(folder)
    return folder


@pytest.fixture(autouse=True)
def _isolated_env(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    if request.node.get_closest_marker("live") is None:
        monkeypatch.delenv("MOSPI_API_KEY", raising=False)
    monkeypatch.setenv("MOSPI_KIT_CACHE", str(tmp_path / "cache"))
