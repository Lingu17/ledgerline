import { get } from "../api";
import { Card, ErrorNote, Loading, Money, Pill, useLoad } from "../components/ui";
import { day, money } from "../format";

interface Summary {
  verdict: "ok" | "attention" | "problem"; headline: string; lookahead_days: number; paused: boolean;
  currencies: { currency: string; cash: number; reserve: number; bills_due: number; free: number; held: number; owed_to_us: number; overdue: number }[];
  agent: { payments: number; settled_without_person: number; refunds_avoided: number; false_claims_caught: number; early_cash_offers_paid: number; estimated_minutes_saved: number; minutes_per_payment_assumed: number };
  needs_you: { kind: string; id: string; status: string; currency: string; amount_minor: number; payer_name: string; reason: string | null }[];
  needs_you_total: number;
  short_bills: { obligation_id: string; payee: string; currency: string; amount_minor: number; due_at: string; decision: string; reason: string }[];
  trust: { ledger_balanced: boolean; log_intact: boolean; log_events: number; double_payments: number };
}

const VERDICT = { ok: ["matched", "All clear"], attention: ["pending", "Needs attention"], problem: ["escalated", "Problem"] } as const;

const NEXT_STEP: Record<string, string> = {
  awaiting_evidence: "Ask the payer's agent.",
  refund_awaiting_approval: "A person must approve or reject the refund.",
  refund_in_flight: "Refund on its way; track it until paid.",
  pending: "A person must approve or reject this.",
};

function link(kind: string, id: string) {
  return kind === "deposit" ? `#/payments?deposit=${id}` : "#/approvals";
}

export function Ceo() {
  const s = useLoad(() => get<Summary>("/ceo"), []);
  if (s.error) return <ErrorNote error={s.error} onRetry={s.reload} />;
  if (!s.data) return <div className="card"><Loading rows={6} /></div>;
  const { verdict, headline, lookahead_days, paused, currencies, agent, needs_you, needs_you_total, short_bills, trust } = s.data;
  const hours = (agent.estimated_minutes_saved / 60).toFixed(1);
  return (
    <div className="stack">
      <div className="card card-body row" style={{ justifyContent: "space-between" }}>
        <b style={{ fontSize: 17 }}>{headline}</b>
        <Pill status={VERDICT[verdict][0]} label={VERDICT[verdict][1]} />
      </div>
      {agent.payments === 0 && currencies.every((c) => c.bills_due === 0) && (
        <div className="notice small"><b>Nothing has happened here yet.</b> <a href="#/inbox">Finish setting up your company</a>, then add customers, invoices and bills, and this page fills in by itself.</div>
      )}
      {paused && <div className="notice risk"><b>Money-out is paused.</b> Matching keeps running. An owner can resume it under Settings.</div>}

      <Card title={`Are we safe? Cash and the next ${lookahead_days} days`} pad={false}>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Currency</th><th className="num">Cash</th><th className="num">Bills due</th><th className="num">Free to spend</th><th className="num">Owed to us</th><th className="num">Overdue</th></tr></thead>
            <tbody>
              {currencies.map((c) => (
                <tr key={c.currency}>
                  <td className="primary-text">{c.currency}</td>
                  <td className="num"><Money minor={c.cash} ccy={c.currency} /></td>
                  <td className="num"><Money minor={c.bills_due} ccy={c.currency} /></td>
                  <td className={`num ${c.free < 0 ? "neg" : ""}`}><Money minor={c.free} ccy={c.currency} /></td>
                  <td className="num"><Money minor={c.owed_to_us} ccy={c.currency} /></td>
                  <td className={`num ${c.overdue > 0 ? "neg" : ""}`}><Money minor={c.overdue} ccy={c.currency} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card-body small muted">Free to spend is after the reserve, held money and bills due. Currencies are never added together.</div>
      </Card>

      <div className="grid-2">
        <Card title="What needs you">
          {needs_you_total === 0 && short_bills.length === 0 ? <p className="small muted" style={{ margin: 0 }}>Nothing is waiting for a decision.</p> : (
            <div className="stack" style={{ gap: 10 }}>
              {short_bills.map((b) => (
                <div key={b.obligation_id} className="small">
                  <a href="#/treasury"><b>{b.payee}</b></a>: {money(b.amount_minor, b.currency)} due {day(b.due_at)}. {b.reason}
                </div>
              ))}
              {needs_you.map((w) => (
                <div key={w.id} className="small">
                  <a href={link(w.kind, w.id)}><b>{w.id}</b></a>: {money(w.amount_minor, w.currency)}, {w.payer_name}.{" "}{w.reason ?? NEXT_STEP[w.status] ?? ""}
                </div>
              ))}
              {needs_you_total > needs_you.length && <a className="small" href="#/inbox">{needs_you_total - needs_you.length} more in the Inbox</a>}
            </div>
          )}
        </Card>

        <Card title="What the agent handled">
          <dl className="kv">
            <dt>Payments received</dt><dd><a href="#/payments">{agent.payments}</a></dd>
            <dt>Decided with no person</dt><dd><a href="#/payments?status=matched">{agent.settled_without_person}</a></dd>
            <dt>Wrong refunds avoided</dt><dd><a href="#/evidence">{agent.refunds_avoided}</a></dd>
            <dt>False claims caught</dt><dd><a href="#/evidence">{agent.false_claims_caught}</a></dd>
            <dt>Early-payment offers paid</dt><dd><a href="#/treasury">{agent.early_cash_offers_paid}</a></dd>
            <dt>Time saved (estimate)</dt><dd>About {hours} h, assuming {agent.minutes_per_payment_assumed} minutes a payment. Not measured.</dd>
          </dl>
        </Card>
      </div>

      <Card title="Can I trust these numbers?">
        <dl className="kv">
          <dt>Ledger</dt><dd><a href="#/ledger">{trust.ledger_balanced ? <Pill status="matched" label="Balanced to the cent" /> : <Pill status="escalated" label="Does not balance" />}</a></dd>
          <dt>Audit log</dt><dd><a href="#/activity">{trust.log_intact ? <Pill status="matched" label={`Intact, ${trust.log_events} events`} /> : <Pill status="escalated" label="Altered" />}</a></dd>
          <dt>Double payments</dt><dd>{trust.double_payments}</dd>
        </dl>
      </Card>
    </div>
  );
}
