import asyncio
import sys
from pathlib import Path

import pytest

# Make the in-repo package importable when running pytest without installation.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tuxutools.backends.mock_backend import MockBackend, FAKE_UDID
from tuxutools.config import Settings


@pytest.fixture
def mock_backend() -> MockBackend:
    return MockBackend()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        config_dir=tmp_path / "config",
        backend="mock",
    )


@pytest.fixture
def app(settings: Settings):
    from tuxutools.app import TuxuTools

    instance = TuxuTools(settings=settings)
    yield instance
    instance.close()


def run(coro):
    return asyncio.run(coro)
