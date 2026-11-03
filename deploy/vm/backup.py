"""Consistent nightly copies of every Ledgerline SQLite database and payer-agent key, keeping the newest N, and an
encrypted copy off the server.

  python backup.py <data_dir> <backup_dir> <keep>

Uses SQLite's online backup API, so copies are consistent while the service keeps running. The local copies stay on
the same disk (protection against bad writes). When LEDGERLINE_BACKUP_BUCKET is set, each night's copy is also packed,
encrypted with AES-256-GCM under the key in LEDGERLINE_BACKUP_KEY_FILE (32 random bytes, base64; it never leaves the
server except in the owner's own safe place), and uploaded to that Cloud Storage bucket with the VM's own credentials.
The upload never overwrites an object, and the VM needs only permission to create objects, not to read or delete them.
restore_check.py decrypts a downloaded copy and verifies it.
"""
import base64
import io
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

MAGIC = b"LLBK1"
METADATA_TOKEN = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
UPLOAD = "https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o?uploadType=media&ifGenerationMatch=0&name={name}"


def snapshot(data: Path, dest_root: Path, keep: int) -> Path:
    dest = dest_root / time.strftime("%Y%m%d-%H%M%S")
    for src in data.rglob("*"):
        if dest_root in src.parents or not src.is_file():
            continue
        rel = src.relative_to(data)
        target = dest / rel
        if src.suffix == ".sqlite3":
            target.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(src) as s, sqlite3.connect(target) as t:
                s.backup(t)
        elif "payer_agents" in rel.parts:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    snapshots = sorted(p for p in dest_root.iterdir() if p.is_dir())
    for old in snapshots[:-keep]:
        shutil.rmtree(old)
    print(f"backup written to {dest}; {min(len(snapshots), keep)} kept")
    return dest


def read_key(path: Path) -> bytes:
    key = base64.b64decode(path.read_text(encoding="ascii").strip(), validate=True)
    if len(key) != 32:
        raise ValueError("backup key must be 32 bytes, base64-encoded")
    return key


def pack(snapshot_dir: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(snapshot_dir, arcname=snapshot_dir.name)
    return buf.getvalue()


def encrypt(plain: bytes, key: bytes, name: str) -> bytes:
    """MAGIC + nonce + AES-256-GCM ciphertext. The object name is bound in, so a copy cannot be passed off as another night's."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, plain, name.encode())


def decrypt(blob: bytes, key: bytes, name: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not blob.startswith(MAGIC):
        raise ValueError("not a Ledgerline backup")
    nonce = blob[len(MAGIC):len(MAGIC) + 12]
    return AESGCM(key).decrypt(nonce, blob[len(MAGIC) + 12:], name.encode())


def upload(blob: bytes, bucket: str, name: str, token_url: str = METADATA_TOKEN, upload_url: str = UPLOAD) -> dict:
    req = urllib.request.Request(token_url, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=10) as r:
        token = json.load(r)["access_token"]
    url = upload_url.format(bucket=urllib.parse.quote(bucket, safe=""), name=urllib.parse.quote(name, safe=""))
    req = urllib.request.Request(url, data=blob, method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def offsite(snapshot_dir: Path, bucket: str, key_file: Path) -> str:
    name = f"ledgerline/{snapshot_dir.name}.tar.gz.enc"
    blob = encrypt(pack(snapshot_dir), read_key(key_file), name)
    meta = upload(blob, bucket, name)
    print(f"off-server copy {name}: {len(blob)} bytes, generation {meta.get('generation')}")
    return name


def main(data: Path, dest_root: Path, keep: int) -> None:
    dest = snapshot(data, dest_root, keep)
    bucket = os.environ.get("LEDGERLINE_BACKUP_BUCKET", "").strip()
    if not bucket:
        print("no off-server copy: LEDGERLINE_BACKUP_BUCKET is not set")
        return
    offsite(dest, bucket, Path(os.environ.get("LEDGERLINE_BACKUP_KEY_FILE", "/etc/ledgerline/backup.key")))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]))
