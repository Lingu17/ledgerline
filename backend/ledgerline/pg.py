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

Connections go through Supabase's shared pooler in session mode (port 5432, IPv4), which keeps
session state for the life of the client connection; TLS is required.
"""
from __future__ import annotations

import hashlib
import re
import threading
from decimal import Decimal
from typing import Any, Iterable

import psycopg
from psycopg_pool import ConnectionPool

_SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_pools: dict[str, ConnectionPool] = {}
_pools_lock = threading.Lock()


def pool(url: str) -> ConnectionPool:
    with _pools_lock:
        p = _pools.get(url)
        if p is None:
            # Small pool: the free Render instance is one process; Supabase's free pooler limits clients.
            p = ConnectionPool(url, min_size=1, max_size=8, timeout=30, kwargs={"autocommit": True},
                               open=True, name="ledgerline")
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
            with self._raw.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                cur.execute(f'SET search_path TO "{schema}"')
        except BaseException:
            self._pool.putconn(self._raw)
            raise

    def execute(self, sql: str, params: Any = ()) -> Cursor:
        stripped = sql.strip().rstrip(";").upper()
        if stripped in ("BEGIN IMMEDIATE", "BEGIN"):
            with self._raw.cursor() as cur:
                cur.execute("BEGIN")
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key(self.schema),))
            self._in_tx = True
            return Cursor(None, 0, None)
        if stripped in ("COMMIT", "ROLLBACK"):
            with self._raw.cursor() as cur:
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
        with self._raw.cursor() as cur:
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
        with self._raw.cursor() as cur:
            cur.executemany(q, [_params(p) for p in seq])

    def executescript(self, script: str) -> None:
        for stmt in split_statements(script):
            self.execute(stmt)

    def close(self) -> None:
        if self._raw is None:
            return
        try:
            if self._in_tx:
                with self._raw.cursor() as cur:
                    cur.execute("ROLLBACK")
            with self._raw.cursor() as cur:
                cur.execute("RESET search_path")
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
    with conn._raw.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY tablename", (s,))
        tables = tuple(r[0] for r in cur.fetchall())
    key = (conn._pool.name or "", s, tables)
    if key in _hardened:
        return
    with conn._raw.cursor() as cur:
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
    _hardened.add(key)


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
