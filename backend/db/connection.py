"""Shared Postgres connection pool (psycopg2)."""
import os
import pathlib
from contextlib import contextmanager

from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

_pool: ThreadedConnectionPool | None = None


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    # Railway sometimes hands out 'postgres://' which psycopg2 accepts, but
    # normalize for safety.
    if dsn.startswith("postgres://"):
        dsn = dsn.replace("postgres://", "postgresql://", 1)
    return dsn


def get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=_dsn())
    return _pool


@contextmanager
def get_conn():
    """Borrow a connection from the pool, commit on success, rollback on error."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor(dict_rows: bool = True):
    """Borrow a cursor. dict_rows=True returns RealDictCursor (JSON-friendly)."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor) if dict_rows else conn.cursor()
        try:
            yield cur
        finally:
            cur.close()


def execute_schema() -> None:
    """Run db/schema.sql once to initialize the database."""
    schema_path = pathlib.Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    print(f"Schema applied from {schema_path}")


def mark_sync(worker: str, status: str, rows: int = 0, message: str = "") -> None:
    """Upsert a sync_status row for a worker."""
    with get_cursor(dict_rows=False) as cur:
        cur.execute(
            """
            INSERT INTO sync_status (worker, last_run_at, last_ok_at, rows_written, status, message)
            VALUES (%s, NOW(), CASE WHEN %s = 'ok' THEN NOW() ELSE NULL END, %s, %s, %s)
            ON CONFLICT (worker) DO UPDATE SET
                last_run_at  = NOW(),
                last_ok_at   = CASE WHEN EXCLUDED.status = 'ok' THEN NOW() ELSE sync_status.last_ok_at END,
                rows_written = EXCLUDED.rows_written,
                status       = EXCLUDED.status,
                message      = EXCLUDED.message
            """,
            (worker, status, rows, status, message),
        )
