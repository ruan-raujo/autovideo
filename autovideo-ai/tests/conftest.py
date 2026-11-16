from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend.config import Config
from backend.main import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(Config(data_dir=tmp_path / "data", worker_enabled=False))


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client
