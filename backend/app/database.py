from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.db_url import engine_options
from app.logging import logger
from app.config import get_settings

settings = get_settings()

_engine_url, _connect_args = engine_options(settings.DATABASE_URL)
engine = create_async_engine(
    _engine_url, echo=False, pool_pre_ping=True, connect_args=_connect_args
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Host and database only: the URL carries the database password, and this module
# is imported by Alembic on every migration, so logging it in full would print
# the credential to the log stream on every run.
_url = make_url(_engine_url)
logger.info(f"Database engine initialized — host: {_url.host}, database: {_url.database}")


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
