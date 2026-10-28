import { useState } from "react";
import { get, post } from "../api";
import { Card, ErrorNote, Loading, Modal, useAction, useLoad } from "../components/ui";
import { useAuth } from "../auth";

interface DemoState {
  available: boolean;
  steps: { id: string; title: string; description: string; done: boolean }[];
  next: string | null;
  blocked: string | null;
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
    return <div className="card"><div className="empty"><b>The walkthrough runs in sample organizations</b>Create one from the organization menu with “Sample data”. Your real workspace is never touched.</div></div>;
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
