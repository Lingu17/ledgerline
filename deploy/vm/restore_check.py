"""Check that an off-server backup can actually be restored. Changes nothing outside a temporary directory.

  python restore_check.py <downloaded .tar.gz.enc> <key file> [object name]

Decrypts the copy (the object name defaults to ledgerline/<file name>), unpacks it into a temporary directory, opens
the control database and every organization's ledger, and reports for each: whether every currency balances and
whether the audit chain verifies. Then deletes the temporary directory. Exit code 1 if anything does not verify.
Run it with the Ledgerline backend on the path, for example from the repository:
  PYTHONPATH=backend python deploy/vm/restore_check.py ~/Downloads/20261104-031500.tar.gz.enc ~/backup.key
"""
import io
import sqlite3
from contextlib import closing
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup import decrypt, read_key  # noqa: E402


def check(blob_path: Path, key_path: Path, name: str | None = None) -> bool:
    from ledgerline import audit, ledger, tamper_demo

    name = name or f"ledgerline/{blob_path.name}"
    plain = decrypt(blob_path.read_bytes(), read_key(key_path), name)
    ok = True
    with tempfile.TemporaryDirectory(prefix="ledgerline-restore-") as tmp:
        with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as tar:
            tar.extractall(tmp, filter="data")
        root = next(Path(tmp).iterdir())
        with closing(sqlite3.connect(root / "control.sqlite3")) as c:
            orgs = {r[0]: (r[1], r[2]) for r in c.execute("SELECT id, name, kind FROM organizations")}
            kinds = {k: v[1] for k, v in orgs.items()}
            org_ids = set(kinds)
            users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        books = sorted(root.glob("orgs/*/ledgerline.sqlite3"))  # each organization's books (not its simulated bank)
        print(f"{name}: control database opens: {len(org_ids)} organizations, {users} accounts, {len(books)} sets of books")
        missing = sorted(org_ids - {p.parent.name for p in books})
        if missing:
            ok = False
            print(f"  MISSING books for {len(missing)} organization(s): {', '.join(missing)}")
        for db_path in books:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                balanced = ledger.conservation(conn)["all_balanced"]
                # A practice company's open "Try to tamper" demo is put back in this temporary copy first, so the
                # check still proves that the demo's one change is the only one. Only for practice companies, as the
                # control database records them: in a real company such a setting is never honoured.
                demo = tamper_demo.undo(conn) if kinds.get(db_path.parent.name) == "sample" else None
                chain = audit.verify_chain(conn)
            finally:
                conn.close()
            ok = ok and balanced and chain["ok"]
            note = f"; practice tamper demo open at event {demo['id']}, checked with it put back" if demo else ""
            name, kind = orgs.get(db_path.parent.name, ("unknown", "?"))
            label = f"{name} ({'practice' if kind == 'sample' else 'company'}, {db_path.parent.name})"
            print(f"  {label}: books balanced={balanced}, audit chain ok={chain['ok']} ({chain['events']} events){note}")
    print("restore check:", "PASS" if ok else "FAIL", "(temporary copy deleted)")
    return ok


if __name__ == "__main__":
    from backup import BackupRefused

    try:
        sys.exit(0 if check(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else None) else 1)
    except BackupRefused as exc:
        print(f"restore check: REFUSED: {exc}", file=sys.stderr)
        sys.exit(1)
