import { get, type Deposit, type Evidence, type Plan } from "../api";
import { Card, Empty, ErrorNote, Loading, Pill, useLoad } from "../components/ui";
import { money, when } from "../format";
import { type Route } from "../App";
import { EvidenceBlock, PlanCard } from "./Payments";

interface Row {
  deposit: Deposit;
  plans: Plan[];
  evidence: Evidence[];
}

export function EvidenceView({ route }: { route: Route }) {
  const data = useLoad(() => get<Row[]>("/evidence"), []);
  const focus = route.params.get("deposit");
  if (data.error) return <ErrorNote error={data.error} onRetry={data.reload} />;
  if (!data.data) return <div className="card"><Loading rows={6} /></div>;
  if (data.data.length === 0)
    return (
      <div className="card">
        <Empty title="No evidence yet">When a deposit is ambiguous, the payer's agent is asked over MCP. Its signed answer and the three checks show up here.</Empty>
      </div>
    );
  const rows = focus ? data.data.filter((r) => r.deposit.id === focus) : data.data;
  return (
    <div className="stack">
      <div className="notice small">
        Payer answers are signed claims, not instructions. Each is checked for (1) the customer's registered Ed25519 key,
        (2) binding to this exact deposit, amount and a valid time window, and (3) agreement with our own invoice records.
        Only then can the plan change, and money-out still follows approval limits.
      </div>
      {rows.map((r) => {
        const initial = r.plans.find((p) => p.kind === "initial");
        const latest = r.plans[r.plans.length - 1];
        return (
          <Card key={r.deposit.id}
            title={<h2 className="row" style={{ gap: 8 }}>{r.deposit.payer_name} · {money(r.deposit.amount_minor, r.deposit.currency)} <Pill status={r.deposit.status} /></h2>}
            actions={<a className="btn small" href={`#/payments?deposit=${r.deposit.id}`}>Open payment</a>}>
            <div className="stack">
              <div className="muted small mono">{r.deposit.id} · received {when(r.deposit.received_at)} · reference “{r.deposit.reference || "none"}”</div>
              {initial && latest && latest.id !== initial.id ? (
                <div className="compare">
                  <PlanCard plan={initial} ccy={r.deposit.currency} />
                  <div className="arrow" aria-hidden="true">→</div>
                  <PlanCard plan={latest} ccy={r.deposit.currency} />
                </div>
              ) : initial ? <PlanCard plan={initial} ccy={r.deposit.currency} /> : null}
              {r.evidence.map((e) => <EvidenceBlock key={e.id} e={e} />)}
            </div>
          </Card>
        );
      })}
    </div>
  );
}
