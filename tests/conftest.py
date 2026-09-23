"""Chaque test utilise une BDD temporaire : la vraie data/stage.db n'est jamais touchée."""

import pytest
from fastapi.testclient import TestClient

from app import config


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    return path


@pytest.fixture
def client(db_path):
    from app.main import app
    with TestClient(app) as c:  # le "with" déclenche le lifespan (init_db)
        yield c
