import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import get_db_session
from app.main import app
from app.orm import Base
from app.seed.seed_mock_data import seed_mock_data


@pytest.fixture()
def seeded_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        seed_mock_data(session)
        yield session


@pytest.fixture()
def seeded_api_client(seeded_session: Session) -> TestClient:
    def override_db_session():
        yield seeded_session

    app.dependency_overrides[get_db_session] = override_db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
