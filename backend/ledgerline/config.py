"""Runtime configuration.

Only the variables named here are read. Nothing else from the environment
(or from unrelated credential stores) is touched.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
AUTO_PREFIXES: list[str] = []

_ENV_KEYS = (
    "LEDGERLINE_DB_PATH",
    "LEDGERLINE_DATA_DIR",
    "LEDGERLINE_HOST",
    "LEDGERLINE_PORT",
    "LEDGERLINE_ALLOWED_ORIGINS",
    "LEDGERLINE_COOKIE_SECURE",
    "LEDGERLINE_ALLOW_SIGNUP",
    "LEDGERLINE_LOG_LEVEL",
    "LEDGERLINE_WEBHOOK_SECRET",
    "LEDGERLINE_PAYER_MCP_TRANSPORT",
    "LEDGERLINE_PAYER_AGENT_ALLOW_LOOPBACK",
    "LEDGERLINE_PROVIDER",
    "LEDGERLINE_SAMPLE_WORKSPACE",
    "AIRWALLEX_CLIENT_ID",
    "AIRWALLEX_API_KEY",
    "AIRWALLEX_WEBHOOK_SECRET",
    "AIRWALLEX_GLOBAL_ACCOUNT_IDS",
    "ANTHROPIC_API_KEY",
    "LEDGERLINE_CLAUDE_MODEL",
    "LEDGERLINE_PUBLIC_URL",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "APPLE_CLIENT_ID",
    "APPLE_TEAM_ID",
    "APPLE_KEY_ID",
    "APPLE_PRIVATE_KEY_PATH",
    "PORT",
    "LEDGERLINE_TRUSTED_PROXY_HOPS",
    "LEDGERLINE_SIGNUP_PER_IP_HOUR",
    "LEDGERLINE_SIGNUP_PER_IP_DAY",
    "LEDGERLINE_SIGNUP_PER_DAY",
    "LEDGERLINE_REQUIRE_PERSISTENT_MOUNT",
    "LEDGERLINE_SANDBOX_ORGS",
    "LEDGERLINE_CLAUDE_DAILY_LIMIT",
    "LEDGERLINE_CLAUDE_SERVER_DAILY_LIMIT",
    "LEDGERLINE_EDGE_SECRET",
    "LEDGERLINE_DATABASE_URL",
    "LEDGERLINE_PG_SCHEMA_PREFIX",
    "LEDGERLINE_SECRET_KEY",
    "LEDGERLINE_REQUIRE_DATABASE",
    "LEDGERLINE_SECURITY_CONTACT",
    "LEDGERLINE_SENDER_SOCKET",
    "LEDGERLINE_CONNECTIONS_KEY_PATH",
)


def _load_dotenv(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines, returning only keys Ledgerline uses."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in _ENV_KEYS:
            values[key] = value.strip().strip('"').strip("'")
    return values


@dataclass
class Settings:
    db_path: Path
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")
    cookie_secure: bool = False  # set when served over HTTPS; required for non-loopback binds
    allow_signup: bool = True
    log_level: str = "INFO"
    webhook_secret: str = "local-demo-webhook-secret-not-for-production"
    payer_mcp_transport: str = "stdio"  # stdio | memory
    payer_agent_allow_loopback: bool = False  # local development and tests only: lets a customer's agent be http://localhost
    provider: str = "local"  # local | airwallex_sandbox
    sample_workspace: bool = True  # first launch: seed and receive the six reference deposits
    airwallex_client_id: str | None = None
    airwallex_api_key: str | None = None
    airwallex_webhook_secret: str | None = None
    airwallex_global_account_ids: dict[str, str] = field(default_factory=dict)
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"
    # Where to report a security problem: a mailto: or https: address the operator chooses (served in security.txt).
    security_contact: str | None = None
    # Sign in with Google / Apple (see oidc.py). public_url is the origin users reach this server on;
    # OAuth redirect URIs are built from it and must be registered with each provider exactly.
    public_url: str = ""
    google_client_id: str | None = None
    google_client_secret: str | None = None
    apple_client_id: str | None = None
    apple_team_id: str | None = None
    apple_key_id: str | None = None
    apple_private_key: bytes | None = None
    # Deployment: how many reverse proxies in front of us append to X-Forwarded-For (0 = use the socket peer),
    # and a mount point the data directory must live on (refuse to start on ephemeral storage).
    trusted_proxy_hops: int = 0
    # New accounts and organizations: per client address per hour and per day, and for the whole server per day.
    signup_limits: tuple[int, int, int] = (10, 40, 500)
    judge_demo: bool = True  # one-click judge demo on the landing page
    judge_demo_limits: tuple[int, int] = (30, 300)  # per address an hour, per server a day
    require_persistent_mount: str | None = None
    # The Airwallex credentials are the operator's single sandbox account. Only organizations listed here
    # (by id) may switch to it; every other organization stays on the simulated bank.
    sandbox_org_ids: frozenset[str] = frozenset()
    # Shared Anthropic key: at most this many Claude calls per organization per UTC day.
    claude_daily_limit: int = 25
    # ...and at most this many across the whole server per UTC day (the spending safeguard for the shared key).
    claude_server_daily_limit: int = 200
    # Optional shared secret the edge proxy adds as X-Ledgerline-Edge. When set, X-Forwarded-For is trusted only on
    # requests carrying it, so a client calling the origin directly cannot choose its throttling identity.
    edge_secret: str | None = None
    # PostgreSQL (direct, non-pooled connection, e.g. Neon): when set, every logical database is a
    # schema there instead of a SQLite file, and payer-agent signing keys are stored encrypted in it.
    database_url: str | None = None
    pg_schema_prefix: str = "ll"
    # Server-side secret (32+ characters) from which the key-encryption key is derived. Required with PostgreSQL.
    secret_key: str | None = None
    # The sending service (ledgerline.sender). When set, this process holds no Airwallex keys: money-out for a company
    # connected to Airwallex is asked of the service by id, and bank reads go through it.
    sender_socket: str | None = None
    # Where the key that seals companies' own Airwallex credentials lives (default: data_dir/connections.key).
    connections_key_path: Path | None = None

    @property
    def postgres(self) -> bool:
        return bool(self.database_url)

    def pg_target(self, kind: str, org_id: str | None = None):
        from .db import PgTarget
        from .pg import schema_for

        return PgTarget(self.database_url, schema_for(self.pg_schema_prefix, kind, org_id))

    @property
    def airwallex_configured(self) -> bool:
        return bool(self.airwallex_client_id and self.airwallex_api_key)

    def sandbox_allowed(self, org_id: str | None) -> bool:
        # With a sending service the keys live there; the allow-list is still checked here and again by the service.
        return (self.airwallex_configured or bool(self.sender_socket)) and bool(org_id) and org_id in self.sandbox_org_ids

    @property
    def claude_configured(self) -> bool:
        return bool(self.anthropic_api_key)


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_ENCRYPTING_SSLMODES = {"require", "verify-ca", "verify-full"}


def check_database_tls(url: str) -> None:
    """Refuse a remote PostgreSQL URL unless every sslmode it carries enforces encryption.

    The URL is parsed rather than searched, so text elsewhere in it (a password, application_name=@localhost)
    cannot make a remote host look local, and a `host=` query parameter (which libpq lets override the
    authority) counts as a host too."""
    from urllib.parse import parse_qs, urlsplit

    parts = urlsplit(url)
    if parts.scheme not in ("postgres", "postgresql"):
        raise ValueError("LEDGERLINE_DATABASE_URL must be a postgresql:// URL")
    try:
        query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=bool(parts.query))
        authority = [h for h in (parts.hostname,) if h]
    except ValueError as exc:
        raise ValueError(f"LEDGERLINE_DATABASE_URL could not be parsed: {exc}") from None
    hosts = authority + [h for v in query.get("host", []) + query.get("hostaddr", []) for h in v.split(",")]
    hosts = [h.strip().strip("[]").lower() for h in hosts]
    local = all(h in _LOCAL_HOSTS or h.startswith("/") or h == "" for h in hosts)
    modes = [m.strip().lower() for m in query.get("sslmode", [])]
    if local:
        return
    if not modes or any(m not in _ENCRYPTING_SSLMODES for m in modes):
        raise ValueError("LEDGERLINE_DATABASE_URL must set sslmode=require (or verify-ca / verify-full) for a remote database")


def load_settings(overrides: dict[str, str] | None = None) -> Settings:
    env = _load_dotenv(BACKEND_DIR / ".env")
    for key in _ENV_KEYS:
        if key in os.environ:
            env[key] = os.environ[key]
    if overrides:
        env.update(overrides)

    data_dir = Path(env.get("LEDGERLINE_DATA_DIR") or (BACKEND_DIR / "var"))
    db_path = Path(env.get("LEDGERLINE_DB_PATH") or (data_dir / "ledgerline.sqlite3"))
    origins = tuple(o.strip() for o in env.get("LEDGERLINE_ALLOWED_ORIGINS", "").split(",") if o.strip())
    ga_ids: dict[str, str] = {}
    for pair in env.get("AIRWALLEX_GLOBAL_ACCOUNT_IDS", "").split(","):
        if ":" in pair:
            ccy, _, gid = pair.partition(":")
            ga_ids[ccy.strip().upper()] = gid.strip()

    s = Settings(db_path=db_path, data_dir=data_dir)
    s.host = env.get("LEDGERLINE_HOST", s.host)
    s.port = int(env.get("LEDGERLINE_PORT") or env.get("PORT") or s.port)  # PORT: set by hosts such as Render
    # Default: the Vite dev server plus this server's own origin (built UI served by the API).
    s.allowed_origins = origins or (
        "http://127.0.0.1:5173", "http://localhost:5173", f"http://127.0.0.1:{s.port}", f"http://localhost:{s.port}",
    )
    s.cookie_secure = env.get("LEDGERLINE_COOKIE_SECURE", "0").strip().lower() in ("1", "true", "yes")
    s.allow_signup = env.get("LEDGERLINE_ALLOW_SIGNUP", "1").strip().lower() not in ("0", "false", "no")
    s.log_level = (env.get("LEDGERLINE_LOG_LEVEL") or "INFO").upper()
    s.webhook_secret = env.get("LEDGERLINE_WEBHOOK_SECRET") or s.webhook_secret
    s.payer_mcp_transport = env.get("LEDGERLINE_PAYER_MCP_TRANSPORT", s.payer_mcp_transport)
    s.payer_agent_allow_loopback = env.get("LEDGERLINE_PAYER_AGENT_ALLOW_LOOPBACK", "0").strip().lower() in ("1", "true", "yes")
    s.provider = env.get("LEDGERLINE_PROVIDER", s.provider)
    s.sample_workspace = env.get("LEDGERLINE_SAMPLE_WORKSPACE", "1").strip().lower() not in ("0", "false", "no")
    s.airwallex_client_id = env.get("AIRWALLEX_CLIENT_ID") or None
    s.airwallex_api_key = env.get("AIRWALLEX_API_KEY") or None
    s.airwallex_webhook_secret = env.get("AIRWALLEX_WEBHOOK_SECRET") or None
    s.airwallex_global_account_ids = ga_ids
    s.anthropic_api_key = env.get("ANTHROPIC_API_KEY") or None
    s.claude_model = env.get("LEDGERLINE_CLAUDE_MODEL") or s.claude_model
    contact = env.get("LEDGERLINE_SECURITY_CONTACT", "").strip()
    if contact and not (contact.startswith("mailto:") or contact.startswith("https://")):
        raise ValueError("LEDGERLINE_SECURITY_CONTACT must start with mailto: or https://")
    s.security_contact = contact or None
    s.public_url = (env.get("LEDGERLINE_PUBLIC_URL") or f"http://localhost:{s.port}").rstrip("/")
    s.google_client_id = env.get("GOOGLE_CLIENT_ID") or None
    s.google_client_secret = env.get("GOOGLE_CLIENT_SECRET") or None
    s.apple_client_id = env.get("APPLE_CLIENT_ID") or None
    s.apple_team_id = env.get("APPLE_TEAM_ID") or None
    s.apple_key_id = env.get("APPLE_KEY_ID") or None
    s.trusted_proxy_hops = max(0, min(5, int(env.get("LEDGERLINE_TRUSTED_PROXY_HOPS") or 0)))
    s.signup_limits = tuple(max(1, int(env.get(k) or d)) for k, d in (("LEDGERLINE_SIGNUP_PER_IP_HOUR", 10), ("LEDGERLINE_SIGNUP_PER_IP_DAY", 40),
                                                                     ("LEDGERLINE_SIGNUP_PER_DAY", 500)))
    s.judge_demo = env.get("LEDGERLINE_JUDGE_DEMO", "1").strip().lower() not in ("0", "false", "no")
    s.judge_demo_limits = (max(1, int(env.get("LEDGERLINE_JUDGE_DEMO_PER_IP_HOUR") or 30)),
                           max(1, int(env.get("LEDGERLINE_JUDGE_DEMO_PER_DAY") or 300)))
    s.require_persistent_mount = env.get("LEDGERLINE_REQUIRE_PERSISTENT_MOUNT") or None
    s.sandbox_org_ids = frozenset(x.strip() for x in env.get("LEDGERLINE_SANDBOX_ORGS", "").split(",") if x.strip())
    s.claude_daily_limit = max(0, int(env.get("LEDGERLINE_CLAUDE_DAILY_LIMIT") or 25))
    s.claude_server_daily_limit = max(0, int(env.get("LEDGERLINE_CLAUDE_SERVER_DAILY_LIMIT") or 200))
    s.edge_secret = env.get("LEDGERLINE_EDGE_SECRET") or None
    s.database_url = env.get("LEDGERLINE_DATABASE_URL") or None
    prefix = (env.get("LEDGERLINE_PG_SCHEMA_PREFIX") or "ll").strip().lower()
    if prefix == "auto":  # tests: an isolated set of schemas per settings object
        import secrets as _secrets

        prefix = "x" + _secrets.token_hex(4)
        AUTO_PREFIXES.append(prefix)  # so a test run can drop exactly the schemas it created
    s.pg_schema_prefix = prefix
    s.secret_key = env.get("LEDGERLINE_SECRET_KEY") or None
    s.sender_socket = env.get("LEDGERLINE_SENDER_SOCKET", "").strip() or None
    s.connections_key_path = Path(env["LEDGERLINE_CONNECTIONS_KEY_PATH"]) if env.get("LEDGERLINE_CONNECTIONS_KEY_PATH") else None
    if env.get("LEDGERLINE_REQUIRE_DATABASE", "0").strip().lower() in ("1", "true", "yes") and not env.get("LEDGERLINE_DATABASE_URL"):
        # Hosted deployments set this so a missing database URL stops the service instead of silently
        # writing accounts and money records to an ephemeral local SQLite file.
        raise ValueError("LEDGERLINE_REQUIRE_DATABASE=1 but LEDGERLINE_DATABASE_URL is not set; refusing to start on local storage")
    if s.database_url:
        check_database_tls(s.database_url)
        if not s.secret_key or len(s.secret_key) < 32:
            raise ValueError("LEDGERLINE_SECRET_KEY (32+ random characters) is required with LEDGERLINE_DATABASE_URL")
        s.db_path = s.pg_target("t", "single")
    key_path = env.get("APPLE_PRIVATE_KEY_PATH")
    s.apple_private_key = Path(key_path).read_bytes() if key_path and Path(key_path).is_file() else None
    return s
