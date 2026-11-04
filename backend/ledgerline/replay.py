"""Replay a payment decision: run the same rules again on the inputs stored with a plan, and compare. Read-only.

Each plan the rules make keeps the exact inputs they read (`plans.inputs`), and the audit event for that plan keeps
their hash. A replay checks the stored inputs against that hash, runs the pure rules on them again
(`matching.initial_plan` for a first plan; `evidence.verify` and `reconcile.plan_after_answer` for a plan revised by a
payer agent's answer) and says whether the result is the same plan. A person's decision has no rules to re-run.
"""
from __future__ import annotations

import json
from typing import Any

from . import db
from .clock import parse_iso
from .context import AppContext
from .evidence import verify
from .matching import InvoiceView, initial_plan


class ReplayError(LookupError):
    pass


def _views(stored: dict[str, Any]) -> dict[str, InvoiceView]:
    return {k: InvoiceView(**v) for k, v in stored.items()}


def rerun(inputs: dict[str, Any]) -> dict[str, Any]:
    """The plan (and, for an answer, the checks) the rules give for these inputs."""
    from .reconcile import plan_after_answer

    if inputs["rule"] == "initial_plan":
        plan = initial_plan(inputs["deposit"], inputs["customers"], _views(inputs["invoices"]), inputs["fee_tolerance_minor"],
                            inputs["fee_tolerance_bps"]).to_dict()
        return {"plan": plan, "checks": None, "verdict": None}
    if inputs["rule"] == "payer_agent_answer":
        if inputs["envelope"] is None:
            result = {"checks": [], "verdict": "rejected", "reason": inputs["no_envelope_reason"], "claim": None}
        else:
            result = verify(inputs["envelope"], deposit=inputs["deposit"], asked_customer_id=inputs["asked_customer_id"],
                            registry=inputs["registry"], invoices=_views(inputs["invoices"]), now=parse_iso(inputs["now"]),
                            max_ttl_seconds=inputs["max_ttl_seconds"], skew_seconds=inputs["skew_seconds"],
                            applicable_minor=inputs["applicable_minor"]).to_dict()
            if result["verdict"] == "verified" and inputs["already_used"]:
                result["verdict"], result["reason"] = "rejected", "replayed answer: this exact signed claim was already used"
        plan = plan_after_answer(result, inputs["deposit"], inputs["applicable_minor"])
        return {"plan": plan, "checks": [{c["name"]: c["passed"]} for c in result["checks"]], "verdict": result["verdict"]}
    raise ReplayError(f"unknown rule {inputs['rule']!r}")


def replay_plan(ctx: AppContext, deposit_id: str, version: int) -> dict[str, Any]:
    from .reconcile import inputs_hash

    with ctx.conn() as conn:
        p = db.row(conn, "SELECT * FROM plans WHERE deposit_id = ? AND version = ?", (deposit_id, version))
        if p is None:
            raise ReplayError("unknown plan")
        logged = None
        for e in db.rows(conn, "SELECT detail FROM audit_events WHERE entity_type = 'deposit' AND entity_id = ? AND action IN "
                               "('plan.initial', 'plan.revised') ORDER BY id", (deposit_id,)):
            detail = json.loads(e["detail"] or "{}")
            if detail.get("version") == version:
                logged = detail
        ev = db.row(conn, "SELECT checks, verdict FROM evidence WHERE id = ?", (p["evidence_id"],)) if p["evidence_id"] else None
    out: dict[str, Any] = {"deposit_id": deposit_id, "version": version, "kind": p["kind"], "replayable": False}
    if p["kind"] == "operator":
        return {**out, "reason": "a person made this decision, so there are no rules to re-run"}
    if not p["inputs"]:
        why = ("it was made by a currency conversion, not by the matching rules" if p["category"] == "converted_settlement"
               else "it was recorded before Ledgerline kept the inputs needed to replay it")
        return {**out, "reason": why}
    inputs = json.loads(p["inputs"])
    untampered = logged is not None and inputs_hash(inputs) == logged.get("inputs_hash")
    again = rerun(inputs)
    stored = {"category": p["category"], "summary": p["summary"], "actions": json.loads(p["actions"])}
    differences = [f"{k}: stored {json.dumps(stored[k])}, re-run {json.dumps(again['plan'][k])}"
                   for k in ("category", "summary", "actions") if stored[k] != again["plan"][k]]
    if again["verdict"] is not None and ev is not None:
        was = [{c["name"]: c["passed"]} for c in json.loads(ev["checks"])]
        if (was, ev["verdict"]) != (again["checks"], again["verdict"]):
            differences.append(f"checks: stored {ev['verdict']} {json.dumps(was)}, re-run {again['verdict']} {json.dumps(again['checks'])}")
    return {**out, "replayable": True, "rule": inputs["rule"], "identical": not differences, "inputs_untampered": untampered,
            "ok": untampered and not differences, "differences": differences, "recomputed": again}
