import { Fragment, useEffect, useState } from "react";
import { download, get, getPage, type AuditEvent } from "../api";
import { Pager } from "../components/Pager";
import { Card, Empty, ErrorNote, Loading, useLoad, useToast } from "../components/ui";
import { when } from "../format";
import { describe } from "./Inbox";

interface ChainCheck { ok: boolean; events: number; head: string; problem: string | null }

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
  return (
    <div className="stack">
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
          <Empty title={q ? "Nothing matches that filter" : "No activity yet"} />
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
                      <td className="mono small">{e.action}</td>
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
