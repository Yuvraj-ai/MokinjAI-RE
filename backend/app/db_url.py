"""Make a provider's Postgres connection string work with SQLAlchemy + asyncpg.

`neon env pull` (and most providers) write libpq-style URLs:
`postgresql://user:pass@host/db?sslmode=require&channel_binding=require`.
SQLAlchemy would pick psycopg for that scheme, and asyncpg rejects `sslmode`
and `channel_binding` as connect arguments. Neon's pooled endpoint (`-pooler`
in the host) is PgBouncer in transaction mode, where asyncpg's
prepared-statement cache fails with "prepared statement already exists", so
caching is turned off and statements get unique names there.

Pure functions: no network, no settings. URLs that already name
`postgresql+asyncpg` and carry no libpq parameters come back unchanged.
"""

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import make_url

_LIBPQ_ONLY_PARAMS = ("sslmode", "channel_binding")
_SSL_OFF_MODES = ("disable", "allow")


def _unique_statement_name() -> str:
    return f"__asyncpg_{uuid4()}__"


def engine_options(raw_url: str) -> tuple[str, dict[str, Any]]:
    """Return the SQLAlchemy URL and the asyncpg `connect_args` for a database URL."""
    url = make_url(raw_url)
    connect_args: dict[str, Any] = {}

    if url.drivername in ("postgres", "postgresql", "postgresql+asyncpg"):
        url = url.set(drivername="postgresql+asyncpg")

    sslmode = url.query.get("sslmode")
    if sslmode and sslmode not in _SSL_OFF_MODES:
        connect_args["ssl"] = "require"
    if any(name in url.query for name in _LIBPQ_ONLY_PARAMS):
        url = url.difference_update_query(_LIBPQ_ONLY_PARAMS)

    if url.host and "-pooler." in url.host:
        connect_args.update(
            statement_cache_size=0,
            prepared_statement_cache_size=0,
            prepared_statement_name_func=_unique_statement_name,
        )

    if url.render_as_string(hide_password=False) == raw_url and not connect_args:
        return raw_url, {}
    return url.render_as_string(hide_password=False), connect_args


def migration_url(environ: Mapping[str, str]) -> str | None:
    """The URL migrations should use: the direct one when the provider gives one.

    Migrations need a real session (DDL, locks, `SET`), which a transaction-mode
    pooler does not keep. Neon names the direct string `DATABASE_URL_UNPOOLED`.
    It is used only when it is the direct twin of `DATABASE_URL` (same host
    without `-pooler`, same database), so a caller that points DATABASE_URL
    somewhere else (a test database, a script) still migrates that database.
    """
    pooled = environ.get("DATABASE_URL") or None
    direct = environ.get("DATABASE_URL_UNPOOLED") or None
    if not direct:
        return pooled
    if not pooled:
        return direct
    pooled_url, direct_url = make_url(pooled), make_url(direct)
    same_database = (
        (pooled_url.host or "").replace("-pooler.", ".") == (direct_url.host or "")
        and pooled_url.database == direct_url.database
    )
    return direct if same_database else pooled
