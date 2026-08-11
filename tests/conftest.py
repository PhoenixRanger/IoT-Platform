import pytest

from app import database
from app import create_app


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    database_path = tmp_path / "test_sensor.db"
    monkeypatch.setattr(database, "DB_NAME", str(database_path))
    database.init_db()
    return database_path


@pytest.fixture
def client(isolated_database):
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()
