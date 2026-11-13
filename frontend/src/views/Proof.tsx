import { useEffect, useState } from "react";
import { DocPage } from "./Legal";

interface Run { date: string; title: string; ids: string[]; result: string; proves: string }
interface Outside { placeholder?: boolean; status?: string; runs?: Record<string, unknown>[]; generated_at?: string;
  label?: string; what?: string; date?: string; validated_by?: string }
interface Evidence { commit: string; sandbox: { what: string; source: string; runs: Run[]; simulated_only: string[] }; outside_agent: Outside }

/** Public, read only: what ran on the real Airwallex sandbox, with dates and ids, read from committed files. The page
 *  calls nothing live. */
export function Proof() {
  const [e, setE] = useState<Evidence | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    document.title = "Sandbox evidence · Ledgerline";
    fetch("/api/public/evidence").then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))).then(setE).catch((x) => setErr(String(x.message ?? x)));
  }, []);
  const outside = e?.outside_agent;
  return (
    <DocPage title="Sandbox evidence" updated={null} wide>
      <p>What Ledgerline has run against the <b>real Airwallex sandbox</b> (test money only), with dates and ids. This page reads
        committed files from the repository (<code>docs/evidence</code>) and calls nothing live.</p>
      {err && <p className="neg">Could not load the evidence: {err}</p>}
      {!e && !err && <p className="muted">Loading…</p>}
      {e && (
        <>
          <div className="table-wrap">
            <table className="stack-sm">
              <thead><tr><th>Date</th><th>Run</th><th>Ids</th><th>What happened</th><th>What this proves</th></tr></thead>
              <tbody>
                {e.sandbox.runs.map((r) => (
                  <tr key={r.title + r.date}>
                    <td className="nowrap">{r.date}</td>
                    <td><b>{r.title}</b></td>
                    <td className="mono small">{r.ids.join(", ")}</td>
                    <td className="small">{r.result}</td>
                    <td className="small">{r.proves}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h2>A payer agent outside this server</h2>
          {outside?.placeholder || !outside?.runs?.length
            ? <p className="small">Not recorded yet in <code>docs/evidence/outside-agent-run.json</code>. The 3 Nov run above was on the owner's own machine;
                the steps to record one from a second machine are in <code>docs/OUTSIDE_AGENT_RUN.md</code>.</p>
            : <>
              {outside.label && <p><span className="pill info" data-testid="outside-label" style={{ whiteSpace: "normal", maxWidth: "100%", height: "auto", minHeight: 21, padding: "2px 8px", lineHeight: 1.35 }}>{outside.label}</span></p>}
              {outside.what && <p className="small">{outside.what}</p>}
              {outside.validated_by && <p className="small muted">Checked by <code>{outside.validated_by}</code> against <code>docs/evidence/outside-agent-run.json</code>:
                the signature, that the key differs from every key this server holds, ids, times and the three checks.</p>}
              <div className="table-wrap"><table className="stack-sm">
                <thead><tr><th>When</th><th>Payment</th><th>Agent host</th><th>Key</th><th>Checks</th><th>Plan</th></tr></thead>
                <tbody>{outside.runs.map((r, i) => {
                  const run = r as { at: string; deposit_id: string; endpoint_host: string; key_id: string; checks: Record<string, boolean>;
                    plan_before?: { category: string }; plan_after?: { category: string } };
                  return <tr key={i}><td className="nowrap small">{run.at}</td><td className="mono small">{run.deposit_id}</td><td className="small">{run.endpoint_host}</td>
                    <td className="mono small">{run.key_id}</td><td className="small">{Object.entries(run.checks).map(([k, v]) => `${v ? "✓" : "✗"} ${k}`).join(" · ")}</td>
                    <td className="small">{run.plan_before?.category ?? "—"} → {run.plan_after?.category ?? "—"}</td></tr>;
                })}</tbody>
              </table></div></>}
          <h2>Simulated only</h2>
          <p className="small">Tested automatically on the simulated bank, never run on the sandbox:</p>
          <ul>{e.sandbox.simulated_only.map((s) => <li key={s}>{s}</li>)}</ul>
          <p className="small muted">Source: <code>{e.sandbox.source}</code> · commit {e.commit}</p>
        </>
      )}
    </DocPage>
  );
}
