"""PostgreSQL backend with the same connection interface the rest of the code uses for SQLite.

Why an adapter rather than an ORM rewrite: every money path (allocations, refunds, FX, approvals,
locks) was written and regression-tested against one small surface: `conn.execute(sql, params)`,
`fetchone()/fetchall()`, rows readable by name and position, `rowcount`, `lastrowid`, and
`BEGIN IMMEDIATE ... COMMIT`. This module provides exactly that surface on PostgreSQL so the
financial code and its tests stay unchanged.

Mapping, in one auditable place:
- One logical database = one PostgreSQL schema (control plane, each organization's ledger, each
  organization's simulated bank). The search_path of a connection is pinned to that schema only,
  so a tenant connection cannot name another tenant's tables without a schema prefix, and the code
  never writes schema prefixes.
- `BEGIN IMMEDIATE` (SQLite: one writer per database) becomes `BEGIN` plus a transaction-scoped
  advisory lock on the schema, which serializes writers per logical database exactly as before.
  Reads see committed data (READ COMMITTED), the same visibility SQLite gives outside a write.
- DDL: INTEGER -> BIGINT (money is 64-bit), AUTOINCREMENT -> identity, COLLATE NOCASE dropped
  (emails are normalized to lower case before storage and lookup).
- Queries: `?` -> `%s`; INSERT OR IGNORE -> ON CONFLICT DO NOTHING; LIKE -> ILIKE (SQLite LIKE is
  case-insensitive); json_extract(col,'$.k') -> col::jsonb ->> 'k'; PRAGMA table_info -> catalog.
- Results: integral NUMERIC from SUM() comes back as int, never float.

Connections must be DIRECT (session) connections, e.g. Neon's non-pooled endpoint: the per-connection
search_path is session state, which transaction-mode poolers (Neon's "-pooler" hostname, Supabase's
port 6543) do not preserve. Such URLs are refused (fail closed) because a lost search_path would point a
tenant connection at the wrong schema. TLS is required for remote hosts. Connections are validated on
checkout so a database that scales to zero (Neon free suspends after 5 idle minutes) is reconnected cleanly.

Every network wait is bounded, so a dead or silent connection fails and is discarded instead of holding a request
thread, a pool slot and possibly a writer lock forever: libpq connect timeout and TCP keepalives (plus
tcp_user_timeout where the OS supports it), server-side statement and idle-in-transaction timeouts, and a
client-side watchdog that shuts the socket of any statement (including the pool's health check) that has had
no answer for CLIENT_WAIT_LIMIT seconds. Checking a connection back in makes no network call: the next checkout
pins and verifies its schema anyway.
"""
from __future__ import annotations

import hashlib
import re
import socket
import threading
import time
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Iterable

import psycopg
from psycopg_pool import ConnectionPool

_SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_pools: dict[str, ConnectionPool] = {}
_pools_lock = threading.Lock()


class PoolerURLRefused(ValueError):
    pass


class DatabaseUnresponsive(psycopg.OperationalError):
    """A statement got no answer within CLIENT_WAIT_LIMIT; its connection was shut down and is discarded."""


# Bounds for every wait on the database (seconds unless noted). The server-side limits are below the client
# watchdog so a slow but alive server cancels a statement itself (a clean error) before the socket is cut.
CONNECT_TIMEOUT = 10
STATEMENT_TIMEOUT_MS = 30_000
IDLE_IN_TRANSACTION_TIMEOUT_MS = 60_000
CLIENT_WAIT_LIMIT = 45.0
_WATCH_INTERVAL = 0.5


def connect_kwargs() -> dict[str, Any]:
    return {
        "autocommit": True,
        "connect_timeout": CONNECT_TIMEOUT,
        # Probe idle connections (keeps NAT mappings alive and detects dead peers); libpq ignores the options an
        # OS lacks (keepalives_count on Windows, tcp_user_timeout outside Linux).
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
        "tcp_user_timeout": 30_000,  # ms: unacknowledged writes fail instead of retrying for many minutes
    }


