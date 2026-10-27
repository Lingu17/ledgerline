"""Administrative commands.

  python -m ledgerline.manage create-owner --email you@company.test --org "Company" [--sample]
  python -m ledgerline.manage migrate

Passwords are read interactively (or from LEDGERLINE_BOOTSTRAP_PASSWORD for scripted local setup);
nothing is written to disk except the hashed credential.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from .config import load_settings
from .control import AuthError, ControlPlane
from .migrations import TENANT, migrate
from .tenancy import OrgRegistry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ledgerline.manage")
    sub = parser.add_subparsers(dest="cmd", required=True)
    co = sub.add_parser("create-owner", help="create a user who owns a new organization")
    co.add_argument("--email", required=True)
    co.add_argument("--name", default="")
    co.add_argument("--org", required=True)
    co.add_argument("--sample", action="store_true", help="seed the reference sample data")
    sub.add_parser("migrate", help="apply pending migrations to the control plane and every organization")
    args = parser.parse_args(argv)

    settings = load_settings()
    control = ControlPlane(settings.data_dir / "control.sqlite3")
    registry = OrgRegistry(settings, control, control.clock)
    if args.cmd == "migrate":
        for org_id in control.all_org_ids():
            with registry.get(org_id).conn() as conn:
                migrate(conn, TENANT)
        print(f"migrations applied; organizations: {len(control.all_org_ids())}")
        return 0

    password = os.environ.get("LEDGERLINE_BOOTSTRAP_PASSWORD") or getpass.getpass("Password (12+ chars, upper, lower, digit): ")
    try:
        _token, org_id = control.signup(email=args.email, name=args.name or args.email.split("@")[0], password=password,
                                        org_name=args.org, kind="sample" if args.sample else "workspace")
    except AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    registry.provision(org_id, sample=args.sample)
    print(f"created owner {args.email.lower()} for organization {args.org!r} ({org_id}); sign in at http://{settings.host}:{settings.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
