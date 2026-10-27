import { useEffect, useMemo, useState } from "react";
import { get, getPage, post, type Approval, type AuditEvent, type Customer, type Deposit, type Evidence, type Invoice, type Operation, type Plan } from "../api";
import { Card, Checks, Drawer, Empty, ErrorNote, Field, Loading, Modal, Money, Pill, useAction, useLoad } from "../components/ui";
import { CATEGORY_LABEL, SOURCE_LABEL, STATUS_LABEL, money, parseMajor, majorString, when, day } from "../format";
import { go, type Route } from "../App";
import { describe } from "./Inbox";
import { useAuth } from "../auth";
import { PAGE_SIZE, Pager } from "../components/Pager";

const STATUSES = ["", "escalated", "awaiting_evidence", "refund_awaiting_approval", "refund_in_flight", "partially_applied", "matched", "credited", "refunded"];

export function Payments({ route }: { route: Route }) {
  const [status, setStatus] = useState(route.params.get("status") ?? "");
  const [currency, setCurrency] = useState("");
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [recording, setRecording] = useState(false);
  const [importing, setImporting] = useState(false);
  const [offset, setOffset] = useState(0);
  const { can } = useAuth();
  const op = can("operator");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 200);
    return () => clearTimeout(t);
  }, [q]);
  const filters = new URLSearchParams({ ...(status && { status }), ...(currency && { currency }), ...(debounced && { q: debounced }) }).toString();
  useEffect(() => setOffset(0), [filters]);
  const qs = `${filters}${filters ? "&" : ""}limit=${PAGE_SIZE}&offset=${offset}`;
  const page = useLoad(() => getPage<Deposit[]>(`/deposits?${qs}`), [qs]);
  const list = { ...page, data: page.data?.items ?? null };
  const selected = route.params.get("deposit");

  return (
    <div className="stack">
      <div className="toolbar">
        <div className="field" style={{ flex: "1 1 240px" }}>
          <label htmlFor="pay-search">Search</label>
          <input id="pay-search" type="search" placeholder="Payer, reference or deposit id" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="pay-status">Status</label>
          <select id="pay-status" value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => <option key={s} value={s}>{s ? STATUS_LABEL[s] : "All statuses"}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="pay-ccy">Currency</label>
          <select id="pay-ccy" value={currency} onChange={(e) => setCurrency(e.target.value)}>
            <option value="">All</option><option>USD</option><option>EUR</option><option>GBP</option>
          </select>
        </div>
        {op && <button className="btn" onClick={() => setImporting(true)}>Import CSV</button>}
        {op && <button className="btn primary" onClick={() => setRecording(true)}>Record payment</button>}
      </div>

      <Card pad={false}>
        {list.error ? <div className="card-body"><ErrorNote error={list.error} onRetry={list.reload} /></div> : !list.data ? <Loading rows={6} /> : list.data.length === 0 ? (
          <Empty title={filters ? "No payments match these filters" : "No payments received yet"}>
            {filters ? "Clear the search or status filter." : op ? "Record a payment from a bank statement, import a CSV, or connect the webhook in Settings." : "Nothing has been received yet."}
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Received</th><th>Payer</th><th className="hide-sm">Reference</th><th className="num">Amount</th>
                  <th>Status</th><th className="hide-sm">Decision</th><th className="num hide-sm">Unapplied</th>
                </tr>
              </thead>
              <tbody>
                {list.data.map((d) => (
                  <tr key={d.id} className={`clickable ${selected === d.id ? "selected" : ""}`} tabIndex={0}
                    onClick={() => go("payments", { deposit: d.id })}
                    onKeyDown={(e) => e.key === "Enter" && go("payments", { deposit: d.id })}>
                    <td className="nowrap"><div>{day(d.received_at)}</div><div className="secondary mono">{d.id}</div></td>
                    <td><div className="primary-text">{d.payer_name}</div><div className="secondary">{d.customer_name ?? "Unidentified"} · {SOURCE_LABEL[d.source] ?? d.source}</div></td>
                    <td className="hide-sm mono small">{d.reference || <span className="muted">none</span>}</td>
                    <td className="num"><Money minor={d.amount_minor} ccy={d.currency} /></td>
                    <td><Pill status={d.status} /></td>
                    <td className="hide-sm small">{CATEGORY_LABEL[d.category ?? ""] ?? d.category}{d.plan_count > 1 && <span className="muted"> · revised</span>}</td>
                    <td className="num hide-sm">{d.buckets.unapplied ? <Money minor={d.buckets.unapplied} ccy={d.currency} /> : <span className="muted">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {page.data && <Pager offset={offset} total={page.data.total} onChange={setOffset} />}
      </Card>

      {selected && <DepositDrawer id={selected} onClose={() => go("payments", status ? { status } : undefined)} />}
      {recording && <RecordPayment onClose={() => setRecording(false)} />}
      {importing && <ImportCsv onClose={() => setImporting(false)} />}
    </div>
  );
}

interface DepositDetail extends Deposit {
  plans: Plan[];
  evidence: Evidence[];
  allocations: { invoice_id: string; amount_minor: number; created_at: string }[];
  writeoffs: { invoice_id: string; amount_minor: number; reason: string }[];
  credits: { customer_id: string; amount_minor: number; earmark_invoice_id: string | null }[];
  payment_links: { id: string; invoice_id: string; amount_minor: number; status: string; note: string; url: string | null }[];
  approvals: Approval[];
  operations: Operation[];
  audit: AuditEvent[];
  has_remittance_doc: boolean;
}

function DepositDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const d = useLoad(() => get<DepositDetail>(`/deposits/${id}`), [id]);
  const { run, busy } = useAction();
  const x = d.data;
  return (
    <Drawer
      title={x ? `${x.payer_name} · ${money(x.amount_minor, x.currency)}` : id}
      subtitle={x ? `${x.id} · received ${when(x.received_at)} · ${SOURCE_LABEL[x.source] ?? x.source}` : undefined}
      onClose={onClose}
    >
      {d.error && <ErrorNote error={d.error} onRetry={d.reload} />}
      {!x ? <Loading rows={8} /> : (
        <>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="row"><Pill status={x.status} /><span className="small">{CATEGORY_LABEL[x.category ?? ""] ?? x.category}</span></div>
            <span className="muted small">Reference: <span className="mono">{x.reference || "none"}</span></span>
          </div>
          {x.source === "manual_import" && <div className="notice warn">Manually recorded by an operator. Not verified against a bank statement feed.</div>}
          {x.escalation_reason && x.status === "escalated" && <div className="notice risk"><b>Why this needs review:</b> {x.escalation_reason}</div>}

          <div className="buckets" aria-label="Where this deposit went">
            <div><span>Applied to invoices</span><b>{money(x.buckets.allocated, x.currency)}</b></div>
            <div><span>Customer credit</span><b>{money(x.buckets.credited, x.currency)}</b></div>
            <div><span>Refund pending</span><b>{money(x.buckets.refund_pending, x.currency)}</b></div>
            <div><span>Refunded</span><b>{money(x.buckets.refund_paid, x.currency)}</b></div>
            <div><span>Unapplied</span><b className={x.buckets.unapplied ? "" : "muted"}>{money(x.buckets.unapplied, x.currency)}</b></div>
          </div>

          <DepositActions x={x} run={run} busy={busy} />

          <section>
            <h3 className="section-title">Decision history</h3>
            <ol className="timeline">
              {x.plans.map((p) => {
                const ev = x.evidence.find((e) => e.id === p.evidence_id);
                return (
                  <li key={p.id}>
                    <span className={`dot ${p.kind === "initial" ? "" : ev?.verdict === "rejected" ? "risk" : "ok"}`} />
                    <PlanCard plan={p} ccy={x.currency} />
                  </li>
                );
              })}
            </ol>
          </section>

          {x.evidence.length > 0 && (
            <section className="stack">
              <h3 className="section-title" style={{ margin: 0 }}>Evidence</h3>
              {x.evidence.map((e) => <EvidenceBlock key={e.id} e={e} />)}
            </section>
          )}

          {(x.allocations.length > 0 || x.writeoffs.length > 0 || x.credits.length > 0 || x.payment_links.length > 0) && (
            <Card title="Postings" pad={false}>
              <table>
                <tbody>
                  {x.allocations.map((a) => <tr key={"a" + a.invoice_id}><td>Applied to {a.invoice_id}</td><td className="num"><Money minor={a.amount_minor} ccy={x.currency} /></td></tr>)}
                  {x.writeoffs.map((w) => <tr key={"w" + w.invoice_id}><td>Bank fee written off on {w.invoice_id} <span className="muted small">(invoice adjustment, not deposit cash)</span></td><td className="num"><Money minor={w.amount_minor} ccy={x.currency} /></td></tr>)}
                  {x.credits.map((c, i) => <tr key={"c" + i}><td>Credit for {c.customer_id}{c.earmark_invoice_id ? ` toward ${c.earmark_invoice_id}` : ""}</td><td className="num"><Money minor={c.amount_minor} ccy={x.currency} /></td></tr>)}
                  {x.payment_links.map((l) => (
                    <tr key={l.id}><td>Balance request for {l.invoice_id} <Pill status={l.status === "sandbox_created" ? "matched" : "pending"} label={l.status === "sandbox_created" ? "Link created" : "Draft, not sent"} /><div className="secondary">{l.note}</div></td><td className="num"><Money minor={l.amount_minor} ccy={x.currency} /></td></tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}

          {(x.approvals.length > 0 || x.operations.length > 0) && (
            <Card title="Refund" actions={<a className="btn small" href="#/approvals">Open approvals</a>}>
              {x.approvals.map((a) => (
                <div key={a.id} className="row small" style={{ justifyContent: "space-between" }}>
                  <span className="mono">{a.id}</span><span>{money(a.scope.amount_minor, a.scope.currency)} to {a.scope.destination}</span><Pill status={a.status} />
                </div>
              ))}
              {x.operations.map((o) => (
                <div key={o.id} className="row small" style={{ justifyContent: "space-between", marginTop: 6 }}>
                  <span className="mono">{o.id}</span><span className="mono muted">request {o.request_id.slice(0, 8)}…</span><Pill status={o.status} />
                </div>
              ))}
            </Card>
          )}

          <section>
            <h3 className="section-title">Audit</h3>
            <table>
              <tbody>
                {x.audit.map((a) => (
                  <tr key={a.id}><td className="nowrap small muted">{when(a.at)}</td><td className="mono small">{a.action}</td><td className="small">{describe(a)}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </Drawer>
  );
}

const ACTION_TEXT: Record<string, (a: any, ccy: string) => string> = {
  allocate: (a, c) => `Apply ${money(a.amount_minor, c)} to ${a.invoice_id}`,
  write_off_fee: (a, c) => `Write off ${money(a.amount_minor, c)} bank fee on ${a.invoice_id}`,
  payment_link: (a, c) => `Request the ${money(a.amount_minor, c)} balance on ${a.invoice_id}`,
  ask_payer_agent: (a) => `Ask ${a.customer_id}'s agent: ${a.question}`,
  hold_unapplied: (a, c) => `Hold ${money(a.amount_minor, c)} unapplied`,
  propose_refund: (a, c) => `Proposed refund of ${money(a.amount_minor, c)} (held until evidence)`,
  cancel_proposed_refund: () => "Drop the proposed refund before any money moves",
  credit: (a, c) => `Hold ${money(a.amount_minor, c)} as credit${a.earmark_invoice_id ? ` toward ${a.earmark_invoice_id}` : ""}`,
  request_refund_approval: (a, c) => `Request approval to refund ${money(a.amount_minor, c)}`,
  escalate: (a) => `Escalate: ${a.reason}`,
};

export function PlanCard({ plan, ccy }: { plan: Plan; ccy: string }) {
  return (
    <div className="plan-card">
      <h4>
        <span>{plan.kind === "initial" ? "Initial plan" : plan.kind === "revised" ? "Revised plan" : "Operator decision"} · v{plan.version}</span>
        <span className="pill plain muted">{CATEGORY_LABEL[plan.category] ?? plan.category}</span>
        <span className="muted small" style={{ fontWeight: 400 }}>{when(plan.created_at)}</span>
      </h4>
      <div className="small">{plan.summary}</div>
      <ul>{plan.actions.map((a, i) => <li key={i}>{(ACTION_TEXT[a.type] ?? (() => a.type))(a, ccy)}</li>)}</ul>
    </div>
  );
}

export function EvidenceBlock({ e }: { e: Evidence }) {
  const claim = e.envelope?.claim;
  const proposal = e.envelope?.proposal;
  return (
    <div className="card">
      <div className="card-head">
        <h3 className="row" style={{ gap: 8 }}>
          {e.source === "mcp_signed" ? "Signed payer answer" : e.source === "claude_extracted" ? "Remittance read by Claude" : "Remittance read by offline rules"}
          <Pill status={e.verdict} label={e.verdict === "advisory" ? "Advisory only" : e.verdict === "verified" ? "Verified" : "Rejected"} />
        </h3>
        <span className="muted small mono">{e.id} · {e.transport}</span>
      </div>
      <div className="card-body stack" style={{ gap: 10 }}>
        {claim && (
          <dl className="kv">
            <dt>Claims</dt><dd>{claim.reason?.replace(/_/g, " ")} for <b>{claim.invoice_id}</b></dd>
            <dt>Speaking for</dt><dd>{claim.customer_id}</dd>
            <dt>Bound to</dt><dd className="mono">{claim.deposit_id} · {money(claim.amount_minor, claim.currency)}</dd>
            <dt>Valid</dt><dd>{when(claim.issued_at)} → {when(claim.expires_at)}</dd>
            <dt>Note</dt><dd>{claim.note}</dd>
            <dt>Key</dt><dd className="mono">{e.envelope.key_id}</dd>
          </dl>
        )}
        {proposal && (
          <>
            <dl className="kv">
              <dt>Mode</dt><dd>{e.envelope.mode}</dd>
              <dt>Proposes</dt><dd className="mono">{proposal.tool} {JSON.stringify(proposal.input)}</dd>
            </dl>
            <details><summary className="small">Source text</summary><pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{e.envelope.document}</pre></details>
          </>
        )}
        <Checks checks={e.checks} />
        {e.verdict === "rejected" && <div className="notice risk small">{e.reason}</div>}
        {e.verdict === "advisory" && <div className="notice small">Unsigned extraction. It informs a person; it cannot move money or change allocations by itself.</div>}
      </div>
    </div>
  );
}

function DepositActions({ x, run, busy }: { x: DepositDetail; run: ReturnType<typeof useAction>["run"]; busy: string | null }) {
  const [panel, setPanel] = useState<"" | "resolve" | "read">("");
  const { can } = useAuth();
  if (!can("operator")) return null;
  if (x.status === "awaiting_evidence") {
    return (
      <div className="notice warn row" style={{ justifyContent: "space-between" }}>
        <span>Waiting on the payer's explanation. Ledgerline asks their agent over MCP and verifies the signed answer.</span>
        <button className="btn primary" disabled={!!busy} onClick={() => run("ask", () => post(`/deposits/${x.id}/ask-agent`), (r: any) => `Payer answer ${r.verification.verdict}`)}>
          {busy === "ask" ? "Asking…" : "Ask payer's agent"}
        </button>
      </div>
    );
  }
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row">
        {x.status === "escalated" && (
          <>
            <button className="btn primary" aria-expanded={panel === "resolve"} onClick={() => setPanel(panel === "resolve" ? "" : "resolve")}>Resolve…</button>
            <button className="btn danger" disabled={!!busy || !x.customer_id}
              title={x.customer_id ? "Creates a refund approval; nothing is sent until a person approves" : "Identify the payer first"}
              onClick={() => run("rts", () => post(`/deposits/${x.id}/return-to-sender`), "Return proposed; it is waiting on the Approvals page")}>
              Propose return to sender
            </button>
          </>
        )}
        <button className="btn" aria-expanded={panel === "read"} onClick={() => setPanel(panel === "read" ? "" : "read")}>Read remittance…</button>
      </div>
      {panel === "resolve" && <ResolveForm x={x} onDone={() => setPanel("")} />}
      {panel === "read" && <ReadRemittance x={x} onDone={() => setPanel("")} />}
    </div>
  );
}

function ResolveForm({ x, onDone }: { x: DepositDetail; onDone: () => void }) {
  const invoices = useLoad(() => get<Invoice[]>("/invoices"), []);
  const customers = useLoad(() => get<Customer[]>("/customers"), []);
  const { run, busy } = useAction();
  const [action, setAction] = useState<"allocate" | "credit">("allocate");
  const [customer, setCustomer] = useState(x.customer_id ?? "");
  const [invoice, setInvoice] = useState("");
  const [amount, setAmount] = useState(majorString(x.buckets.unapplied));
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const eligible = useMemo(
    () => (invoices.data ?? []).filter((i) => i.customer_id === customer && i.currency === x.currency && i.status === "open" && i.remaining_minor > 0),
    [invoices.data, customer, x.currency],
  );
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const minor = parseMajor(amount);
    if (minor === null || minor <= 0) return setErr("Enter an amount like 1250.00");
    if (minor > x.buckets.unapplied) return setErr(`At most ${money(x.buckets.unapplied, x.currency)} is unapplied`);
    if (action === "allocate" && !invoice) return setErr("Choose one of the payer's open invoices");
    if (note.trim().length < 3) return setErr("Add a short note for the audit trail");
    setErr(null);
    const r = await run("resolve", () => post(`/deposits/${x.id}/resolve`, { action, amount, invoice_id: invoice || undefined, customer_id: customer || undefined, note }), "Decision recorded");
    if (r) onDone();
  };
  return (
    <form className="card card-body" onSubmit={submit} noValidate>
      <div className="row" style={{ marginBottom: 12 }}>
        <div className="segmented" role="group" aria-label="Resolution">
          <button type="button" aria-pressed={action === "allocate"} onClick={() => setAction("allocate")}>Apply to invoice</button>
          <button type="button" aria-pressed={action === "credit"} onClick={() => setAction("credit")}>Hold as credit</button>
        </div>
      </div>
      <div className="form-grid">
        <Field id="rs-cust" label="Paying customer" hint={x.customer_id ? "Identified from the remitter name; cannot be changed" : "The remitter is unknown: identify who paid"}>
          <select id="rs-cust" value={customer} disabled={!!x.customer_id} onChange={(e) => setCustomer(e.target.value)}>
            <option value="">Select…</option>
            {customers.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        {action === "allocate" && (
          <Field id="rs-inv" label="Invoice" hint={customer && eligible.length === 0 ? `No open ${x.currency} invoices for this customer` : "Only this customer's open invoices in the same currency"}>
            <select id="rs-inv" value={invoice} onChange={(e) => setInvoice(e.target.value)}>
              <option value="">Select…</option>
              {eligible.map((i) => <option key={i.id} value={i.id}>{i.id} · {money(i.remaining_minor, i.currency)} due</option>)}
            </select>
          </Field>
        )}
        <Field id="rs-amt" label={`Amount (${x.currency})`} hint={`Unapplied: ${money(x.buckets.unapplied, x.currency)}`}>
          <input id="rs-amt" type="text" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </Field>
        <Field id="rs-note" label="Note" wide hint="Recorded in the audit trail">
          <input id="rs-note" type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Confirmed by phone with their AP lead" />
        </Field>
      </div>
      {err && <div className="notice risk small" role="alert" style={{ marginTop: 10 }}>{err}</div>}
      <div className="form-actions">
        <button type="button" className="btn" onClick={onDone}>Cancel</button>
        <button className="btn primary" disabled={!!busy}>{busy ? "Saving…" : "Record decision"}</button>
      </div>
    </form>
  );
}

function ReadRemittance({ x, onDone }: { x: DepositDetail; onDone: () => void }) {
  const { run, busy } = useAction();
  const [text, setText] = useState("");
  const submit = async (useDoc: boolean) => {
    const r = await run("read", () => post(`/deposits/${x.id}/read-remittance`, useDoc ? {} : { text }), (res: any) => `Proposal: ${res.proposal.tool.replace(/_/g, " ")}`);
    if (r) onDone();
  };
  return (
    <div className="card card-body">
      <Field id="rm-text" label="Remittance email or advice text" hint="Read as data. The result is advisory and is checked against our records.">
        <textarea id="rm-text" rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the customer's remittance email…" />
      </Field>
      <div className="form-actions">
        {x.has_remittance_doc && <button className="btn" disabled={!!busy} onClick={() => submit(true)}>Use document on file</button>}
        <button className="btn primary" disabled={!!busy || text.trim().length < 10} onClick={() => submit(false)}>{busy ? "Reading…" : "Read text"}</button>
      </div>
    </div>
  );
}

function RecordPayment({ onClose }: { onClose: () => void }) {
  const { run, busy } = useAction();
  const [f, setF] = useState({ external_ref: "", currency: "USD", amount: "", payer_name: "", reference: "", received_at: new Date().toISOString().slice(0, 10) });
  const [err, setErr] = useState<Record<string, string>>({});
  const [serverErr, setServerErr] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const v: Record<string, string> = {};
    if (!/^[A-Za-z0-9._:-]{1,64}$/.test(f.external_ref)) v.external_ref = "Letters, digits and . _ : - only (max 64)";
    const minor = parseMajor(f.amount);
    if (minor === null || minor <= 0) v.amount = "Enter an amount like 1250.00";
    if (f.payer_name.trim().length < 2) v.payer_name = "As shown on the statement";
    setErr(v);
    if (Object.keys(v).length) return;
    setServerErr(null);
    try {
      const r = await post<{ deposit_id: string; created: boolean }>("/payments", f);
      await run("noop", async () => r, r.created ? `Recorded ${r.deposit_id}` : `Already recorded as ${r.deposit_id}`);
      onClose();
      go("payments", { deposit: r.deposit_id });
    } catch (ex) {
      setServerErr((ex as Error).message);
    }
  };
  return (
    <Modal title="Record a received payment" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <p className="muted small" style={{ marginTop: 0 }}>
          For payments seen on a statement but not delivered by webhook. It is labelled as manually recorded and runs through the same matching rules.
          The statement reference makes it idempotent.
        </p>
        <div className="form-grid">
          <Field id="rp-ref" label="Statement reference" error={err.external_ref} hint="Unique per bank line">
            <input id="rp-ref" type="text" value={f.external_ref} onChange={set("external_ref")} aria-invalid={!!err.external_ref} />
          </Field>
          <Field id="rp-date" label="Received on">
            <input id="rp-date" type="date" value={f.received_at} onChange={set("received_at")} />
          </Field>
          <Field id="rp-ccy" label="Currency">
            <select id="rp-ccy" value={f.currency} onChange={set("currency")}><option>USD</option><option>EUR</option><option>GBP</option></select>
          </Field>
          <Field id="rp-amt" label="Amount" error={err.amount}>
            <input id="rp-amt" type="text" inputMode="decimal" placeholder="0.00" value={f.amount} onChange={set("amount")} aria-invalid={!!err.amount} />
          </Field>
          <Field id="rp-payer" label="Remitter name" wide error={err.payer_name} hint="Must match a customer's registered payer name to be matched automatically">
            <input id="rp-payer" type="text" value={f.payer_name} onChange={set("payer_name")} aria-invalid={!!err.payer_name} />
          </Field>
          <Field id="rp-memo" label="Payment reference" wide hint="e.g. INV-2240">
            <input id="rp-memo" type="text" value={f.reference} onChange={set("reference")} />
          </Field>
        </div>
        {serverErr && <div className="notice risk small" role="alert" style={{ marginTop: 12 }}>{serverErr}</div>}
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!!busy}>Record payment</button>
        </div>
      </form>
    </Modal>
  );
}

const CSV_SAMPLE = "external_ref,received_at,currency,amount,payer_name,reference\nHSBC-2026-1102,2026-10-26,GBP,1250.00,ORCHARD TEA CO,INV-2301";

function ImportCsv({ onClose }: { onClose: () => void }) {
  const { run, busy } = useAction();
  const [text, setText] = useState("");
  const [result, setResult] = useState<{ rows: number; created: number; duplicates: number; errors: number; results: { line: number; external_ref: string; status: string; error?: string; deposit_id?: string }[] } | null>(null);
  return (
    <Modal title="Import statement lines" onClose={onClose}>
      {result ? (
        <div className="stack" style={{ gap: 10 }}>
          <div className="small">{result.created} recorded · {result.duplicates} already recorded · {result.errors} with errors</div>
          <div className="table-wrap" style={{ maxHeight: 260, overflowY: "auto" }}>
            <table>
              <thead><tr><th>Line</th><th>Reference</th><th>Result</th></tr></thead>
              <tbody>{result.results.map((r) => (
                <tr key={r.line}><td>{r.line}</td><td className="mono small">{r.external_ref}</td>
                  <td className="small">{r.status === "error" ? <span className="neg">{r.error}</span> : <>{r.status === "created" ? "Recorded" : "Duplicate, skipped"} <span className="mono">{r.deposit_id}</span></>}</td></tr>
              ))}</tbody>
            </table>
          </div>
          <div className="form-actions"><button className="btn primary" onClick={onClose}>Done</button></div>
        </div>
      ) : (
        <form onSubmit={async (e) => {
          e.preventDefault();
          const r = await run("csv", () => post<NonNullable<typeof result>>("/payments/import", { csv: text }));
          if (r) setResult(r);
        }}>
          <p className="small muted" style={{ marginTop: 0 }}>Paste CSV with the header below. Each line is matched like any received payment, labelled as manually recorded, and skipped if its reference was already recorded.</p>
          <Field id="csv-text" label="CSV" hint="external_ref, received_at (YYYY-MM-DD), currency, amount, payer_name, reference">
            <textarea id="csv-text" rows={8} className="mono" value={text} placeholder={CSV_SAMPLE} onChange={(e) => setText(e.target.value)} />
          </Field>
          <div className="form-actions"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!!busy || !text.trim()}>Import</button></div>
        </form>
      )}
    </Modal>
  );
}
