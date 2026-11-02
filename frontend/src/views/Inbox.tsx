import { get, type AuditEvent, type Wallet } from "../api";
import { Card, Empty, ErrorNote, Loading, Money, Pill, useLoad } from "../components/ui";
import { CATEGORY_LABEL, money, relativeDays, when } from "../format";
import { go } from "../App";

interface Overview {
  wallets: Wallet[];
  deposit_counts: Record<string, number>;
  work_queue: { kind: "deposit" | "approval" | "operation"; id: string; status: string; currency: string; amount_minor: number; payer_name: string; reason: string | null }[];
  conservation: Record<string, boolean>;
  all_balanced: boolean;
  scorecard: { deposits: number; settled_without_human: number; approvals_by_person: number; escalations: number; double_payments: number; ledger_balanced: boolean };
  paused: boolean;
}

interface TreasuryLite {
  obligations: { id: string; payee: string; currency: string; amount_minor: number; due_at: string; status: string }[];
  plans: Record<string, { deficit: number }>;
}

const QUEUE_ACTION: Record<string, string> = {
  awaiting_evidence: "Ask the payer's agent",
  escalated: "Review and resolve",
  refund_awaiting_approval: "Approve or reject refund",
  refund_in_flight: "Track until final",
  pending: "Approve or reject",
  processing: "Reconcile with provider",
};

