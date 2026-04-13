from app.db import normalize_database_url


def test_normalize_database_url_for_railway_postgres() -> None:
    assert normalize_database_url("postgres://user:pass@host:5432/db") == "postgresql+psycopg://user:pass@host:5432/db"
    assert normalize_database_url("postgresql://user:pass@host:5432/db") == "postgresql+psycopg://user:pass@host:5432/db"
    assert normalize_database_url("postgresql+psycopg://user:pass@host:5432/db") == "postgresql+psycopg://user:pass@host:5432/db"
    assert normalize_database_url("sqlite:///./nba_pool.db") == "sqlite:///./nba_pool.db"
