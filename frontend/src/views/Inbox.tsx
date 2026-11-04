import { useState } from "react";
import { get, type AuditEvent, type Wallet } from "../api";
import { Card, Empty, ErrorNote, Loading, Money, Pill, useLoad } from "../components/ui";
import { CATEGORY_LABEL, money, plainReason, relativeDays, when, actionLabel, actorLabel, whenUtc } from "../format";
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

const GUIDE_KEY = "ledgerline.guide.hidden";

function guideHidden() {
  try { return localStorage.getItem(GUIDE_KEY) === "1"; } catch { return false; }
}

function FirstVisit() {
  const [hidden, setHidden] = useState(guideHidden);
  if (hidden) return null;
  const hide = () => {
    try { localStorage.setItem(GUIDE_KEY, "1"); } catch { /* the guide simply comes back next time */ }
    setHidden(true);
  };
  return (
    <Card title="See what it does in three minutes" actions={<button className="btn small" onClick={hide}>Hide this guide</button>}>
      <p className="small" style={{ margin: "0 0 8px" }}>
        <button className="btn small primary" onClick={() => window.dispatchEvent(new Event("ledgerline:tour"))}>Take the guided tour</button>{" "}
        (the same as <b>Show me</b> at the top), or follow these steps yourself:
      </p>
      <ol className="small" style={{ margin: 0, paddingLeft: 20, lineHeight: 1.8 }}>
        <li><a href="#/payments?deposit=DEP-1005">Open this payment</a> and click <b>Ask payer's agent</b>: what looks like a duplicate turns out to be an advance, and the refund is dropped before any money moves.</li>
        <li><a href="#/payments?deposit=DEP-1004">Open this one</a> and ask again: the answer is correctly signed but false, so it is rejected and a person gets the reason.</li>
        <li><a href="#/walkthrough">Run the practice steps</a>: a currency conversion, a refund that needs approval, and the bank moving from SENT to PAID.</li>
        <li><a href="#/ceo">See the CEO view</a>: the whole company on one screen.</li>
      </ol>
    </Card>
  );
}

export function Inbox() {
  const ov = useLoad(() => get<Overview>("/overview"), []);
  const tr = useLoad(() => get<TreasuryLite & { wallets: Wallet[] }>("/treasury"), []);
  const activity = useLoad(() => get<AuditEvent[]>("/audit?limit=12"), []);
  const status = useLoad(() => get<{ now: string; org: { kind: string } | null }>("/status"), []);
  const setup = useLoad(() => get<{ show: boolean; steps: { id: string; label: string; done: boolean; page: string }[] }>("/setup"), []);

  if (ov.error) return <ErrorNote error={ov.error} onRetry={ov.reload} />;
  const o = ov.data;

  return (
    <div className="stack">
      {status.data?.org?.kind === "sample" && <FirstVisit />}
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
                <Pill status={o.conservation[w.currency] ? "matched" : "escalated"} label={o.conservation[w.currency] ? "Books balance" : "Out of balance"} />
              </div>
              <div className="cash">{money(w.cash, w.currency)}</div>
              <dl>
                <dt>Reserve kept</dt><dd>{money(w.reserve, w.currency)}</dd>
                <dt>Held for customers</dt><dd>{money(w.customer_credits + w.unapplied_held + w.refunds_reserved, w.currency)}</dd>
                <dt>Bills due soon</dt><dd>{money(w.obligations_due_in_window, w.currency)}</dd>
                {w.fx_out_reserved > 0 && (<><dt>Reserved for FX out</dt><dd>{money(w.fx_out_reserved, w.currency)}</dd></>)}
                {w.fx_in_pending > 0 && (<><dt>Pending FX in (forecast)</dt><dd>{money(w.fx_in_pending, w.currency)}</dd></>)}
                {!w.cash_known ? (
                  <><dt className="free">Opening balance</dt><dd className="free"><a href="#/treasury">Not set yet</a></dd></>
                ) : w.free_after_commitments < 0 ? (
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
                    <tr key={w.kind + w.id} className="clickable" tabIndex={0} aria-label={w.kind === "deposit" ? `Open payment ${w.id} from ${w.payer_name}` : `Open ${w.id}`}
                      onClick={() => (w.kind === "deposit" ? go("payments", { deposit: w.id }) : go(w.kind === "approval" ? "approvals" : "approvals"))}
                      onKeyDown={(e) => e.key === "Enter" && (w.kind === "deposit" ? go("payments", { deposit: w.id }) : go("approvals"))}>
                      <td>
                        <div className="primary-text">{w.kind === "deposit" ? w.payer_name : w.kind === "approval" ? `${w.id.startsWith("PAY-") ? "Bill payment" : "Refund"} to ${w.payer_name}` : `Operation ${w.id}`}</div>
                        <div className="secondary"><span className="mono">{w.id}</span>{w.reason ? ` · ${plainReason(w.reason)}` : ""}</div>
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
                <dt>Deposits received</dt><dd className="num" style={{ textAlign: "left" }}><a href="#/payments">{o.scorecard.deposits}</a></dd>
                <dt>Decided with no person</dt><dd><a href="#/payments?status=matched">{o.scorecard.settled_without_human}</a></dd>
                <dt>Decided by a person</dt><dd><a href="#/approvals">{o.scorecard.approvals_by_person}</a></dd>
                <dt>Waiting for a person</dt><dd><a href="#/payments?status=escalated">{o.scorecard.escalations}</a></dd>
                <dt>Duplicate payouts</dt><dd><a href="#/ledger">{o.scorecard.double_payments}</a></dd>
                <dt>Ledger</dt><dd>{o.all_balanced ? <Pill status="matched" label="Balanced per currency" /> : <Pill status="escalated" label="Check ledger" />}</dd>
              </dl>
            )}
          </Card>
        </div>
      </div>

      <Card title="Recent activity" pad={false} actions={<a className="btn small" href="#/activity">Full audit trail</a>}>
        {!activity.data ? <Loading rows={4} /> : activity.data.length === 0 ? <Empty title="No activity yet">Every decision and money movement will be recorded here.</Empty> : (
          <div className="table-wrap">
            <table>
              <tbody>
                {activity.data.map((a) => (
                  <tr key={a.id}>
                    <td className="nowrap muted small" title={whenUtc(a.at)}>{when(a.at)}</td>
                    <td className="small" title={a.action}>{actionLabel(a.action)}</td>
                    <td className="small">{describe(a)}</td>
                    <td className="small muted hide-sm" title={a.actor}>{actorLabel(a.actor)}</td>
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