export function Inbox() {
  const ov = useLoad(() => get<Overview>("/overview"), []);
  const tr = useLoad(() => get<TreasuryLite & { wallets: Wallet[] }>("/treasury"), []);
  const activity = useLoad(() => get<AuditEvent[]>("/audit?limit=12"), []);
  const status = useLoad(() => get<{ now: string }>("/status"), []);
  const setup = useLoad(() => get<{ show: boolean; steps: { id: string; label: string; done: boolean; page: string }[] }>("/setup"), []);

  if (ov.error) return <ErrorNote error={ov.error} onRetry={ov.reload} />;
  const o = ov.data;

  return (
    <div className="stack">
      {setup.data?.show && (
        <Card title="Set up your company">
          <ul className="setup-list">
            {setup.data.steps.map((s) => (
              <li key={s.id} className={s.done ? "done" : ""}>
                <span aria-hidden="true">{s.done ? "✓" : "○"}</span>
                {s.done ? <span>{s.label}</span> : <a href={`#/${s.page}`}>{s.label}</a>}
                <span className="sr-only">{s.done ? "done" : "to do"}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <section aria-labelledby="cash-h">
        <h2 className="section-title" id="cash-h">Cash by currency</h2>
        <div className="wallets">
          {!o && [0, 1, 2].map((i) => <div className="card" key={i}><Loading rows={3} /></div>)}
          {o?.wallets.map((w) => (
            <div className="card wallet" key={w.currency}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span className="ccy">{w.currency} WALLET</span>
                <Pill status={o.conservation[w.currency] ? "matched" : "escalated"} label={o.conservation[w.currency] ? "Reconciled" : "Out of balance"} />
              </div>
              <div className="cash">{money(w.cash, w.currency)}</div>
              <dl>
                <dt>Reserve kept</dt><dd>{money(w.reserve, w.currency)}</dd>
                <dt>Held for customers</dt><dd>{money(w.customer_credits + w.unapplied_held + w.refunds_reserved, w.currency)}</dd>
                <dt>Bills due in window</dt><dd>{money(w.obligations_due_in_window, w.currency)}</dd>
                {w.fx_out_reserved > 0 && (<><dt>Reserved for FX out</dt><dd>{money(w.fx_out_reserved, w.currency)}</dd></>)}
                {w.fx_in_pending > 0 && (<><dt>Pending FX in (forecast)</dt><dd>{money(w.fx_in_pending, w.currency)}</dd></>)}
                {w.free_after_commitments < 0 ? (
                  <><dt className="free" title="Commitments exceed cash in this currency">Short by</dt>
                    <dd className="free neg">{money(-w.free_after_commitments, w.currency)}</dd></>
                ) : (
                  <><dt className="free">Free to use</dt><dd className="free">{money(w.free_after_commitments, w.currency)}</dd></>
                )}
              </dl>
            </div>
          ))}
        </div>
      </section>

      <div className="split">
        <Card title="Needs a decision" pad={false} actions={<a className="btn small" href="#/payments">All payments</a>}>
          {!o ? <Loading /> : o.work_queue.length === 0 ? (
            <Empty title="Nothing waiting">New deposits that cannot be matched by rule will appear here.</Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Item</th><th>Status</th><th className="num">Amount</th><th className="hide-sm">Next step</th></tr>
                </thead>
                <tbody>
                  {o.work_queue.map((w) => (
                    <tr key={w.kind + w.id} className="clickable" tabIndex={0}
                      onClick={() => (w.kind === "deposit" ? go("payments", { deposit: w.id }) : go(w.kind === "approval" ? "approvals" : "approvals"))}
                      onKeyDown={(e) => e.key === "Enter" && (w.kind === "deposit" ? go("payments", { deposit: w.id }) : go("approvals"))}>
                      <td>
                        <div className="primary-text">{w.kind === "deposit" ? w.payer_name : w.kind === "approval" ? `${w.id.startsWith("PAY-") ? "Bill payment" : "Refund"} to ${w.payer_name}` : `Operation ${w.id}`}</div>
                        <div className="secondary mono">{w.id}{w.reason ? ` · ${w.reason}` : ""}</div>
                      </td>
                      <td><Pill status={w.status} /></td>
                      <td className="num"><Money minor={w.amount_minor} ccy={w.currency} /></td>
                      <td className="hide-sm muted small">{QUEUE_ACTION[w.status] ?? "Open"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <div className="stack">
          <Card title="Upcoming obligations" pad={false} actions={<a className="btn small" href="#/treasury">Treasury</a>}>
            {!tr.data ? <Loading rows={3} /> : (
              <table>
                <tbody>
                  {tr.data.obligations.map((ob) => (
                    <tr key={ob.id}>
                      <td>
                        <div className="primary-text">{ob.payee}</div>
                        <div className="secondary">Due {status.data ? relativeDays(ob.due_at, status.data.now) : when(ob.due_at)}</div>
                      </td>
                      <td className="num">
                        <Money minor={ob.amount_minor} ccy={ob.currency} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card title="Reconciliation status">
            {!o ? <Loading rows={3} /> : o.scorecard.deposits === 0 ? (
              <Empty title="No deposits received yet">Payments appear here when your bank reports them, or when you record or import them.</Empty>
            ) : (
              <dl className="kv">
                <dt>Deposits received</dt><dd className="num" style={{ textAlign: "left" }}>{o.scorecard.deposits}</dd>
                <dt>Resolved by rules and verified evidence</dt><dd>{o.scorecard.settled_without_human}</dd>
                <dt>Decided by a person</dt><dd>{o.scorecard.approvals_by_person}</dd>
                <dt>Escalated for review</dt><dd>{o.scorecard.escalations}</dd>
                <dt>Duplicate payouts</dt><dd>{o.scorecard.double_payments}</dd>
                <dt>Ledger</dt><dd>{o.all_balanced ? <Pill status="matched" label="Balanced per currency" /> : <Pill status="escalated" label="Check ledger" />}</dd>
              </dl>
            )}
          </Card>
        </div>
      </div>

      <Card title="Recent activity" pad={false} actions={<a className="btn small" href="#/activity">Full audit trail</a>}>
        {!activity.data ? <Loading rows={4} /> : activity.data.length === 0 ? <Empty title="No activity yet" /> : (
          <div className="table-wrap">
            <table>
              <tbody>
                {activity.data.map((a) => (
                  <tr key={a.id}>
                    <td className="nowrap muted small">{when(a.at)}</td>
                    <td className="mono small">{a.action}</td>
                    <td className="small">{describe(a)}</td>
                    <td className="small muted hide-sm">{a.actor}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

export function describe(a: AuditEvent): string {
  const d = a.detail || {};
  switch (a.action) {
    case "deposit.received":
      return `${a.entity_id}: ${money(d.amount_minor, d.currency)} from ${d.payer}`;
    case "plan.initial":
    case "plan.revised":
    case "plan.operator":
      return `${a.entity_id} plan v${d.version}: ${CATEGORY_LABEL[d.category] ?? d.category}`;
    case "evidence.received":
      return `${a.entity_id}: payer answer ${d.verdict} via ${d.transport}`;
    case "allocation.created":
      return `${d.deposit_id} applied to ${a.entity_id}`;
    case "approval.invalidated":
      return `${a.entity_id} invalidated`;
    default:
      return `${a.entity_type} ${a.entity_id}`;
  }
}
