"""Every setting load_settings reads from the environment must be in _ENV_KEYS, or a server's env file is silently
ignored (the sending service and the security contact were, until this test)."""
import re
from pathlib import Path

from ledgerline import config
from ledgerline.config import load_settings


def test_every_name_load_settings_reads_is_passed_through_from_the_environment():
    source = Path(config.__file__).read_text(encoding="utf-8")
    body = source[source.index("def load_settings"):]
    read = set(re.findall(r"""env(?:\.get\(|\[)\s*["']([A-Z][A-Z0-9_]+)["']""", body))
    assert read, "no environment names found; the pattern no longer matches load_settings"
    missing = sorted(read - set(config._ENV_KEYS))
    assert not missing, f"read by load_settings but not in _ENV_KEYS, so ignored on a server: {missing}"


def test_sender_key_path_and_security_contact_come_from_the_real_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LEDGERLINE_SENDER_SOCKET", "unix:/run/ledgerline-send/send.sock")
    monkeypatch.setenv("LEDGERLINE_CONNECTIONS_KEY_PATH", str(tmp_path / "connections.key"))
    monkeypatch.setenv("LEDGERLINE_SECURITY_CONTACT", "https://example.com/security")
    s = load_settings()
    assert s.sender_socket == "unix:/run/ledgerline-send/send.sock"
    assert s.connections_key_path == tmp_path / "connections.key"
    assert s.security_contact == "https://example.com/security"


def test_every_setting_is_documented_in_env_example():
    from ledgerline.config import BACKEND_DIR, _ENV_KEYS

    text = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
    assert [k for k in _ENV_KEYS if f"\n{k}=" not in text] == []
    values = dict(line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#"))
    for secret in ("AIRWALLEX_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_CLIENT_SECRET", "LEDGERLINE_SECRET_KEY", "LEDGERLINE_EDGE_SECRET",
                   "AIRWALLEX_WEBHOOK_SECRET", "LEDGERLINE_WEBHOOK_SECRET"):
        assert values.get(secret, "") == "", f"{secret} must be blank in the example"
