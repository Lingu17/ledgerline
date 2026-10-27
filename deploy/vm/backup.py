"""Consistent nightly copies of every Ledgerline SQLite database and payer-agent key, keeping the newest N.

  python backup.py <data_dir> <backup_dir> <keep>

Uses SQLite's online backup API, so copies are consistent while the service keeps running.
Backups stay on the same persistent volume (protection against bad writes, not disk loss).
"""
import shutil
import sqlite3
import sys
import time
from pathlib import Path


def main(data: Path, dest_root: Path, keep: int) -> None:
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


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]))
