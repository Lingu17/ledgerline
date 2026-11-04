import { useEffect, useState } from "react";
import { get, getPage, post, type AuditEvent, type Customer, type Invoice } from "../api";
import { useAuth } from "../auth";
import { Card, CsvImport, Drawer, Empty, ErrorNote, Field, Loading, Modal, Money, Pill, useAction, useLoad } from "../components/ui";
import { PAGE_SIZE, Pager } from "../components/Pager";
import { day, money, parseMajor, plainAmount, when, actionLabel } from "../format";
import { go, type Route } from "../App";

function useDebounced(v: string, ms = 200) {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

export function Customers({ route }: { route: Route }) {
  const { can } = useAuth();
  const op = can("operator");
  const [cq, setCq] = useState("");
  const cqd = useDebounced(cq);
  const customers = useLoad(() => get<Customer[]>(`/customers${cqd ? `?q=${encodeURIComponent(cqd)}` : ""}`), [cqd]);
  const allCustomers = useLoad(() => get<Customer[]>("/customers"), []);
  const [iq, setIq] = useState("");
  const iqd = useDebounced(iq);
  const [filter, setFilter] = useState("outstanding");
  const [offset, setOffset] = useState(0);
  useEffect(() => setOffset(0), [iqd, filter]);
  const qs = new URLSearchParams({ ...(filter && { status: filter }), ...(iqd && { q: iqd }), limit: String(PAGE_SIZE), offset: String(offset) });
  const invoices = useLoad(() => getPage<Invoice[]>(`/invoices?${qs}`), [qs.toString()]);
  const [modal, setModal] = useState<"" | "customer" | "invoice" | "import-customers" | "import-invoices">("");
  const [editing, setEditing] = useState<Customer | null>(null);
  const [agentFor, setAgentFor] = useState<Customer | null>(null);
  const invoiceId = route.params.get("invoice");

  return (
    <div className="stack">
      <Card title="Customers" pad={false} actions={<>
        <input type="search" aria-label="Search customers" placeholder="Search customers" value={cq} onChange={(e) => setCq(e.target.value)} />
        {op && <button className="btn small" onClick={() => setModal("import-customers")}>Import CSV</button>}
        {op && <button className="btn primary small" onClick={() => setModal("customer")}>New customer</button>}
      </>}>
        {customers.error ? <div className="card-body"><ErrorNote error={customers.error} onRetry={customers.reload} /></div> : !customers.data ? <Loading /> : customers.data.length === 0 ? (
          <Empty title={cq ? "No customers match" : "No customers yet"}>{!cq && op && "Add the companies that pay you, with the remitter names that appear on your bank statements."}</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Customer</th><th className="hide-sm">Remitter names</th><th>Payer agent</th><th className="num">Credit held</th><th /></tr></thead>
              <tbody>
                {customers.data.map((c) => (
                  <tr key={c.id}>
                    <td style={{ minWidth: 150 }}><div className="primary-text">{c.name}</div><div className="secondary mono nowrap">{c.id} · {c.country}</div></td>
                    <td className="hide-sm small">{c.payer_names.join(", ")}</td>
                    <td className="small">
                      {c.agent_url ? <Pill status="info" label="Own agent" /> : c.agent_key_id ? <Pill status="muted" label={c.demo_only ? "Simulated agent" : "Key registered"} /> : <span className="muted">None</span>}
                      {c.agent_url && <div className="secondary mono hide-sm" title={c.agent_url}>{new URL(c.agent_url).host}</div>}
                      {c.agent_key_id && <div className="secondary mono hide-sm" title={c.agent_key_id}>{c.agent_key_id}</div>}
                      {c.agent_key_set_by && <div className="secondary">Key set by {c.agent_key_set_by} · {day(c.agent_key_set_at)}</div>}
                    </td>
                    <td className="num">{c.credits.length ? c.credits.map((cr, i) => <div key={i}><Money minor={cr.amount_minor} ccy={cr.currency} /></div>) : <span className="muted">—</span>}</td>
                    <td className="num"><div className="row" style={{ justifyContent: "flex-end", gap: 6 }}>
                      {can("owner") && <button className="btn small" onClick={() => setAgentFor(c)}>Payer agent…</button>}
                      {op && <button className="btn small" onClick={() => setEditing(c)}>Edit</button>}
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Invoices" pad={false} actions={<>
        <input type="search" aria-label="Search invoices" placeholder="Invoice, customer or description" value={iq} onChange={(e) => setIq(e.target.value)} />
        <select aria-label="Invoice status" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="outstanding">Outstanding</option><option value="paid">Paid</option><option value="scheduled">Scheduled</option><option value="void">Void</option><option value="">All</option>
        </select>
        {op && <button className="btn small" onClick={() => setModal("import-invoices")}>Import CSV</button>}
        {op && <button className="btn primary small" onClick={() => setModal("invoice")}>New invoice</button>}
      </>}>
        {invoices.error ? <div className="card-body"><ErrorNote error={invoices.error} onRetry={invoices.reload} /></div> : !invoices.data ? <Loading /> : invoices.data.items.length === 0 ? <Empty title="No invoices in this view" /> : (
          <>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Invoice</th><th>Customer</th><th>Due</th><th className="num">Amount</th><th className="num">Outstanding</th><th className="hide-sm">Status</th></tr></thead>
                <tbody>
                  {invoices.data.items.map((i) => (
                    <tr key={i.id} className="clickable" tabIndex={0} onClick={() => go("customers", { invoice: i.id })} onKeyDown={(e) => e.key === "Enter" && go("customers", { invoice: i.id })}>
                      <td style={{ minWidth: 140 }}><div className="mono nowrap">{i.id}</div><div className="secondary">{i.description}</div></td>
                      <td className="small" style={{ minWidth: 110 }}>{i.customer_name}</td>
                      <td className="nowrap small">{day(i.due_at)}</td>
                      <td className="num"><Money minor={i.effective_amount_minor} ccy={i.currency} />{i.adjustments.length > 0 && <div className="secondary">adjusted</div>}</td>
                      <td className="num"><b>{money(i.remaining_minor, i.currency)}</b></td>
                      <td className="hide-sm small"><InvoiceStatus i={i} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager offset={offset} total={invoices.data.total} onChange={setOffset} />
          </>
        )}
      </Card>
      {modal === "import-customers" && <CsvImport title="Import customers" path="/customers/import" columns="name,country,payer_names,refund_beneficiary"
        example="Orchard Tea Co,GB,ORCHARD TEA CO|ORCHARD TEA LTD,Orchard Tea GBP account" onClose={() => { setModal(""); allCustomers.reload(); }} />}
      {modal === "import-invoices" && <CsvImport title="Import invoices" path="/invoices/import" columns="customer,currency,amount,due_date,description"
        example="Orchard Tea Co,GBP,1250.00,2026-11-30,October supply" onClose={() => setModal("")} />}
      {modal === "customer" && <CustomerForm onClose={() => setModal("")} />}
      {editing && <CustomerForm existing={editing} onClose={() => setEditing(null)} />}
      {agentFor && <PayerAgentForm customer={agentFor} onClose={() => setAgentFor(null)} />}
      {modal === "invoice" && <NewInvoice customers={allCustomers.data ?? []} onClose={() => setModal("")} />}
      {invoiceId && <InvoiceDrawer id={invoiceId} onClose={() => go("customers")} />}
    </div>
  );
}

function InvoiceStatus({ i }: { i: { effective_status: string; remaining_minor: number; prior_paid_minor: number } }) {
  if (i.effective_status === "void") return <Pill status="muted" label="Void" />;
  if (i.effective_status === "scheduled") return <Pill status="info" label="Not yet issued" />;
  if (i.remaining_minor === 0) return <Pill status="matched" label={i.prior_paid_minor ? "Paid (prior period)" : "Paid"} />;
  return <Pill status="pending" label="Outstanding" />;
}

interface InvoiceDetail extends Invoice {
  allocations: { deposit_id: string; amount_minor: number; payer_name: string; received_at: string }[];
  writeoffs: { amount_minor: number; reason: string; deposit_id: string }[];
  audit: AuditEvent[];
}

function InvoiceDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const inv = useLoad(() => get<InvoiceDetail>(`/invoices/${id}`), [id]);
  const { can } = useAuth();
  const op = can("operator");
  const { run, busy } = useAction();
  const [desc, setDesc] = useState("");
  const [due, setDue] = useState("");
  const [adj, setAdj] = useState<{ kind: "decrease" | "increase" | "void"; amount: string; reason: string }>({ kind: "decrease", amount: "", reason: "" });
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (inv.data) {
      setDesc(inv.data.description);
      setDue(inv.data.due_at.slice(0, 10));
    }
  }, [inv.data]);
  const x = inv.data;
  return (
    <Drawer title={x ? `${x.id} · ${x.customer_name}` : id} subtitle={x ? `Issued ${day(x.issued_at)} · due ${day(x.due_at)}` : undefined} onClose={onClose}>
      {inv.error && <ErrorNote error={inv.error} onRetry={inv.reload} />}
      {!x ? <Loading rows={6} /> : (
        <>
          <div className="row" style={{ justifyContent: "space-between" }}><InvoiceStatus i={x} /><span className="small muted">{x.description}</span></div>
          <div className="buckets" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))" }}>
            <div><span>Billed</span><b>{money(x.amount_minor, x.currency)}</b></div>
            <div><span>Adjustments</span><b>{money(x.effective_amount_minor - x.amount_minor, x.currency)}</b></div>
            <div><span>Paid &amp; written off</span><b>{money(x.effective_amount_minor - x.remaining_minor, x.currency)}</b></div>
            <div><span>Outstanding</span><b>{money(x.remaining_minor, x.currency)}</b></div>
          </div>
          <Card title="Payments applied" pad={false}>
            {x.allocations.length === 0 && x.writeoffs.length === 0 && !x.prior_paid_minor ? <Empty title="No payments yet" /> : (
              <table><tbody>
                {x.prior_paid_minor > 0 && <tr><td>Settled before this ledger period</td><td className="num"><Money minor={x.prior_paid_minor} ccy={x.currency} /></td></tr>}
                {x.allocations.map((a) => <tr key={a.deposit_id}><td><a href={`#/payments?deposit=${a.deposit_id}`} className="mono">{a.deposit_id}</a> · {a.payer_name} · {day(a.received_at)}</td><td className="num"><Money minor={a.amount_minor} ccy={x.currency} /></td></tr>)}
                {x.writeoffs.map((w, i) => <tr key={i}><td>Bank fee written off ({w.deposit_id})</td><td className="num"><Money minor={w.amount_minor} ccy={x.currency} /></td></tr>)}
              </tbody></table>
            )}
          </Card>
          {x.adjustments.length > 0 && (
            <Card title="Adjustments" pad={false}>
              <table><tbody>{x.adjustments.map((a) => (
                <tr key={a.id}><td><div>{a.reason}</div><div className="secondary">{a.created_by} · {when(a.created_at)} · <span className="mono">{a.id}</span></div></td><td className="num"><Money minor={a.delta_minor} ccy={x.currency} sign /></td></tr>
              ))}</tbody></table>
            </Card>
          )}
          {op && x.effective_status !== "void" && (
            <>
              <Card title="Details">
                <form className="form-grid" onSubmit={(e) => {
                  e.preventDefault();
                  run("inv-edit", () => post(`/invoices/${x.id}`, { description: desc, due_date: due }, "PATCH"), "Invoice updated");
                }}>
                  <Field id="ie-desc" label="Description" wide><input id="ie-desc" type="text" value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
                  <Field id="ie-due" label="Due date"><input id="ie-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
                  <div className="form-actions" style={{ alignSelf: "end", marginTop: 0 }}><button className="btn" disabled={!!busy}>Save details</button></div>
                </form>
                <p className="small muted" style={{ marginBottom: 0 }}>Amount, currency and customer are fixed once issued. Post an adjustment below instead.</p>
              </Card>
              <Card title="Post an adjustment">
                <form onSubmit={async (e) => {
                  e.preventDefault();
                  if (adj.kind !== "void" && (parseMajor(adj.amount) ?? 0) <= 0) return setErr("Enter an amount like 100.00");
                  if (adj.reason.trim().length < 3) return setErr("Give a reason for the audit trail");
                  setErr(null);
                  const r = await run("adj", () => post(`/invoices/${x.id}/adjustments`, { ...adj, amount: plainAmount(adj.amount) }), adj.kind === "void" ? "Invoice voided" : "Adjustment posted");
                  if (r) setAdj({ kind: "decrease", amount: "", reason: "" });
                }}>
                  <div className="form-grid">
                    <Field id="ad-kind" label="Type">
                      <select id="ad-kind" value={adj.kind} onChange={(e) => setAdj({ ...adj, kind: e.target.value as typeof adj.kind })}>
                        <option value="decrease">Credit note (reduce)</option><option value="increase">Additional charge</option><option value="void">Void invoice (no payments only)</option>
                      </select>
                    </Field>
                    {adj.kind !== "void" && <Field id="ad-amt" label={`Amount (${x.currency})`}><input id="ad-amt" type="text" inputMode="decimal" value={adj.amount} onChange={(e) => setAdj({ ...adj, amount: e.target.value })} /></Field>}
                    <Field id="ad-reason" label="Reason" wide><input id="ad-reason" type="text" value={adj.reason} onChange={(e) => setAdj({ ...adj, reason: e.target.value })} /></Field>
                  </div>
                  {err && <div className="notice risk small" role="alert" style={{ marginTop: 10 }}>{err}</div>}
                  <div className="form-actions"><button className={`btn ${adj.kind === "void" ? "danger" : "primary"}`} disabled={!!busy}>{adj.kind === "void" ? "Void invoice" : "Post adjustment"}</button></div>
                </form>
              </Card>
            </>
          )}
          <section>
            <h3 className="section-title">Audit</h3>
            <table><tbody>{x.audit.map((a) => <tr key={a.id}><td className="small muted nowrap">{when(a.at)}</td><td className="small" title={a.action}>{actionLabel(a.action)}</td><td className="small">{a.actor}</td></tr>)}</tbody></table>
          </section>
        </>
      )}
    </Drawer>
  );
}

function CustomerForm({ onClose, existing }: { onClose: () => void; existing?: Customer }) {
  const { run, busy } = useAction();
  const [f, setF] = useState({
    name: existing?.name ?? "", country: existing?.country ?? "", payer_names: existing?.payer_names.join(", ") ?? "",
    refund_beneficiary: existing?.refund_beneficiary ?? "", agent_public_key: "",
  });
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const payer_names = f.payer_names.split(",").map((s) => s.trim()).filter(Boolean);
    if (f.name.trim().length < 2) return setErr("Enter the customer's legal name.");
    if (!/^[A-Z]{2}$/.test(f.country)) return setErr("Enter a 2-letter country code, e.g. GB.");
    if (!payer_names.length) return setErr("Add at least one remitter name as it appears on bank statements.");
    if (f.refund_beneficiary.trim().length < 2) return setErr("Enter the account refunds should go to.");
    setErr(null);
    const body: Record<string, unknown> = { name: f.name, country: f.country, payer_names, refund_beneficiary: f.refund_beneficiary };
    if (f.agent_public_key || !existing) body.agent_public_key = f.agent_public_key || null;
    try {
      if (existing) await post(`/customers/${existing.id}`, body, "PATCH");
      else await post("/customers", body);
      await run("c", async () => null, existing ? "Customer updated" : "Customer created");
      onClose();
    } catch (ex) {
      setErr((ex as Error).message);
    }
  };
  return (
    <Modal title={existing ? `Edit ${existing.name}` : "New customer"} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <div className="form-grid">
          <Field id="nc-name" label="Legal name"><input id="nc-name" type="text" value={f.name} onChange={set("name")} /></Field>
          <Field id="nc-cty" label="Country" hint="ISO code, e.g. GB"><input id="nc-cty" type="text" maxLength={2} value={f.country} onChange={(e) => setF({ ...f, country: e.target.value.toUpperCase() })} /></Field>
          <Field id="nc-payers" label="Remitter names on statements" wide hint="Comma-separated. Must not overlap another customer's names.">
            <input id="nc-payers" type="text" value={f.payer_names} onChange={set("payer_names")} />
          </Field>
          <Field id="nc-ben" label="Refund account" wide hint={existing ? "Changing this invalidates any refund approval bound to the old account" : "Where refunds go"}>
            <input id="nc-ben" type="text" value={f.refund_beneficiary} onChange={set("refund_beneficiary")} />
          </Field>
          {!existing?.agent_url && (
            <Field id="nc-key" label={existing ? "Replace payer agent public key (optional)" : "Payer agent public key (optional)"} wide hint="Base64 raw Ed25519 key their agent signs explain_payment answers with">
              <input id="nc-key" type="text" className="mono" value={f.agent_public_key} onChange={set("agent_public_key")} />
            </Field>
          )}
        </div>
        {err && <div className="notice risk small" role="alert" style={{ marginTop: 12 }}>{err}</div>}
        <div className="form-actions"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!!busy}>{existing ? "Save changes" : "Create customer"}</button></div>
      </form>
    </Modal>
  );
}

/** Owner only: ask this customer's own agent at its URL. Only the public key is stored; its answers still face the three checks. */
function PayerAgentForm({ customer, onClose }: { customer: Customer; onClose: () => void }) {
  const { run, busy } = useAction();
  const [url, setUrl] = useState(customer.agent_url ?? "");
  const [key, setKey] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return setErr("Enter the agent's address.");  // the server enforces https and a public address
    if (!key.trim()) return setErr("Paste the public key the agent printed when it started.");
    setErr(null);
    try {
      await post(`/customers/${customer.id}/payer-agent`, { url: url.trim(), public_key: key.trim() }, "PUT");
      await run("agent", async () => null, `${customer.name} is now asked at its own agent`);
      onClose();
    } catch (ex) {
      setErr((ex as Error).message);
    }
  };
  const remove = async () => {
    const r = await run("agent", () => post(`/customers/${customer.id}/payer-agent`, undefined, "DELETE"),
      customer.demo_only ? `${customer.name} uses its simulated agent again` : `${customer.name} has no agent now`);
    if (r) onClose();
  };
  return (
    <Modal title={`Payer agent for ${customer.name}`} onClose={onClose}>
      <p className="small muted" style={{ marginTop: 0 }}>
        The customer runs its own agent, which keeps its own private key. Ledgerline asks it over the network what a payment was for
        and stores only its public key. Every answer still has to pass the three checks, and it can change a plan but never move money.
        {customer.demo_only ? " Without one, this practice customer uses a simulated agent on this server." : ""}
      </p>
      <form onSubmit={save} noValidate>
        <div className="form-grid">
          <Field id="pa-url" label="Agent address" wide hint="https only, a public address, for example https://agent.example.com/mcp">
            <input id="pa-url" type="url" className="mono" value={url} onChange={(e) => setUrl(e.target.value)} />
          </Field>
          <Field id="pa-key" label="Agent public key" wide hint="Base64 Ed25519 public key, as the agent printed it">
            <input id="pa-key" type="text" className="mono" value={key} onChange={(e) => setKey(e.target.value)} />
          </Field>
        </div>
        {err && <div className="notice risk small" role="alert" style={{ marginTop: 12 }}>{err}</div>}
        <div className="form-actions">
          {customer.agent_url && <button type="button" className="btn danger" disabled={!!busy} onClick={remove}>Stop using its own agent</button>}
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!!busy}>Save</button>
        </div>
      </form>
    </Modal>
  );
}

