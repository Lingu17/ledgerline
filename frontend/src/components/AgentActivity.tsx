import { get, type AuditEvent } from "../api";
import { actionLabel, money } from "../format";
import { Card, useLoad } from "./ui";

/** What the agent did by itself, payment by payment, read from the audit log only. Nothing here decides or changes
 *  anything: it shows the steps the rules and the agent took without a person, in the order the log recorded them. */

// Actors that are not a person: the rules, the system, the automatic asker, a payer's agent, a policy.
function bySelf(actor: string): boolean {
  return !actor.includes("@") && !["practice_payment", "manual_import", "csv_import", "webhook", "provider", "practice-teammate"].includes(actor);
}

const SHOWN = new Set(["plan.initial", "agent.asked_automatically", "evidence.received", "plan.revised", "credit.created", "allocation.created",
  "writeoff.created", "approval.created", "refund.created", "refund.paid"]);

function stepText(e: AuditEvent): string | null {
  const d = e.detail ?? {};
  switch (e.action) {
    case "agent.asked_automatically": return "Asked the payer's agent, with no click";
    case "evidence.received": {
      const checks: Record<string, boolean>[] = Array.isArray(d.checks) ? d.checks : [];
      const passed = checks.filter((c) => Object.values(c)[0] === true).length;
      return checks.length ? `Checked the signed answer: ${passed} of ${checks.length} checks passed` : "Payer's agent answered";
    }
    case "approval.created": return d.status === "approved" ? "Refund approved by policy, under the limit" : null;
    default: return actionLabel(e.action);
  }
}

interface Story { deposit: string; payer: string; amount: string; steps: string[]; noClick: boolean; last: number }

function stories(events: AuditEvent[]): Story[] {
  const by = new Map<string, Story>();
  for (const e of [...events].sort((a, b) => a.id - b.id)) {
    const dep = e.entity_type === "deposit" ? e.entity_id : (e.detail?.deposit_id as string | undefined);
    if (!dep) continue;
    if (e.action === "deposit.received") {
      const d = e.detail ?? {};
      by.set(dep, { deposit: dep, payer: String(d.payer ?? ""), amount: d.amount_minor != null && d.currency ? money(d.amount_minor, d.currency) : "",
        steps: [], noClick: false, last: e.id });
      continue;
    }
    const s = by.get(dep);
    if (!s || !SHOWN.has(e.action) || !bySelf(e.actor)) continue;
    const text = stepText(e);
    if (!text) continue;
    if (e.action === "agent.asked_automatically") {
      // The log records the ask after the answer it led to (same transaction); tell it in the order it happened.
      s.noClick = true;
      const answered = s.steps.findIndex((t) => t.startsWith("Checked the signed answer") || t === "Payer's agent answered");
      s.steps.splice(answered >= 0 ? answered : s.steps.length, 0, text);
    } else if (s.steps[s.steps.length - 1] !== text) s.steps.push(text);
    s.last = e.id;
  }
  // A payment the rules only matched once is not much of a story; show the ones where the agent did more.
  return [...by.values()].filter((s) => s.steps.length >= 2).sort((a, b) => b.last - a.last);
}

export function AgentActivity({ limit = 5 }: { limit?: number }) {
  const log = useLoad(() => get<AuditEvent[]>("/audit?limit=500"), []);
  const list = log.data ? stories(log.data).slice(0, limit) : [];
  return (
    <Card title="What the agent did by itself">
      <p className="small muted" style={{ margin: "0 0 10px" }}>
        Each step was taken by the rules or the agent, not a person, and is read from the audit log.
      </p>
      {log.data && list.length === 0 && <p className="small muted" style={{ margin: 0 }}>Nothing yet: payments appear here once the agent has acted on them.</p>}
      <ol className="agent-activity">
        {list.map((s) => (
          <li key={s.deposit}>
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              <a href={`#/payments?deposit=${s.deposit}`} className="mono small">{s.deposit}</a>
              <span className="small">{s.payer}{s.amount ? ` · ${s.amount}` : ""}</span>
              {s.noClick && <span className="pill ok">No click</span>}
            </div>
            <div className="small muted">{s.steps.join(" → ")}</div>
          </li>
        ))}
      </ol>
    </Card>
  );
}
