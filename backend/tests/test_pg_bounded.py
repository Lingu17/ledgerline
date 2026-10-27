"""Every database wait is bounded: a server (or network path) that stops answering must not hang a request.

Runs against a minimal in-process PostgreSQL wire-protocol server (simple query protocol only), so the real
psycopg/libpq/pool code paths are exercised without a database. The server can be told to stop answering on
the connections it already has, which is what a dead NAT mapping or a stuck proxy looks like to the client.
"""
from __future__ import annotations

import socket
import struct
import threading
import time

import psycopg
import pytest

from ledgerline import pg


class FakePostgres:
    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.queries: list[str] = []
        self.silent_conns: set[int] = set()
        self.conns: list[socket.socket] = []
        self.answer_startup = True
        self._lock = threading.Lock()
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def url(self) -> str:
        return f"postgresql://u:p@127.0.0.1:{self.port}/db?sslmode=disable&gssencmode=disable"

    def silence_existing(self) -> None:
        """Existing connections stop answering (they still read); new connections work normally."""
        with self._lock:
            self.silent_conns |= {id(c) for c in self.conns}

    def close(self) -> None:
        self.sock.close()
        for c in self.conns:
            try:
                c.close()
            except OSError:
                pass

    # ------------------------------------------------------------------ protocol
    def _accept(self) -> None:
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            with self._lock:
                self.conns.append(c)
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    @staticmethod
    def _recv(c: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = c.recv(n - len(buf))
            if not chunk:
                raise ConnectionError
            buf += chunk
        return buf

    @staticmethod
    def _msg(kind: bytes, payload: bytes = b"") -> bytes:
        return kind + struct.pack("!i", len(payload) + 4) + payload

    def _serve(self, c: socket.socket) -> None:
        try:
            while True:  # startup, after refusing SSL/GSS encryption requests
                n = struct.unpack("!i", self._recv(c, 4))[0]
                body = self._recv(c, n - 4)
                if struct.unpack("!i", body[:4])[0] in (80877103, 80877104):
                    c.sendall(b"N")
                    continue
                break
            if not self.answer_startup:
                while True:
                    self._recv(c, 1)
            out = self._msg(b"R", struct.pack("!i", 0))
            for k, v in (("client_encoding", "UTF8"), ("server_encoding", "UTF8"), ("server_version", "17.0"),
                         ("standard_conforming_strings", "on"), ("DateStyle", "ISO, MDY"), ("integer_datetimes", "on")):
                out += self._msg(b"S", k.encode() + b"\0" + v.encode() + b"\0")
            out += self._msg(b"K", struct.pack("!ii", 1234, 5678)) + self._msg(b"Z", b"I")
            c.sendall(out)
            schema = "public"
            while True:
                kind = self._recv(c, 1)
                n = struct.unpack("!i", self._recv(c, 4))[0]
                body = self._recv(c, n - 4)
                if kind == b"X":
                    return
                if kind != b"Q":
                    raise ConnectionError(f"fake server only speaks the simple query protocol, got {kind!r}")
                q = body.rstrip(b"\0").decode()
                with self._lock:
                    self.queries.append(q)
                    silent = id(c) in self.silent_conns
                if silent:
                    continue  # read, never answer
                if q.strip() == "":
                    c.sendall(self._msg(b"I") + self._msg(b"Z", b"I"))
                    continue
                if q.upper().startswith("SET SEARCH_PATH TO"):
                    schema = q.split("TO", 1)[1].strip().strip('"')
                value = {"SELECT CURRENT_SCHEMA()": schema, "SELECT 1": "1"}.get(q.strip().upper())
                out = b""
                if value is not None:
                    field = b"v\0" + struct.pack("!ihihih", 0, 0, 25, -1, -1, 0)
                    out += self._msg(b"T", struct.pack("!h", 1) + field)
                    out += self._msg(b"D", struct.pack("!hi", 1, len(value)) + value.encode())
                    tag = "SELECT 1"
                else:
                    tag = " ".join(q.split()[:2]).upper() if q.upper().startswith("CREATE") else q.split()[0].upper()
                out += self._msg(b"C", tag.encode() + b"\0") + self._msg(b"Z", b"I")
                c.sendall(out)
        except (ConnectionError, OSError):
            return
        finally:
            c.close()  # like a real server or proxy: when the client hangs up, close our side too


@pytest.fixture()
def fake(monkeypatch):
    monkeypatch.setattr(pg, "CLIENT_WAIT_LIMIT", 1.0)
    monkeypatch.setattr(pg, "_WATCH_INTERVAL", 0.05)
    server = FakePostgres()
    yield server
    p = pg._pools.pop(server.url, None)
    if p is not None:
        p.close(timeout=2)
    server.close()


def test_a_statement_with_no_answer_fails_fast_and_the_connection_is_discarded(fake):
    conn = pg.PgConnection(fake.url, "ll_bounded")
    assert conn.execute("SELECT 1").fetchone()[0] == "1"
    fake.silence_existing()
    started = time.monotonic()
    with pytest.raises(pg.DatabaseUnresponsive, match="no answer to a statement"):
        conn.execute("SELECT 1")
    assert time.monotonic() - started < 5
    conn.close()  # must not wait on the dead connection
    again = pg.PgConnection(fake.url, "ll_bounded")  # a fresh connection, not the broken one
    assert again.execute("SELECT 1").fetchone()[0] == "1"
    again.close()


def test_checking_a_connection_back_in_makes_no_network_call(fake):
    conn = pg.PgConnection(fake.url, "ll_bounded")
    before = len(fake.queries)
    conn.close()
    assert len(fake.queries) == before
    # The next checkout still pins and verifies the schema before any SQL.
    other = pg.PgConnection(fake.url, "ll_other")
    assert fake.queries[-2:] == ['SET search_path TO "ll_other"', "SELECT current_schema()"]
    other.close()


def test_the_pool_health_check_is_bounded_and_a_silent_connection_is_replaced(fake):
    pg.PgConnection(fake.url, "ll_bounded").close()  # one idle connection now sits in the pool
    fake.silence_existing()
    started = time.monotonic()
    conn = pg.PgConnection(fake.url, "ll_bounded")  # the check on the silent one times out; a new one is made
    assert time.monotonic() - started < 10
    assert conn.execute("SELECT 1").fetchone()[0] == "1"
    conn.close()


def test_new_connections_get_server_side_timeouts(fake):
    pg.PgConnection(fake.url, "ll_bounded").close()
    assert f"SET statement_timeout = {pg.STATEMENT_TIMEOUT_MS}" in fake.queries
    assert f"SET idle_in_transaction_session_timeout = {pg.IDLE_IN_TRANSACTION_TIMEOUT_MS}" in fake.queries


def test_connect_is_bounded_when_the_server_never_answers_the_startup(fake):
    fake.answer_startup = False
    kwargs = {**pg.connect_kwargs(), "connect_timeout": 2}  # libpq's minimum
    started = time.monotonic()
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(fake.url, **kwargs)
    assert time.monotonic() - started < 8


def test_production_bounds_are_ordered():
    # Server-side limits fire before the client watchdog, so a slow but alive server gives a clean error.
    assert pg.STATEMENT_TIMEOUT_MS / 1000 < pg.CLIENT_WAIT_LIMIT and pg.CONNECT_TIMEOUT <= 10
    assert pg.connect_kwargs()["keepalives"] == 1 and pg.connect_kwargs()["tcp_user_timeout"] > 0
