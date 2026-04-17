from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal = None


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://") and not database_url.startswith("postgresql+"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def configure_database(database_url: str | None = None) -> None:
    global engine, SessionLocal
    settings = get_settings()
    url = normalize_database_url(database_url or settings.database_url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, connect_args=connect_args)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_runtime_schema()


def _ensure_runtime_schema() -> None:
    inspector = inspect(engine)
    if inspector.has_table("memberships"):
        column_names = {column["name"] for column in inspector.get_columns("memberships")}
        if "side_bet_manager" not in column_names:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE memberships ADD COLUMN side_bet_manager BOOLEAN NOT NULL DEFAULT FALSE"))
    if inspector.has_table("side_bets"):
        column_names = {column["name"] for column in inspector.get_columns("side_bets")}
        if "points_value" not in column_names:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE side_bets ADD COLUMN points_value INTEGER NOT NULL DEFAULT 1"))
    if engine.dialect.name == "postgresql" and inspector.has_table("side_bet_submissions"):
        for foreign_key in inspector.get_foreign_keys("side_bet_submissions"):
            constrained = foreign_key.get("constrained_columns") or []
            referred_table = foreign_key.get("referred_table")
            options = foreign_key.get("options") or {}
            if constrained == ["side_bet_id"] and referred_table == "side_bets" and options.get("ondelete") != "CASCADE":
                constraint_name = foreign_key.get("name") or "side_bet_submissions_side_bet_id_fkey"
                with engine.begin() as connection:
                    connection.execute(text(f'ALTER TABLE side_bet_submissions DROP CONSTRAINT IF EXISTS "{constraint_name}"'))
                    connection.execute(
                        text(
                            f'ALTER TABLE side_bet_submissions ADD CONSTRAINT "{constraint_name}" '
                            "FOREIGN KEY (side_bet_id) REFERENCES side_bets (id) ON DELETE CASCADE"
                        )
                    )
                break


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


configure_database()
