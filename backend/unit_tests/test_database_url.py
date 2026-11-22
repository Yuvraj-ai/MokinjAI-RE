"""Turning a provider's connection string into what SQLAlchemy + asyncpg accept.

`neon env pull` writes libpq-style URLs (`postgresql://...?sslmode=require&
channel_binding=require`). asyncpg rejects `sslmode`/`channel_binding` as
connect kwargs, and Neon's `-pooler` host is PgBouncer in transaction mode,
where asyncpg's prepared-statement cache breaks. Pure functions, no network.
"""

import pytest

from app.db_url import engine_options, migration_url

NEON_POOLED = (
    "postgresql://user:pa%25ss@ep-x-pooler.c-9.us-east-2.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)
NEON_DIRECT = (
    "postgresql://user:pa%25ss@ep-x.c-9.us-east-2.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)
LOCAL = "postgresql+asyncpg://imyuvi@localhost:5432/mokinjay"


class TestEngineOptions:
    def test_libpq_url_becomes_asyncpg_with_ssl(self):
        url, args = engine_options(NEON_DIRECT)
        assert url.startswith("postgresql+asyncpg://")
        assert "sslmode" not in url and "channel_binding" not in url
        assert "pa%25ss" in url  # password encoding survives
        assert args["ssl"] == "require"
        assert "statement_cache_size" not in args

    def test_pooled_host_disables_prepared_statement_caching(self):
        _, args = engine_options(NEON_POOLED)
        assert args["statement_cache_size"] == 0
        assert args["prepared_statement_cache_size"] == 0
        name = args["prepared_statement_name_func"]
        assert name() != name()  # unique per statement, safe across pooled backends

    @pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
    def test_every_postgres_scheme_maps_to_asyncpg(self, scheme):
        url, _ = engine_options(f"{scheme}://u:p@db.example.com/x")
        assert url.startswith("postgresql+asyncpg://")

    def test_local_url_is_unchanged(self):
        url, args = engine_options(LOCAL)
        assert url == LOCAL
        assert args == {}

    @pytest.mark.parametrize("mode", ["disable", "allow"])
    def test_ssl_off_modes_are_not_forced_on(self, mode):
        _, args = engine_options(f"postgresql://u:p@db.example.com/x?sslmode={mode}")
        assert "ssl" not in args


class TestMigrationUrl:
    def test_prefers_the_direct_url(self):
        assert migration_url({"DATABASE_URL": NEON_POOLED, "DATABASE_URL_UNPOOLED": NEON_DIRECT}) == NEON_DIRECT

    def test_ignores_a_direct_url_for_a_different_database(self):
        """Overriding DATABASE_URL (tests, scripts) must keep migrations on it."""
        assert migration_url({"DATABASE_URL": LOCAL, "DATABASE_URL_UNPOOLED": NEON_DIRECT}) == LOCAL
        other_db = NEON_DIRECT.replace("/neondb?", "/otherdb?")
        assert migration_url({"DATABASE_URL": NEON_POOLED, "DATABASE_URL_UNPOOLED": other_db}) == NEON_POOLED

    def test_falls_back_to_database_url(self):
        assert migration_url({"DATABASE_URL": LOCAL}) == LOCAL
        assert migration_url({"DATABASE_URL": LOCAL, "DATABASE_URL_UNPOOLED": ""}) == LOCAL

    def test_none_when_nothing_is_set(self):
        assert migration_url({}) is None
