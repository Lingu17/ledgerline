import { useEffect, useState } from "react";
import { DocPage } from "./Legal";

interface Moved { transfers: number; amount_minor: number; conversions: number }
interface Attack { id: string; category: string; tried: string; rule: string; result: string; moved: Moved | null }
interface Report { missing?: boolean; what: string; how: string; generated_at: string; commit: string; total: number; blocked: number;
  moved_minor_total: number | null; attacks: Attack[] }

/** Public, read only: the latest run of the hostile-attempt suite on the simulated bank, read from the committed report.
 *  Nothing is run against a bank from this page. */
export function Attacks() {
  const [r, setR] = useState<Report | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    document.title = "Attacks · Ledgerline";
    fetch("/api/public/attacks").then((x) => (x.ok ? x.json() : Promise.reject(new Error(`HTTP ${x.status}`)))).then(setR).catch((x) => setErr(String(x.message ?? x)));
  }, []);
  const allBlocked = r && !r.missing && r.blocked === r.total && r.moved_minor_total === 0;
  return (
    <DocPage title="Attacks" updated={null} wide>
      <p>Hostile attempts against Ledgerline on the <b>simulated bank</b> (no real money): forged and replayed agent answers,
        instructions hidden in emails, approvals reused or self-approved, double sends. Each one must be refused and move nothing.
        Money is measured on the simulated bank's own records before and after each attempt.</p>
      {err && <p className="neg">Could not load the report: {err}</p>}
      {!r && !err && <p className="muted">Loading…</p>}
      {r?.missing && <p>No report has been committed yet.</p>}
      {r && !r.missing && (
        <>
          <p className="attack-score" data-testid="attack-score">
            <span className={allBlocked ? "pill ok" : "pill risk"} style={{ fontSize: "1.25rem", padding: "6px 14px" }}>
              {r.blocked}/{r.total} blocked · {r.moved_minor_total === 0 ? "$0 moved" : `${r.moved_minor_total ?? "unknown"} minor units moved`}
            </span>
          </p>
          <p className="small muted">Last run {r.generated_at} on commit {r.commit}. The suite also runs in CI on every push
            (<code>backend/tests/test_attacks.py</code>); this page shows the committed report from <code>scripts/attack_report.py</code>.</p>
          <div className="table-wrap">
            <table className="stack-sm">
              <thead><tr><th>Area</th><th>What was tried</th><th>What stopped it</th><th>Result</th></tr></thead>
              <tbody>
                {r.attacks.map((a) => (
                  <tr key={a.id}>
                    <td className="nowrap small">{a.category}</td>
                    <td className="small">{a.tried}</td>
                    <td className="small">{a.rule}</td>
                    <td className="nowrap small">
                      <span className={a.result === "blocked" ? "pill ok" : "pill risk"}>{a.result === "blocked" ? "Blocked" : "Not blocked"}</span>
                      {a.moved && <div className="muted">{a.moved.transfers} transfers · {a.moved.amount_minor} moved</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">Simulated bank only. The real-sandbox runs are on the <a href="/evidence">evidence page</a>.</p>
        </>
      )}
    </DocPage>
  );
}
