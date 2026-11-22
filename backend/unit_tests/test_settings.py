"""Settings surface.

The sync database URL existed only so Alembic could use a blocking driver. Now
that Alembic is async there is exactly one database URL, and this test keeps a
second one from creeping back in.
"""

from app.config import get_settings


def test_settings_no_longer_expose_a_sync_database_url():
    assert not hasattr(get_settings(), "SYNC_DATABASE_URL")


def test_database_url_uses_the_async_driver():
    """The engine always runs on asyncpg, whatever form the provider's URL takes.

    `.env` may hold a libpq-style `postgresql://` URL (as `neon env pull`
    writes it); `engine_options` is what turns it into the asyncpg URL.
    """
    from app.database import engine
    from app.db_url import engine_options

    url, _ = engine_options(get_settings().DATABASE_URL)
    assert url.startswith("postgresql+asyncpg://")
    assert engine.url.drivername == "postgresql+asyncpg"
