"""Nightly backup: the encrypted off-server copy, its upload, and the restore check."""
import base64
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy" / "vm"))
import backup  # noqa: E402
import restore_check  # noqa: E402


@pytest.fixture
def snapshot(client, app, settings, tmp_path):
    """A real night's copy of a practice company that has been through the walkthrough."""
    for step in ("deposits", "links", "agents", "treasury"):
        assert client.post("/api/demo/step", json={"step": step}).status_code == 200
    return backup.snapshot(Path(settings.data_dir), Path(settings.data_dir) / "backups", 7)


@pytest.fixture
def key_file(tmp_path):
    p = tmp_path / "backup.key"
    p.write_text(base64.b64encode(os.urandom(32)).decode())
    return p


def write_encrypted(snapshot, key_file, tmp_path, name=None):
    name = name or f"ledgerline/{snapshot.name}.tar.gz.enc"
    out = tmp_path / f"{snapshot.name}.tar.gz.enc"
    out.write_bytes(backup.encrypt(backup.pack(snapshot), backup.read_key(key_file), name))
    return out


def test_an_encrypted_copy_restores_and_verifies(snapshot, key_file, tmp_path, capsys):
    blob = write_encrypted(snapshot, key_file, tmp_path)
    assert b"organizations" not in blob.read_bytes()  # nothing readable without the key
    assert restore_check.check(blob, key_file) is True
    out = capsys.readouterr().out
    assert "books balanced=True, audit chain ok=True" in out and "PASS" in out and "1 organizations" in out


def test_a_copy_missing_an_organizations_books_fails(snapshot, key_file, tmp_path, capsys):
    next(snapshot.glob("orgs/*/ledgerline.sqlite3")).unlink()
    assert restore_check.check(write_encrypted(snapshot, key_file, tmp_path), key_file) is False
    out = capsys.readouterr().out
    assert "MISSING books for 1 organization" in out and "FAIL" in out


def test_a_successful_upload_records_when(snapshot, key_file, monkeypatch):
    monkeypatch.setattr(backup, "upload", lambda blob, bucket, name: {"generation": "7"})
    name = backup.offsite(snapshot, "bucket", key_file)
    assert (snapshot.parent / "last_offsite").read_text().split()[1] == name


def test_a_failed_upload_fails_the_backup_and_records_nothing(snapshot, key_file, monkeypatch):
    def down(*_a):
        raise OSError("bucket unreachable")
    monkeypatch.setattr(backup, "upload", down)
    with pytest.raises(OSError):
        backup.offsite(snapshot, "bucket", key_file)
    assert not (snapshot.parent / "last_offsite").exists()


def test_a_tampered_copy_a_wrong_key_or_a_renamed_copy_is_refused(snapshot, key_file, tmp_path):
    blob = write_encrypted(snapshot, key_file, tmp_path)
    data = bytearray(blob.read_bytes())
    data[-10] ^= 1
    tampered = tmp_path / "t" / blob.name
    tampered.parent.mkdir()
    tampered.write_bytes(bytes(data))
    with pytest.raises(InvalidTag):
        restore_check.check(tampered, key_file)
    other_key = tmp_path / "other.key"
    other_key.write_text(base64.b64encode(os.urandom(32)).decode())
    with pytest.raises(InvalidTag):
        restore_check.check(blob, other_key)
    with pytest.raises(InvalidTag):
        restore_check.check(blob, key_file, "ledgerline/20200101-000000.tar.gz.enc")  # passed off as another night
    bad = tmp_path / "short.key"
    bad.write_text(base64.b64encode(b"x" * 16).decode())
    with pytest.raises(ValueError):
        backup.read_key(bad)


def test_upload_uses_the_vm_token_and_never_overwrites():
    seen = {}

    class Fake(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["metadata_flavor"] = self.headers.get("Metadata-Flavor")
            body = json.dumps({"access_token": "test-token", "expires_in": 60}).encode()
            self.send_response(200)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            seen["path"], seen["auth"] = self.path, self.headers.get("Authorization")
            seen["body"] = self.rfile.read(int(self.headers["content-length"]))
            body = json.dumps({"generation": "1"}).encode()
            self.send_response(200)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):
            pass
    s = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{s.server_address[1]}"
    try:
        meta = backup.upload(b"secret-bytes", "my-bucket", "ledgerline/x.tar.gz.enc", token_url=f"{base}/token",
                             upload_url=base + "/upload/{bucket}?ifGenerationMatch=0&name={name}")
    finally:
        s.shutdown()
    assert meta == {"generation": "1"} and seen["metadata_flavor"] == "Google" and seen["auth"] == "Bearer test-token"
    assert seen["path"] == "/upload/my-bucket?ifGenerationMatch=0&name=ledgerline%2Fx.tar.gz.enc" and seen["body"] == b"secret-bytes"
    assert "ifGenerationMatch=0" in backup.UPLOAD


def test_without_a_bucket_only_the_local_copy_is_made(client, settings, monkeypatch, capsys):
    monkeypatch.delenv("LEDGERLINE_BACKUP_BUCKET", raising=False)
    backup.main(Path(settings.data_dir), Path(settings.data_dir) / "backups", 7)
    assert "no off-server copy" in capsys.readouterr().out
    assert len([p for p in (Path(settings.data_dir) / "backups").iterdir() if p.is_dir()]) == 1
