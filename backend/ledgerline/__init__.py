"""Ledgerline: incoming-payment reconciliation with verified payer-agent evidence."""
from __future__ import annotations

from pathlib import Path

__version__ = "0.2.0"
REPO_DIR = Path(__file__).resolve().parent.parent.parent


def build_commit(length: int = 12) -> str | None:
    """The commit this checkout runs, read from git's own files (no git binary needed); None outside a checkout."""
    git = REPO_DIR / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="ascii").strip()
        if head.startswith("ref: "):
            ref = head[5:]
            loose = git / ref
            if loose.is_file():
                return loose.read_text(encoding="ascii").strip()[:length]
            for line in (git / "packed-refs").read_text(encoding="ascii").splitlines():
                if line.endswith(" " + ref):
                    return line.split()[0][:length]
            return None
        return head[:length] if len(head) >= 7 else None
    except OSError:
        return None
