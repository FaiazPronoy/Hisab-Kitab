import os

# integration tests use their own database and run Celery tasks inline
_base = os.environ.get("DATABASE_URL", "postgresql+psycopg://docintel:docintel@postgres:5432/docintel")
os.environ["DATABASE_URL"] = _base.rsplit("/", 1)[0] + "/docintel_test"
os.environ["CELERY_EAGER"] = "true"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["MAX_UPLOAD_MB"] = "2"
os.environ.setdefault("STORAGE_DIR", "/tmp/docintel-test-storage")
# most tests act through the API key alone; test_auth.py turns login back on
os.environ["REQUIRE_LOGIN"] = "false"
os.environ["UPLOAD_RATE_LIMIT"] = "10000/minute"

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def db_ready():
    from sqlalchemy import create_engine, text
    admin = create_engine(_base, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS docintel_test WITH (FORCE)"))
        c.execute(text("CREATE DATABASE docintel_test"))
    eng = create_engine(os.environ["DATABASE_URL"])
    with eng.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        c.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    from app.db.models import Base
    Base.metadata.create_all(eng)
    yield


@pytest.fixture(scope="session")
def client(db_ready):
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


@pytest.fixture
def H():
    return {"X-API-Key": "local-dev-key"}
