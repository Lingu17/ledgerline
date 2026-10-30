"""Reproducible business evaluation: what share of payments Ledgerline resolves without a person, how many need one,
whether any allocation disagrees with an independent reference model, and how long automated decisions take.

  backend\\.venv\\Scripts\\python scripts\\evaluate.py --seeds 50

Everything runs in-process on synthetic data (simulated bank, simulated payer agents over in-memory MCP, no Claude,
no Airwallex), so the numbers measure the decision engine, not provider latency or model quality. Writes
docs/EVALUATION.md. Exit code 1 if any allocation disagrees with the reference model or a documented case differs.
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from ledgerline.api.app import create_app  # noqa: E402
from ledgerline.config import load_settings  # noqa: E402
from tests.accuracy_harness import PASSWORD, Mismatch, Scenario  # noqa: E402

# The six documented reference cases (docs/DEMO_SCRIPT.md) and the outcome each must reach.
REFERENCE = {
    "DEP-1001": ("clean_match", "matched", "split reference INV 2231 + 2240, exact"),
    "DEP-1002": ("clean_with_fee", "matched", "EUR 15 short, within the bank-fee tolerance"),
    "DEP-1003": ("partial_payment", "partially_applied", "GBP 1,200 short: partial, exact balance requested"),
    "DEP-1004": ("evidence_rejected", "escalated", "payer agent claims another customer's invoice: rejected"),
    "DEP-1005": ("verified_advance_credit", "credited", "apparent duplicate is a verified advance: credit, no refund"),
    "DEP-1006": ("verified_duplicate", "refunded", "genuine duplicate: refund after a person approves, SENT then PAID"),
}
STEPS = ["seed", "deposits", "links", "agents", "treasury", "approve", "bank_sent", "bank_paid"]


def outcome(detail: dict) -> str:
    kinds = {p["kind"] for p in detail["plans"]}
    if "operator" in kinds:
        return "resolved_by_person"
    if any(a.get("decided_by") and not str(a["decided_by"]).startswith("policy:") for a in detail.get("approvals", [])):
        return "approved_by_person"  # the decision was automatic; a person approved the money-out (four-eyes)
    if detail["status"] == "escalated":
        return "with_a_person"
    return "resolved_automatically"


def reference_case(app) -> dict:
    c = TestClient(app)
    r = c.post("/api/auth/signup", json={"email": f"eval-{random.randrange(10**8)}@eval.test", "name": "Eval", "password": PASSWORD,
                                          "organization_name": "Eval reference", "start_with": "sample"})
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    timings, approvals = {}, 0
    for step in STEPS:
        if step == "approve":
            for a in c.get("/api/approvals").json():
                if a["status"] == "pending":
                    assert c.post(f"/api/approvals/{a['id']}/approve", json={"scope_hash": a["scope_hash"]}).status_code == 200
                    approvals += 1
        t0 = time.perf_counter()
        assert c.post("/api/demo/step", json={"step": step}).status_code == 200, step
        timings[step] = (time.perf_counter() - t0) * 1000
    rows = []
    for did, (cat, status, why) in REFERENCE.items():
        d = c.get(f"/api/deposits/{did}").json()
        rows.append((did, why, f"{cat}/{status}", f"{d['category']}/{d['status']}", (d["category"], d["status"]) == (cat, status), outcome(d)))
    return {"rows": rows, "timings": timings, "approvals": approvals, "score": c.get("/api/overview").json()["scorecard"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--report", default=str(ROOT / "docs" / "EVALUATION.md"))
    args = ap.parse_args()
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="ledgerline-eval-") as tmp:
        app = create_app(load_settings({"LEDGERLINE_DATA_DIR": tmp, "LEDGERLINE_PAYER_MCP_TRANSPORT": "memory",
                                        "LEDGERLINE_SAMPLE_WORKSPACE": "1", "ANTHROPIC_API_KEY": "", "AIRWALLEX_CLIENT_ID": "",
                                        "AIRWALLEX_API_KEY": "", "GOOGLE_CLIENT_ID": "", "APPLE_CLIENT_ID": "",
                                        "LEDGERLINE_LOG_LEVEL": "WARNING"}))
        ref = reference_case(app)
        outcomes: Counter[str] = Counter()
        categories: Counter[str] = Counter()
        mismatched_seeds: list[str] = []
        latencies: list[float] = []
        for seed in range(1, args.seeds + 1):
            s = Scenario(app, seed)
            try:
                s.run()
            except Mismatch as exc:
                mismatched_seeds.append(f"seed {seed}: {str(exc)[:300]}")
            for d in s.c.get("/api/deposits", params={"limit": 500}).json():
                t0 = time.perf_counter()
                detail = s.c.get(f"/api/deposits/{d['id']}").json()
                latencies.append((time.perf_counter() - t0) * 1000)
                outcomes[outcome(detail)] += 1
                categories[detail["plans"][0]["category"] if detail["plans"] else "none"] += 1
            print(f"seed {seed}: {'MISMATCH' if mismatched_seeds and mismatched_seeds[-1].startswith(f'seed {seed}:') else 'ok'}", flush=True)
    total = sum(outcomes.values())
    ref_ok = all(r[4] for r in ref["rows"])
    pct = lambda n: f"{100 * n / total:.1f}%" if total else "n/a"  # noqa: E731
    lines = [
        "# Evaluation",
        "",
        f"Generated by `scripts/evaluate.py --seeds {args.seeds}` in {time.time() - started:.0f} s on {time.strftime('%Y-%m-%d')}. "
        "Synthetic data only: simulated bank, simulated payer agents over MCP, no Claude and no Airwallex, so these numbers "
        "measure the decision engine and controls, not model quality, provider latency or real customer behaviour.",
        "",
        "## Documented reference cases",
        "",
        f"All six reach their documented outcome: **{ref_ok}**. Scorecard: `{ref['score']}`. People approved {ref['approvals']} refund(s).",
        "",
        "| Deposit | Case | Expected | Actual | Match | Handled |",
        "|---|---|---|---|---|---|",
    ] + [f"| {did} | {why} | {exp} | {act} | {'yes' if ok else '**NO**'} | {how.replace('_', ' ')} |" for did, why, exp, act, ok, how in ref["rows"]] + [
        "",
        "Server time per walkthrough step (in-process, local machine; includes the MCP agent calls in `agents`):",
        "",
        "| Step | ms |", "|---|---|",
    ] + [f"| {k} | {v:.0f} |" for k, v in ref["timings"].items()] + [
        "",
        f"## Randomized companies ({args.seeds} seeds, {total:,} payments)",
        "",
        "Each seed builds a synthetic company and sends statement lines (exact, split, fee-short, partial, overpaid, duplicate, "
        "wrong currency, unknown payer, other customer's invoice, malformed rows and re-imports); an operator then resolves some "
        "escalations. An independent reference model predicts every balance and status.",
        "",
        "| Measure | Result |", "|---|---|",
        f"| Allocations disagreeing with the reference model | **{len(mismatched_seeds)} seeds** with any disagreement |",
        f"| Resolved automatically (rules, no person) | {outcomes['resolved_automatically']:,} ({pct(outcomes['resolved_automatically'])}) |",
        f"| Resolved by a person (operator decision recorded) | {outcomes['resolved_by_person']:,} ({pct(outcomes['resolved_by_person'])}) |",
        f"| Decided automatically, money-out approved by a person | {outcomes['approved_by_person']:,} ({pct(outcomes['approved_by_person'])}) |",
        f"| Still waiting for a person, with a stated reason | {outcomes['with_a_person']:,} ({pct(outcomes['with_a_person'])}) |",
        f"| Payment detail API time, median / p95 | {statistics.median(latencies):.1f} ms / {sorted(latencies)[int(len(latencies) * 0.95)]:.1f} ms |",
        "",
        "First-plan categories:",
        "",
        "| Category | Payments |", "|---|---|",
    ] + [f"| {k} | {v:,} |" for k, v in categories.most_common()] + [
        "",
        "## What this does not show",
        "",
        "- Real customers' payment mix: the randomized mix is designed to exercise every rule, so its escalation share is not a forecast.",
        "- Claude's accuracy on real remittances, and live provider timing: see INTEGRATION_EVIDENCE for the observed live calls.",
        "- Time saved for a finance team, adoption or willingness to pay: not measured; no customer evidence exists yet.",
        "",
        "## Disagreements",
        "",
    ] + ([f"- {m}" for m in mismatched_seeds] or ["None."])
    Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[6:9]))
    return 1 if mismatched_seeds or not ref_ok else 0


if __name__ == "__main__":
    sys.exit(main())