function NewInvoice({ customers, onClose }: { customers: Customer[]; onClose: () => void }) {
  const { run, busy } = useAction();
  const [f, setF] = useState({ customer_id: "", currency: "USD", amount: "", due_date: "", description: "" });
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const minor = parseMajor(f.amount);
    if (!f.customer_id) return setErr("Choose the customer to bill.");
    if (minor === null || minor <= 0) return setErr("Enter an amount greater than zero, like 1250.00.");
    if (!f.due_date) return setErr("Choose a due date.");
    if (!f.description.trim()) return setErr("Add a short description of what is billed.");
    setErr(null);
    try {
      const inv = await post<{ id: string }>("/invoices", { ...f, amount: plainAmount(f.amount) });
      await run("i", async () => null, `Invoice ${inv.id} created`);
      onClose();
    } catch (ex) {
      setErr((ex as Error).message);
    }
  };
  return (
    <Modal title="New invoice" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {customers.length === 0 && <div className="notice warn small" style={{ marginBottom: 12 }}>Create a customer first.</div>}
        <div className="form-grid">
          <Field id="ni-cust" label="Customer" wide>
            <select id="ni-cust" value={f.customer_id} onChange={set("customer_id")}>
              <option value="">Select…</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
          <Field id="ni-ccy" label="Currency"><select id="ni-ccy" value={f.currency} onChange={set("currency")}><option>USD</option><option>EUR</option><option>GBP</option></select></Field>
          <Field id="ni-amt" label="Amount"><input id="ni-amt" type="text" inputMode="decimal" placeholder="0.00" value={f.amount} onChange={set("amount")} /></Field>
          <Field id="ni-due" label="Due date"><input id="ni-due" type="date" value={f.due_date} onChange={set("due_date")} /></Field>
          <Field id="ni-desc" label="Description" wide><input id="ni-desc" type="text" value={f.description} onChange={set("description")} /></Field>
        </div>
        {err && <div className="notice risk small" role="alert" style={{ marginTop: 12 }}>{err}</div>}
        <div className="form-actions"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!!busy}>Create invoice</button></div>
      </form>
    </Modal>
  );
}
