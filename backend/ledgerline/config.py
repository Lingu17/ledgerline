"""Runtime configuration.

Only the variables named here are read. Nothing else from the environment
(or from unrelated credential stores) is touched.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

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
    "LEDGERLINE_REQUIRE_PERSISTENT_MOUNT",
    "LEDGERLINE_SANDBOX_ORGS",
    "LEDGERLINE_CLAUDE_DAILY_LIMIT",
    "LEDGERLINE_EDGE_SECRET",
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
    provider: str = "local"  # local | airwallex_sandbox
    sample_workspace: bool = True  # first launch: seed and receive the six reference deposits
    airwallex_client_id: str | None = None
    airwallex_api_key: str | None = None
    airwallex_webhook_secret: str | None = None
    airwallex_global_account_ids: dict[str, str] = field(default_factory=dict)
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"
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
    require_persistent_mount: str | None = None
    # The Airwallex credentials are the operator's single sandbox account. Only organizations listed here
    # (by id) may switch to it; every other organization stays on the simulated bank.
    sandbox_org_ids: frozenset[str] = frozenset()
    # Shared Anthropic key: at most this many Claude calls per organization per UTC day.
    claude_daily_limit: int = 25
    # Optional shared secret the edge proxy adds as X-Ledgerline-Edge. When set, X-Forwarded-For is trusted only on
    # requests carrying it, so a client calling the origin directly cannot choose its throttling identity.
    edge_secret: str | None = None

    @property
    def airwallex_configured(self) -> bool:
        return bool(self.airwallex_client_id and self.airwallex_api_key)

    def sandbox_allowed(self, org_id: str | None) -> bool:
        return self.airwallex_configured and bool(org_id) and org_id in self.sandbox_org_ids

    @property
    def claude_configured(self) -> bool:
        return bool(self.anthropic_api_key)


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
    s.provider = env.get("LEDGERLINE_PROVIDER", s.provider)
    s.sample_workspace = env.get("LEDGERLINE_SAMPLE_WORKSPACE", "1").strip().lower() not in ("0", "false", "no")
    s.airwallex_client_id = env.get("AIRWALLEX_CLIENT_ID") or None
    s.airwallex_api_key = env.get("AIRWALLEX_API_KEY") or None
    s.airwallex_webhook_secret = env.get("AIRWALLEX_WEBHOOK_SECRET") or None
    s.airwallex_global_account_ids = ga_ids
    s.anthropic_api_key = env.get("ANTHROPIC_API_KEY") or None
    s.claude_model = env.get("LEDGERLINE_CLAUDE_MODEL") or s.claude_model
    s.public_url = (env.get("LEDGERLINE_PUBLIC_URL") or f"http://localhost:{s.port}").rstrip("/")
    s.google_client_id = env.get("GOOGLE_CLIENT_ID") or None
    s.google_client_secret = env.get("GOOGLE_CLIENT_SECRET") or None
    s.apple_client_id = env.get("APPLE_CLIENT_ID") or None
    s.apple_team_id = env.get("APPLE_TEAM_ID") or None
    s.apple_key_id = env.get("APPLE_KEY_ID") or None
    s.trusted_proxy_hops = max(0, min(5, int(env.get("LEDGERLINE_TRUSTED_PROXY_HOPS") or 0)))
    s.require_persistent_mount = env.get("LEDGERLINE_REQUIRE_PERSISTENT_MOUNT") or None
    s.sandbox_org_ids = frozenset(x.strip() for x in env.get("LEDGERLINE_SANDBOX_ORGS", "").split(",") if x.strip())
    s.claude_daily_limit = max(0, int(env.get("LEDGERLINE_CLAUDE_DAILY_LIMIT") or 25))
    s.edge_secret = env.get("LEDGERLINE_EDGE_SECRET") or None
    key_path = env.get("APPLE_PRIVATE_KEY_PATH")
    s.apple_private_key = Path(key_path).read_bytes() if key_path and Path(key_path).is_file() else None
    return s