class _Watchdog:
    """One background thread that shuts the socket of any database wait older than its deadline."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._waits: dict[int, list[Any]] = {}
        self._seq = 0
        self._thread: threading.Thread | None = None

    def start(self, raw: Any, limit: float) -> list[Any]:
        with self._lock:
            self._seq += 1
            entry = [time.monotonic() + limit, raw, False, self._seq]  # deadline, connection, fired, key
            self._waits[self._seq] = entry
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="ledgerline-db-watchdog", daemon=True)
                self._thread.start()
        return entry

    def finish(self, entry: list[Any]) -> bool:
        """Stop watching; True if the deadline passed and the socket was shut."""
        with self._lock:
            self._waits.pop(entry[3], None)
            return entry[2]

    def _run(self) -> None:
        while True:
            time.sleep(_WATCH_INTERVAL)
            now = time.monotonic()
            with self._lock:
                expired = [e for e in self._waits.values() if not e[2] and e[0] <= now]
                for e in expired:
                    e[2] = True
            for e in expired:
                _shut_socket(e[1])


_watchdog = _Watchdog()


def _shut_socket(raw: Any) -> None:
    """Make a blocked libpq wait return: the read sees EOF, psycopg raises, the connection becomes unusable."""
    try:
        s = socket.socket(fileno=raw.pgconn.socket)
        try:
            s.shutdown(socket.SHUT_RDWR)
        finally:
            s.detach()  # never close libpq's descriptor from here
    except Exception:  # noqa: BLE001 - the connection may already be closed; nothing else to do
        pass


@contextmanager
def bounded(raw: Any, what: str, limit: float | None = None):
    """Run database round trips with a hard client-side deadline."""
    limit = CLIENT_WAIT_LIMIT if limit is None else limit
    entry = _watchdog.start(raw, limit)
    try:
        yield
    except psycopg.Error as exc:
        if _watchdog.finish(entry):
            raise DatabaseUnresponsive(f"database gave no answer to {what} within {limit:.0f}s; connection discarded") from exc
        raise
    finally:
        _watchdog.finish(entry)


def _configure(conn: psycopg.Connection) -> None:
    with bounded(conn, "session setup"):
        conn.execute(f"SET statement_timeout = {int(STATEMENT_TIMEOUT_MS)}")
        conn.execute(f"SET idle_in_transaction_session_timeout = {int(IDLE_IN_TRANSACTION_TIMEOUT_MS)}")


def _check(conn: psycopg.Connection) -> None:
    with bounded(conn, "the pool health check"):
        ConnectionPool.check_connection(conn)


def check_direct_url(url: str) -> None:
    """Refuse transaction-mode pooler endpoints: they drop session state such as search_path."""
    from urllib.parse import urlparse

    u = urlparse(url)
    host = (u.hostname or "").lower()
    if "-pooler." in host or u.port == 6543 or "pgbouncer=true" in (u.query or "").lower():
        raise PoolerURLRefused("LEDGERLINE_DATABASE_URL points at a transaction-mode pooler; use the direct (non-pooled) "
                               "connection string, e.g. Neon's hostname without '-pooler'")


def pool(url: str) -> ConnectionPool:
    with _pools_lock:
        p = _pools.get(url)
        if p is None:
            check_direct_url(url)
            # Small pool (one free-tier process). check: validate on checkout, so connections closed by the server
            # (e.g. Neon suspending compute after inactivity) are replaced instead of failing a request.
            p = ConnectionPool(url, min_size=0, max_size=8, timeout=60, kwargs=connect_kwargs(), configure=_configure,
                               check=_check, max_idle=120, open=True, name="ledgerline")
            _pools[url] = p
        return p


def close_all() -> None:
    with _pools_lock:
        for p in _pools.values():
            p.close()
        _pools.clear()


class Row(dict):
    """dict that also answers row[0], like sqlite3.Row."""

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

    def keys(self):  # noqa: D401 - sqlite3.Row compatibility
        return list(super().keys())


def _clean(v: Any) -> Any:
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else v
    return v


class Cursor:
    def __init__(self, rows: list[Row] | None, rowcount: int, lastrowid: int | None) -> None:
        self._rows = rows or []
        self._i = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self) -> Row | None:
        if self._i < len(self._rows):
            self._i += 1
            return self._rows[self._i - 1]
        return None

    def fetchall(self) -> list[Row]:
        out, self._i = self._rows[self._i:], len(self._rows)
        return out

    def __iter__(self):
        return iter(self.fetchall())


# --------------------------------------------------------------------------- SQL translation
_JSON = re.compile(r"json_extract\(\s*(\w+)\s*,\s*'\$\.(\w+)'\s*\)", re.IGNORECASE)
_AUTOINC = re.compile(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", re.IGNORECASE)
_INTEGER = re.compile(r"\bINTEGER\b")
_NOCASE = re.compile(r"\s+COLLATE\s+NOCASE\b", re.IGNORECASE)
_OR_IGNORE = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\b", re.IGNORECASE)
_PRAGMA_TI = re.compile(r"^\s*PRAGMA\s+table_info\((\w+)\)\s*$", re.IGNORECASE)
_PRAGMA = re.compile(r"^\s*PRAGMA\b", re.IGNORECASE)
_DDL = re.compile(r"^\s*(CREATE|ALTER)\b", re.IGNORECASE)


def _outside_quotes(sql: str, fn) -> str:
    """Apply fn to the parts of sql outside single-quoted literals; escape % inside literals."""
    out, i, n = [], 0, len(sql)
    while i < n:
        j = sql.find("'", i)
        if j < 0:
            out.append(fn(sql[i:]))
            break
        out.append(fn(sql[i:j]))
        k = j + 1
        while True:  # find the closing quote, honouring '' escapes
            k = sql.find("'", k)
            if k < 0:
                raise ValueError("unterminated string literal in SQL")
            if k + 1 < n and sql[k + 1] == "'":
                k += 2
                continue
            break
        out.append(sql[j:k + 1].replace("%", "%%"))
        i = k + 1
    return "".join(out)


def translate(sql: str) -> str:
    if _DDL.match(sql):
        sql = _AUTOINC.sub("BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", sql)
        sql = _INTEGER.sub("BIGINT", sql)
        sql = _NOCASE.sub("", sql)
        return sql.replace("%", "%%")
    m = _PRAGMA_TI.match(sql)
    if m:
        return ("SELECT ordinal_position - 1 AS cid, column_name AS name FROM information_schema.columns "
                f"WHERE table_schema = current_schema() AND table_name = '{m.group(1)}' ORDER BY ordinal_position")
    ignore = bool(_OR_IGNORE.match(sql))
    if ignore:
        sql = _OR_IGNORE.sub("INSERT INTO", sql)
    sql = _JSON.sub(lambda mm: f"({mm.group(1)}::jsonb ->> '{mm.group(2)}')", sql)
    sql = _outside_quotes(sql, lambda part: re.sub(r"\bLIKE\b", "ILIKE", part.replace("?", "%s")))
    if ignore:
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql


def _params(params: Any) -> Any:
    if params is None or params == () or params == []:
        return None
    if isinstance(params, dict):
        return {k: int(v) if isinstance(v, bool) else v for k, v in params.items()}
    return tuple(int(v) if isinstance(v, bool) else v for v in params)


def lock_key(schema: str) -> int:
    return int.from_bytes(hashlib.sha256(schema.encode()).digest()[:8], "big", signed=True)


class PgConnection:
    """One pooled connection pinned to one schema, with the sqlite3 surface the code uses."""

    def __init__(self, url: str, schema: str) -> None:
        if not _SCHEMA_RE.match(schema):
            raise ValueError(f"invalid schema name {schema!r}")
        self.schema = schema
        self._pool = pool(url)
        self._raw = self._pool.getconn()
        self._in_tx = False
        try:
            with self._raw.cursor() as cur, bounded(self._raw, "schema pinning"):
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                cur.execute(f'SET search_path TO "{schema}"')
                cur.execute("SELECT current_schema()")
                if cur.fetchone()[0] != schema:  # defence in depth: never run tenant SQL in another schema
                    raise RuntimeError(f"search_path did not pin schema {schema!r}")
        except BaseException:
            self._pool.putconn(self._raw)
            raise

    def execute(self, sql: str, params: Any = ()) -> Cursor:
        stripped = sql.strip().rstrip(";").upper()
        if stripped in ("BEGIN IMMEDIATE", "BEGIN"):
            with self._raw.cursor() as cur, bounded(self._raw, "BEGIN"):
                cur.execute("BEGIN")
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key(self.schema),))
            self._in_tx = True
            return Cursor(None, 0, None)
        if stripped in ("COMMIT", "ROLLBACK"):
            with self._raw.cursor() as cur, bounded(self._raw, stripped):
                cur.execute(stripped)
            self._in_tx = False
            return Cursor(None, 0, None)
        if "sqlite_sequence" in sql:
            return Cursor(None, 0, None)  # identity counters are not reset on PostgreSQL; ids stay unique
        if _PRAGMA.match(sql) and not _PRAGMA_TI.match(sql):
            return Cursor(None, 0, None)  # SQLite connection pragmas have no PostgreSQL equivalent here
        q = translate(sql)
        lastrowid = None
        # The only caller that reads lastrowid is audit.post (journal_entries); ask PostgreSQL for the id.
        returning = q.lstrip().upper().startswith("INSERT INTO JOURNAL_ENTRIES")
        if returning and "RETURNING" not in q.upper():
            q = q.rstrip().rstrip(";") + " RETURNING id"
        with self._raw.cursor() as cur, bounded(self._raw, "a statement"):
            cur.execute(q, _params(params))
            rows = None
            if cur.description is not None:
                cols = [d.name for d in cur.description]
                rows = [Row(zip(cols, (_clean(v) for v in r))) for r in cur.fetchall()]
            if returning and rows:
                lastrowid = int(rows[0]["id"])
                rows = None
            return Cursor(rows, cur.rowcount, lastrowid)

    def executemany(self, sql: str, seq: Iterable[Any]) -> None:
        q = translate(sql)
        with self._raw.cursor() as cur, bounded(self._raw, "a batch statement"):
            cur.executemany(q, [_params(p) for p in seq])

    def executescript(self, script: str) -> None:
        for stmt in split_statements(script):
            self.execute(stmt)

    def close(self) -> None:
        if self._raw is None:
            return
        try:
            if self._in_tx and not self._raw.closed:
                with self._raw.cursor() as cur, bounded(self._raw, "ROLLBACK"):
                    cur.execute("ROLLBACK")
            # No RESET here: it cost a round trip on every check-in (and is where a silent connection was seen
            # hanging). The next checkout sets and verifies search_path before any SQL runs.
        finally:
            self._pool.putconn(self._raw)
            self._raw = None


_hardened: set[tuple[str, str, tuple[str, ...]]] = set()


def harden(conn: "PgConnection") -> None:
    """Deny everything to non-owner roles: Supabase's anon/authenticated API roles and PUBLIC get no
    privileges on Ledgerline schemas, and row-level security is enabled with no policies on every
    table, so only the owning server role (which bypasses RLS) can read or write. Tenant isolation
    itself is enforced by the application: a request's connection is pinned to its organization's
    schema only after session -> membership -> role checks."""
    if not isinstance(conn, PgConnection):
        return
    s = conn.schema
    # PostgreSQL catalog ACL updates can fail with "tuple concurrently updated"
    # when the first requests harden the same schema simultaneously. Use the same
    # transaction-scoped schema lock as migrations/writers, including across processes.
    owns_transaction = not conn._in_tx
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        with conn._raw.cursor() as cur, bounded(conn._raw, "schema hardening"):
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY tablename", (s,))
            tables = tuple(r[0] for r in cur.fetchall())
        key = (conn._pool.name or "", s, tables)
        if key not in _hardened:
            with conn._raw.cursor() as cur, bounded(conn._raw, "schema hardening"):
                cur.execute(f'REVOKE ALL ON SCHEMA "{s}" FROM PUBLIC')
                cur.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
                api_roles = [r[0] for r in cur.fetchall()]
                for role in api_roles:
                    cur.execute(f'REVOKE ALL ON SCHEMA "{s}" FROM {role}')
                    cur.execute(f'REVOKE ALL ON ALL TABLES IN SCHEMA "{s}" FROM {role}')
                    cur.execute(f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA "{s}" FROM {role}')
                    cur.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{s}" REVOKE ALL ON TABLES FROM {role}')
                for t in tables:
                    cur.execute(f'ALTER TABLE "{s}"."{t}" ENABLE ROW LEVEL SECURITY')
        if owns_transaction:
            conn.execute("COMMIT")
            _hardened.add(key)
    except BaseException:
        if owns_transaction:
            conn.execute("ROLLBACK")
        raise


def split_statements(script: str) -> Iterable[str]:
    no_comments = "\n".join(line.split("--", 1)[0] for line in script.splitlines())
    for stmt in no_comments.split(";"):
        if stmt.strip():
            yield stmt.strip()


def schema_for(prefix: str, kind: str, org_id: str | None = None) -> str:
    """ll_control, ll_t_org_0123abcd4567 (ledger), ll_b_org_0123abcd4567 (simulated bank)."""
    name = f"{prefix}_{kind}" + (f"_{org_id}" if org_id else "")
    if not _SCHEMA_RE.match(name):
        raise ValueError(f"invalid schema name {name!r}")
    return name
