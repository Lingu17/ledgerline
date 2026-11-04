import { Fragment, useEffect, useState } from "react";
import { download, get, getPage, post, type AuditEvent } from "../api";
import { useAuth } from "../auth";
import { Pager } from "../components/Pager";
import { Card, Empty, ErrorNote, Loading, useLoad, useToast } from "../components/ui";
import { when, actionLabel } from "../format";
import { describe } from "./Inbox";

interface ChainCheck { ok: boolean; events: number; head: string; problem: string | null; broken_at?: number | null }
interface Tampered { id: number; action: string; field: string; from: number; to: number }

/** Practice companies only: change one audit event directly, as someone with database access could, and watch the
 * hash chain catch it at that event. Restore puts it back. */
function TryToTamper({ onChange }: { onChange: () => void }) {
  const [state, setState] = useState<{ changed: Tampered | null; chain: ChainCheck } | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  useEffect(() => { get<{ changed: Tampered | null; chain: ChainCheck }>("/practice/tamper").then(setState).catch(() => setState(null)); }, []);
  const act = async (path: string) => {
    setBusy(true);
    try {
      await post(path);
      setState(await get("/practice/tamper"));
      onChange();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  const t = state?.changed;
  return (
    <Card title="Try to tamper (practice only)">
      {!t ? (
        <div className="row" style={{ justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <span className="small muted">Change one recorded amount straight in the database, the way an insider could, and see whether the log notices. Only this practice company is touched.</span>
          <button className="btn" disabled={busy} onClick={() => act("/practice/tamper")}>{busy ? "Changing…" : "Change one audit row"}</button>
        </div>
      ) : (
        <div className="stack" style={{ gap: 8 }}>
          <div className={`notice small ${state!.chain.ok ? "" : "risk"}`} role="status">
            <b>{state!.chain.ok ? "Not caught." : `Caught at event ${state!.chain.broken_at}.`}</b> Event {t.id} ({t.action}) had its recorded amount changed from {t.from} to {t.to} (in cents), with nothing else touched.
            {!state!.chain.ok && <> Checking the log recomputes every event's hash; event {state!.chain.broken_at} no longer matches its own, so the change shows at exactly that row.</>}
          </div>
          <div><button className="btn primary" disabled={busy} onClick={() => act("/practice/tamper/restore")}>{busy ? "Restoring…" : "Restore the original"}</button></div>
        </div>
      )}
    </Card>
  );
}

export function Activity() {
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => { setDq(q); setOffset(0); }, 250);
    return () => clearTimeout(t);
  }, [q]);
  const page = useLoad(() => getPage<AuditEvent[]>(`/audit?limit=50&offset=${offset}${dq ? `&q=${encodeURIComponent(dq)}` : ""}`), [offset, dq]);
  const a = { ...page, data: page.data?.items ?? null };
  const [open, setOpen] = useState<number | null>(null);
  const toast = useToast();
  const rows = a.data ?? [];
  const [chain, setChain] = useState<ChainCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const { me } = useAuth();
  return (
    <div className="stack">
      {me?.organization?.kind === "sample" && <TryToTamper onChange={() => { setChain(null); page.reload(); }} />}
      <div className="toolbar">
        <div className="field" style={{ flex: "1 1 260px" }}>
          <label htmlFor="act-q">Filter</label>
          <input id="act-q" type="search" placeholder="Action, entity, actor or operation id" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <button className="btn" disabled={checking} onClick={async () => {
          setChecking(true);
          try { setChain(await get<ChainCheck>("/audit/verify")); } catch (e) { toast((e as Error).message, "error"); } finally { setChecking(false); }
        }}>{checking ? "Checking…" : "Verify log integrity"}</button>
        <button className="btn" onClick={() => download("/audit/export", "ledgerline-evidence-export.json").catch((e) => toast(e.message, "error"))}>
          Download evidence JSON
        </button>
        <button className="btn" onClick={() => download("/export/csv", "ledgerline-export.zip").catch((e) => toast(e.message, "error"))}>
          Download CSV files
        </button>
      </div>
      {chain && (
        <div className={`notice small ${chain.ok ? "" : "risk"}`} role="status">
          {chain.ok ? <><b>Log intact.</b> All {chain.events} events match their hash chain.</> : <><b>Log integrity failed.</b> {chain.problem}</>}
          <div className="mono" style={{ overflowWrap: "anywhere" }}>Head {chain.head}</div>
          <div className="muted">Rewriting the whole log would need database access; compare this head with a saved copy to rule that out.</div>
        </div>
      )}
      <Card pad={false}>
        {a.error ? <div className="card-body"><ErrorNote error={a.error} onRetry={a.reload} /></div> : !a.data ? <Loading rows={8} /> : rows.length === 0 ? (
          <Empty title={q ? "Nothing matches that filter" : "No activity yet"}>{q ? "Clear the filter to see everything." : "Every decision and money movement will be recorded here."}</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Summary</th><th className="hide-sm">Operation</th></tr></thead>
              <tbody>
                {rows.map((e) => (
                  <Fragment key={e.id}>
                    <tr className="clickable" tabIndex={0} aria-expanded={open === e.id}
                      onClick={() => setOpen(open === e.id ? null : e.id)} onKeyDown={(k) => k.key === "Enter" && setOpen(open === e.id ? null : e.id)}>
                      <td className="nowrap small muted">{when(e.at)}</td>
                      <td className="small">{e.actor}</td>
                      <td className="small" title={e.action}>{actionLabel(e.action)}<div className="mono muted" style={{ fontSize: 11 }}>{e.action}</div></td>
                      <td className="small">{describe(e)}</td>
                      <td className="mono small hide-sm">{e.operation_id ?? ""}</td>
                    </tr>
                    {open === e.id && (
                      <tr><td colSpan={5}><pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(e.detail, null, 2)}</pre></td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {page.data && <Pager offset={offset} total={page.data.total} onChange={setOffset} size={50} />}
      </Card>
    </div>
  );
}
