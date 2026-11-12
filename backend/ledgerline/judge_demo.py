"""One-click judge demos are deleted 48 hours after they were made: the company, its storage and its two demo people."""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("ledgerline.judge_demo")


def cleanup(app: Any) -> int:
    """Delete every judge demo older than 48 hours. Safe to call repeatedly. Returns how many were deleted."""
    from .tenancy import delete_org_storage

    deleted = 0
    for org_id in app.state.control.expired_judge_demos():
        try:
            app.state.control.forget_judge_demo(org_id)
            app.state.orgs.invalidate(org_id)
            delete_org_storage(app.state.settings, org_id)
            deleted += 1
        except Exception as exc:  # noqa: BLE001 - one bad demo must not stop the others
            log.warning("judge demo %s not deleted: %s", org_id, type(exc).__name__)
    return deleted
