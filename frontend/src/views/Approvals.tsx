import { useState } from "react";
import { get, post, type Approval, type Operation } from "../api";
import { Card, Checks, Empty, ErrorNote, Loading, Modal, Money, Pill, useAction, useLoad } from "../components/ui";
import { money, when } from "../format";
import { useAuth } from "../auth";

export function Approvals({ localMode, sandboxMode = false }: { localMode: boolean; sandboxMode?: boolean }) {
  const approvals = useLoad(() => get<Approval[]>("/approvals"), []);
  const ops = useLoad(() => get<Operation[]>("/operations"), []);
  const { run, busy } = useAction();
  const [confirm, setConfirm] = useState<{ a: Approval; approve: boolean } | null>(null);
  const { can, me } = useAuth();
  const op = can("operator");
  const canSimulate = localMode || (sandboxMode && can("owner"));
  const simulationLabel = localMode ? "Simulate" : "Sandbox API";

  const pending = approvals.data?.filter((a) => a.status === "pending") ?? [];
  const ready = approvals.data?.filter((a) => a.status === "approved") ?? [];
  const history = approvals.data?.filter((a) => !["pending", "approved"].includes(a.status)) ?? [];

  if (approvals.error) return <ErrorNote error={approvals.error} onRetry={approvals.reload} />;
  return (
    <div className="stack">
      <section className="stack">
        <h2 className="section-title" style={{ margin: 0 }}>Waiting for a decision</h2>
        {!approvals.data ? <div className="card"><Loading /></div> : pending.length === 0 ? (
          <div className="card"><Empty title="No approvals waiting">Refunds above the auto-limit and operator returns appear here.</Empty></div>
        ) : pending.map((a) => <ScopeCard key={a.id} a={a} busy={busy} canDecide={op} ownProposal={a.created_by === me?.user.email}
            onDecide={(approve) => setConfirm({ a, approve })} />)}
      </section>

      {ready.length > 0 && (
        <section className="stack">
          <h2 className="section-title" style={{ margin: 0 }}>Approved, not yet executed</h2>
          {ready.map((a) => (
            <div className="card card-body row" key={a.id} style={{ justifyContent: "space-between" }}>
              <div>
                <b>{money(a.scope.amount_minor, a.scope.currency)}</b> to {a.scope.destination}
                <div className="muted small">{a.id} · approved by {a.decided_by} {when(a.decided_at)}</div>
              </div>
              {op && <button className="btn primary" disabled={!!busy}
                onClick={() => run("exec" + a.id, () => post(`/approvals/${a.id}/execute`), (r: any) => `Refund ${r.operation.id} is ${r.operation.status}`)}>
                {busy === "exec" + a.id ? "Sending…" : "Execute refund"}
              </button>}
            </div>
          ))}
        </section>
      )}

      <Card title="Money-out operations" pad={false}>
        {!ops.data ? <Loading /> : ops.data.length === 0 ? <Empty title="No operations yet" /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Operation</th><th>Status</th><th className="num">Amount</th><th className="hide-sm">History</th><th /></tr></thead>
              <tbody>
                {ops.data.map((o) => (
                  <tr key={o.id}>
                    <td>
                      <div className="primary-text">{o.kind === "refund" ? `Refund · ${o.deposit_id}` : `Conversion → ${o.destination}`}</div>
                      <div className="secondary mono">{o.id} · request {o.request_id.slice(0, 13)}…{o.provider_id ? ` · bank ${o.provider_id}` : ""}</div>
                      {o.needs_reconciliation === 1 && <div className="secondary neg">Outcome unknown: {o.last_error}. Reconcile before anything is retried.</div>}
                    </td>
                    <td>
                      <Pill status={o.status} />
                      {o.status === "sent" && <div className="secondary">Not final until paid</div>}
                    </td>
                    <td className="num"><Money minor={o.amount_minor} ccy={o.currency} /></td>
                    <td className="hide-sm small">
                      {o.events?.map((e) => <div key={e.id}><span className="muted">{when(e.at)}</span> {e.from_status ? `${e.from_status} → ` : ""}{e.to_status}</div>)}
                    </td>
                    <td>
                      {op && <div className="row" style={{ justifyContent: "flex-end" }}>
                        {["processing", "sent", "pending"].includes(o.status) && (
                          <button className="btn small" disabled={!!busy} onClick={() => run("sync" + o.id, () => post(`/operations/${o.id}/sync`), "Checked with provider")}>Check status</button>
                        )}
                        {canSimulate && o.kind === "refund" && o.provider_id && o.status === "processing" && (
                          <button className="btn small" disabled={!!busy} title={localMode ? "Local simulated bank" : "Calls Airwallex sandbox transfer transition API; no real money"}
                            onClick={() => run("sim" + o.id, () => post(`/operations/${o.id}/simulate-bank`, { next_status: "SENT" }), `${simulationLabel}: SENT`)}>{simulationLabel}: sent</button>
                        )}
                        {canSimulate && o.kind === "refund" && o.provider_id && o.status === "sent" && (
                          <>
                            <button className="btn small" disabled={!!busy} title={localMode ? "Local simulated bank" : "Calls Airwallex sandbox transfer transition API; no real money"}
                              onClick={() => run("sim" + o.id, () => post(`/operations/${o.id}/simulate-bank`, { next_status: "PAID" }), `${simulationLabel}: PAID`)}>{simulationLabel}: paid</button>
                            {localMode && <button className="btn small danger" disabled={!!busy} title="Local workspace only"
                              onClick={() => run("sim" + o.id, () => post(`/operations/${o.id}/simulate-bank`, { next_status: "FAILED" }), "Simulated bank: FAILED")}>Simulate: failed</button>}
                          </>
                        )}
                      </div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {history.length > 0 && (
        <Card title="Decided" pad={false}>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Approval</th><th>Status</th><th className="num">Amount</th><th className="hide-sm">Detail</th></tr></thead>
              <tbody>
                {history.map((a) => (
                  <tr key={a.id}>
                    <td style={{ minWidth: 140 }}><div className="mono nowrap">{a.id}</div><div className="secondary">{a.scope.destination}</div></td>
                    <td><Pill status={a.status} /></td>
                    <td className="num"><Money minor={a.scope.amount_minor} ccy={a.scope.currency} /></td>
                    <td className="hide-sm small">{a.invalidated_reason ?? (a.decided_by ? `${a.decided_by} · ${when(a.decided_at)}` : a.reason)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {confirm && (
        <Modal title={confirm.approve ? "Approve refund" : "Reject refund"} onClose={() => setConfirm(null)}>
          <p style={{ marginTop: 0 }}>
            {confirm.approve ? "You are approving exactly:" : "You are rejecting:"} <b>{money(confirm.a.scope.amount_minor, confirm.a.scope.currency)}</b> to{" "}
            <b>{confirm.a.scope.destination}</b> for deposit <span className="mono">{confirm.a.scope.deposit_id}</span>.
          </p>
          <p className="small muted">Scope hash <span className="hash">{confirm.a.scope_hash}</span>. If the deposit, destination or evidence changes, this approval is invalidated automatically.</p>
          <div className="form-actions">
            <button className="btn" onClick={() => setConfirm(null)}>Cancel</button>
            <button className={`btn ${confirm.approve ? "primary" : "danger solid"}`} disabled={!!busy}
              onClick={async () => {
                const path = confirm.approve ? "approve" : "reject";
                await run(path, () => post(`/approvals/${confirm.a.id}/${path}`, { scope_hash: confirm.a.scope_hash }), confirm.approve ? "Approved. Execute when ready." : "Rejected");
                setConfirm(null);
              }}>
              {confirm.approve ? "Approve this scope" : "Reject"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function ScopeCard({ a, onDecide, busy, canDecide, ownProposal }: { a: Approval; onDecide: (approve: boolean) => void; busy: string | null; canDecide: boolean; ownProposal: boolean }) {
  return (
    <div className="card scope">
      <div className="card-head">
        <h3>{a.reason.charAt(0).toUpperCase() + a.reason.slice(1)}</h3>
        <span className="muted small">{a.id} · requested {when(a.created_at)}</span>
      </div>
      <div className="card-body grid-2">
        <div className="stack" style={{ gap: 10 }}>
          <div>
            <div className="muted small">Refund amount</div>
            <div className="amount">{money(a.scope.amount_minor, a.scope.currency)}</div>
          </div>
          <dl className="kv">
            <dt>Destination</dt><dd>{a.scope.destination}</dd>
            <dt>Deposit</dt><dd><a href={`#/payments?deposit=${a.scope.deposit_id}`}>{a.scope.deposit_id}</a> · version {a.scope.deposit_version}</dd>
            <dt>Evidence</dt><dd>{a.scope.evidence_id ? `${a.scope.evidence_id} (v${a.scope.evidence_version})` : "None: operator decision"}</dd>
            <dt>Scope hash</dt><dd className="hash">{a.scope_hash}</dd>
          </dl>
          {canDecide && (
            <div className="row">
              <button className="btn primary" disabled={!!busy || ownProposal} title={ownProposal ? "You proposed this; another team member must approve" : undefined} onClick={() => onDecide(true)}>Approve…</button>
              <button className="btn danger" disabled={!!busy} onClick={() => onDecide(false)}>Reject…</button>
            </div>
          )}
          {ownProposal && <div className="small muted">You proposed this refund, so a different team member must approve it.</div>}
          {a.created_by && a.created_by !== "system" && !ownProposal && <div className="small muted">Proposed by {a.created_by}</div>}
        </div>
        <div>
          {a.evidence ? (
            <>
              <div className="row" style={{ marginBottom: 8 }}><span className="small muted">Evidence checks</span><Pill status={a.evidence.verdict} /></div>
              <Checks checks={a.evidence.checks} />
            </>
          ) : (
            <div className="notice warn small">No verified payer evidence is attached. This return was proposed by an operator and needs a deliberate decision.</div>
          )}
        </div>
      </div>
    </div>
  );
}
