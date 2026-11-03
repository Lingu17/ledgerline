import { useState } from "react";
import { get, post } from "../api";
import { Card, ErrorNote, Loading, Modal, useAction, useLoad } from "../components/ui";
import { useAuth } from "../auth";

interface DemoState {
  available: boolean;
  steps: { id: string; title: string; description: string; done: boolean }[];
  next: string | null;
  blocked: string | null;
  practice_teammate_can_send?: string | null;
  provider: string;
}

export function Walkthrough() {
  const st = useLoad(() => get<DemoState>("/demo"), []);
  const { run, busy } = useAction();
  const [confirmReset, setConfirmReset] = useState(false);
  const { can } = useAuth();
  if (st.error) return <ErrorNote error={st.error} onRetry={st.reload} />;
  if (!st.data) return <div className="card"><Loading /></div>;
  const s = st.data;
  if (!s.available)
    return <div className="card"><div className="empty"><b>Practice steps run in a practice company</b>Create one from the organization menu. Your real company is never touched.</div></div>;
  return (
    <div className="stack" style={{ maxWidth: 820 }}>
      <div className="notice small">
        A guided run of the reference scenario: six synthetic deposits in USD, EUR and GBP, including a suspected duplicate that turns out to be an
        advance and a payer agent that claims another customer's invoice. Every step uses the same code paths as day-to-day work.
        Bank: {s.provider}.
      </div>
      <Card title="Steps" actions={can("owner") && <button className="btn small danger" onClick={() => setConfirmReset(true)}>Reset sample data…</button>}>
        <ol className="steps">
          {s.steps.map((step, i) => (
            <li key={step.id}>
              <span className={`n ${step.done ? "done" : ""}`} aria-hidden="true">{step.done ? "✓" : i + 1}</span>
              <div>
                <b>{step.title}</b>{step.done && <span className="sr-only"> (done)</span>}
                <div className="small muted">{step.description}</div>
                {s.next === step.id && s.blocked && (
                  <div className="small" style={{ marginTop: 4 }}>
                    {s.blocked}. <a href="#/approvals">Go to Approvals</a>
                  </div>
                )}
                {s.next === step.id && s.practice_teammate_can_send && can("operator") && (
                  <PracticeTeammateSend approvalId={s.practice_teammate_can_send} busy={busy}
                    onSend={() => run("practice-send", async () => {
                      await post(`/approvals/${s.practice_teammate_can_send}/send-as-practice-teammate`);
                      return post("/demo/step", { step: "approve" });
                    }, "The practice teammate sent the refund")} />
                )}
              </div>
              <div>
                {can("operator") && s.next === step.id && step.id !== "seed" && (
                  <button className="btn primary small" disabled={!!busy || !!s.blocked}
                    onClick={() => run("step", () => post("/demo/step", { step: step.id }),
                      step.id === "deposits" && s.provider.includes("AIRWALLEX")
                        ? "Sandbox receipts checked. Pending deposits wait for Airwallex settled webhooks."
                        : `${step.title}: done`)}>
                    {busy === "step" ? "Running…" : "Run"}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ol>
      </Card>
      {confirmReset && (
        <Modal title="Reset sample data" onClose={() => setConfirmReset(false)}>
          <p style={{ marginTop: 0 }}>This deletes all deposits, decisions, approvals, journals and audit events in this sample organization and re-seeds the synthetic customers and invoices. Policy and the pause switch are kept.</p>
          <div className="form-actions">
            <button className="btn" onClick={() => setConfirmReset(false)}>Cancel</button>
            <button className="btn danger solid" disabled={!!busy} onClick={async () => {
              await run("seed", () => post("/demo/step", { step: "seed" }), "Workspace reset");
              setConfirmReset(false);
            }}>Reset</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

/** Practice companies only: the server refuses this in a real company. */
export function PracticeTeammateSend({ approvalId, busy, onSend }: { approvalId: string; busy: string | null; onSend: () => void }) {
  return (
    <div className="notice small" style={{ marginTop: 8 }}>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <span className="pill warn">Practice only</span>
        <button className="btn small" disabled={!!busy} onClick={onSend}>
          {busy === "practice-send" ? "Sending…" : "Send as practice teammate"}
        </button>
      </div>
      <div className="muted" style={{ marginTop: 6 }}>
        A stand-in second member that exists only in practice companies, so you can finish alone. It sends {approvalId} and is recorded
        as <span className="mono">practice-teammate</span>, never as a real member. It cannot approve. A real company needs a second real member.
      </div>
    </div>
  );
}
