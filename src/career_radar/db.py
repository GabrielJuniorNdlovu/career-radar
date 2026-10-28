from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from career_radar.config import Settings


def make_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=0,
        hide_parameters=True,
    )


@contextmanager
def source_lock(engine: Engine):
    if engine.dialect.name != "mysql":
        raise RuntimeError("ingestion requires MySQL advisory locking")
    with engine.connect() as connection:
        acquired = connection.scalar(text("SELECT GET_LOCK('careerradar:himalayas', 0)"))
        connection.commit()
        if acquired != 1:
            raise RuntimeError("Himalayas ingestion is already running")
        try:
            yield
        finally:
            try:
                connection.execute(text("SELECT RELEASE_LOCK('careerradar:himalayas')"))
                connection.commit()
            except Exception:
                connection.invalidate()
                raise
