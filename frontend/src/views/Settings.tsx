import { useEffect, useState } from "react";
import { del, get, post, type Ccy, type Customer, type Policy, type Status } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorNote, Field, Loading, Pill, useAction, useLoad, useToast } from "../components/ui";
import { majorString, parseMajor, when } from "../format";
import { hashParam, oauthErrorText, PROVIDER_LABEL, ProviderLogo, startUrl, type ProviderId } from "../components/OAuthButtons";

const CCYS: Ccy[] = ["USD", "EUR", "GBP"];

interface OrgSettings {
  id: string; name: string; kind: string; bank_mode: "local" | "airwallex_sandbox";
  airwallex_global_accounts: Partial<Record<Ccy, string>>; airwallex_webhook_secret_set: boolean; airwallex_connected: boolean; webhook_path: string;
  server: { airwallex_credentials_present: boolean; claude_key_present: boolean; claude_model: string; sandbox_allowed: boolean; claude_daily_limit: number };
  control_audit: { id: number; at: string; actor: string; action: string; detail: string }[];
}
type CheckResult = Record<string, { status: string; detail: string }>;

export function Settings() {
  const s = useLoad(() => get<Status>("/status"), []);
  const org = useLoad(() => get<OrgSettings>("/organization"), []);
  if (s.error) return <ErrorNote error={s.error} onRetry={s.reload} />;
  if (!s.data || !org.data) return <div className="card"><Loading rows={8} /></div>;
  return (
    <div className="stack">
      <PauseCard st={s.data} />
      <OrgCard org={org.data} />
      {org.data.kind !== "sample" && (!org.data.server.sandbox_allowed || org.data.airwallex_connected) && <ConnectAirwallex org={org.data} />}
      <IntegrationsCard st={s.data} org={org.data} />
      {org.data.bank_mode === 'airwallex_sandbox' && <><SandboxReceipts /><SandboxBeneficiaries /></>}
      <PolicyEditor policy={s.data.policy} />
      <div className="grid-2">
        <AccountCard />
        <SignInMethods />
        <Card title="Reference rates">
          <div className="small muted" style={{ marginBottom: 8 }}>{s.data.bank.mode === "local" ? "Fixed synthetic rates used by the local workspace. Not market data." : "Sandbox quotes are fetched per conversion."}</div>
          <table><tbody>{s.data.demo_fx_rates.map((r) => <tr key={r.sell + r.buy}><td>{r.sell} → {r.buy}</td><td className="num">{r.rate}</td></tr>)}</tbody></table>
        </Card>
      </div>
      {org.data.control_audit.length > 0 && (
        <Card title="Organization changes" pad={false}>
          <div className="table-wrap"><table><tbody>{org.data.control_audit.map((a) => (
            <tr key={a.id}><td className="small muted nowrap">{when(a.at)}</td><td className="mono small">{a.action}</td><td className="small">{a.actor}</td></tr>
          ))}</tbody></table></div>
        </Card>
      )}
    </div>
  );
}

function PauseCard({ st }: { st: Status }) {
  const { can } = useAuth();
  const { run, busy } = useAction();
  const [reason, setReason] = useState("");
  const mayToggle = st.paused ? can("owner") : can("operator");
  return (
    <Card title="Money-out control">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ maxWidth: 620 }}>
          {st.paused ? (
            <div className="notice risk"><b>Paused.</b> Refunds, retries of pending refunds and FX conversions are blocked. Matching and evidence checks keep running.
              {st.pause_info && <div className="small muted">By {st.pause_info.by} at {when(st.pause_info.at)}{st.pause_info.reason ? ` · “${st.pause_info.reason}”` : ""}</div>}
            </div>
          ) : <div className="small">Money-out is running. Any operator can pause every outbound action immediately; only an owner can resume. The switch persists across restarts.</div>}
        </div>
        {mayToggle ? (
          <div className="row">
            {!st.paused && <input type="text" aria-label="Reason for pausing" placeholder="Reason (recorded)" value={reason} onChange={(e) => setReason(e.target.value)} />}
            <button className={`btn ${st.paused ? "primary" : "danger solid"}`} disabled={!!busy}
              onClick={() => run("pause", () => post("/settings/pause", { paused: !st.paused, reason }), st.paused ? "Money-out resumed" : "Money-out paused")}>
              {st.paused ? "Resume money-out" : "Pause all money-out"}
            </button>
          </div>
        ) : <span className="small muted">{st.paused ? "An owner can resume." : "Viewers cannot change this."}</span>}
      </div>
    </Card>
  );
}

function OrgCard({ org }: { org: OrgSettings }) {
  const { can, refresh } = useAuth();
  const { run, busy } = useAction();
  const [name, setName] = useState(org.name);
  useEffect(() => setName(org.name), [org.name]);
  const owner = can("owner");
  return (
    <Card title="Organization">
      <form className="row" style={{ alignItems: "flex-end" }} onSubmit={async (e) => {
        e.preventDefault();
        if (await run("org", () => post("/organization", { name }, "PUT"), "Organization updated")) refresh();
      }}>
        <Field id="org-name" label="Name"><input id="org-name" type="text" value={name} disabled={!owner} onChange={(e) => setName(e.target.value)} style={{ width: 280 }} /></Field>
        {owner && <button className="btn" disabled={!!busy || name === org.name}>Save</button>}
        <span className="small muted">{org.kind === "sample" ? "Practice company (made-up data)" : "Workspace"} · <span className="mono">{org.id}</span></span>
      </form>
    </Card>
  );
}

function ConnectAirwallex({ org }: { org: OrgSettings }) {
  const { can, refresh } = useAuth();
  const { run, busy } = useAction();
  const owner = can("owner");
  const [f, setF] = useState({ client_id: "", api_key: "", webhook_secret: "" });
  const [missing, setMissing] = useState<string[]>([]);
  const webhookUrl = window.location.origin + org.webhook_path;
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  if (org.airwallex_connected) {
    return (
      <Card title="Your Airwallex account" actions={owner && <button className="btn small" disabled={!!busy} onClick={async () => { if (await run("aw-off", () => post("/integrations/airwallex/disconnect"), "Airwallex account disconnected")) refresh(); }}>Disconnect</button>}>
        <div className="row"><Pill status="matched" label="Connected (test environment)" /><span className="small muted">Keys are encrypted and never shown again.</span></div>
        {missing.length > 0 && <div className="notice small" style={{ marginTop: 10 }}>No single-currency receiving account was found for {missing.join(", ")}. Create one in Airwallex and enter its id below.</div>}
        <Field id="aw-url" label="Webhook address to add in Airwallex (deposit.settled)"><input id="aw-url" type="text" readOnly className="mono" value={webhookUrl} onFocus={(e) => e.target.select()} /></Field>
      </Card>
    );
  }
  return (
    <Card title="Connect your Airwallex account">
      <p className="small muted" style={{ marginTop: 0 }}>Use your sandbox client ID and API key from the Airwallex developer settings. Ledgerline checks them with Airwallex first and saves them encrypted only if they work. This connection reaches the Airwallex test environment only, so no real money can move.</p>
      {owner ? (
        <form className="form-grid" autoComplete="off" onSubmit={async (e) => {
          e.preventDefault();
          const r = await run("aw-on", () => post<{ missing_currencies: string[] }>("/integrations/airwallex/connect", f), "Airwallex account connected");
          setF({ client_id: "", api_key: "", webhook_secret: "" });
          if (r) { setMissing(r.missing_currencies); refresh(); }
        }}>
          <Field id="aw-client" label="Client ID"><input id="aw-client" type="text" autoComplete="off" value={f.client_id} onChange={set("client_id")} /></Field>
          <Field id="aw-key" label="API key"><input id="aw-key" type="password" autoComplete="off" value={f.api_key} onChange={set("api_key")} /></Field>
          <Field id="aw-hook" label="Webhook secret" hint={`Create a webhook in Airwallex for ${webhookUrl}, then paste its secret`}><input id="aw-hook" type="password" autoComplete="off" value={f.webhook_secret} onChange={set("webhook_secret")} /></Field>
          <div className="wide form-actions" style={{ marginTop: 0 }}><button className="btn primary" disabled={!!busy || !f.client_id || !f.api_key || f.webhook_secret.length < 8}>{busy === "aw-on" ? "Checking…" : "Check and connect"}</button></div>
        </form>
      ) : <p className="small muted">An owner can connect the account.</p>}
    </Card>
  );
}

function IntegrationsCard({ st, org }: { st: Status; org: OrgSettings }) {
  const { can } = useAuth();
  const toast = useToast();
  const { run, busy } = useAction();
  const owner = can("owner");
  const [check, setCheck] = useState<CheckResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [ga, setGa] = useState<Partial<Record<Ccy, string>>>(org.airwallex_global_accounts);
  const [secret, setSecret] = useState("");
  const webhookUrl = window.location.origin + org.webhook_path;
  const tone = (s?: string) => (s === "ok" ? "matched" : s === "error" ? "escalated" : "muted");
  return (
    <Card title="Integrations" actions={owner && (
      <button className="btn small" disabled={checking} onClick={async () => {
        setChecking(true);
        try {
          setCheck(await post<CheckResult>("/integrations/check"));
        } catch (e) {
          toast((e as Error).message, "error");
        } finally {
          setChecking(false);
        }
      }}>{checking ? "Checking…" : "Run readiness check"}</button>
    )}>
      <div className="table-wrap">
        <table className="integrations">
          <tbody>
            <tr>
              <td style={{ width: "28%" }}><b>Bank</b><div className="secondary">{st.bank.label}</div></td>
              <td>
                {owner && org.server.sandbox_allowed && !org.airwallex_connected ? (
                  <select aria-label="Bank mode" value={org.bank_mode} disabled={!!busy}
                    onChange={(e) => run("bank", () => post("/organization", { bank_mode: e.target.value }, "PUT"), "Bank mode updated")}>
                    <option value="local">Not connected</option>
                    <option value="airwallex_sandbox">Airwallex test environment</option>
                  </select>
                ) : <Pill status="muted" label={org.bank_mode === "local" ? "Not connected" : "Airwallex test environment"} />}
              </td>
              <td className="small">
                Run the readiness check to test the current connection. Checking does not move money.
                {check?.airwallex && <div style={{ marginTop: 4 }}><Pill status={tone(check.airwallex.status)} label={check.airwallex.status.replace("_", " ")} /> {check.airwallex.detail}</div>}
              </td>
            </tr>
            <tr>
              <td><b>Evidence reader</b><div className="secondary">{st.claude.label}</div></td>
              <td>{st.claude.mode === "claude_api" ? <Pill status="matched" label="Claude API key set" /> : <Pill status="muted" label="Offline rules" />}</td>
              <td className="small">Reads remittance text into a typed proposal. Advisory only: never signed, cannot move money.
                {check?.claude && <div style={{ marginTop: 4 }}><Pill status={tone(check.claude.status)} label={check.claude.status.replace("_", " ")} /> {check.claude.detail}</div>}
              </td>
            </tr>
            <tr>
              <td><b>Payer agents</b><div className="secondary">{st.payer_agents.label}</div></td>
              <td><Pill status="muted" label={st.payer_agents.transport} /></td>
              <td className="small">explain_payment is called over MCP. In this version the customer agents run on this server with their own signing keys; a customer's own hosted agent cannot be connected yet.</td>
            </tr>
            <tr>
              <td><b>Webhooks</b><div className="secondary">This organization's endpoint</div></td>
              <td colSpan={2} className="small">
                <input type="text" readOnly className="mono" value={webhookUrl} aria-label="Webhook URL" style={{ width: "100%" }} onFocus={(e) => e.target.select()} />
                <div style={{ marginTop: 6 }}>HMAC-SHA256 over x-timestamp + raw body, {st.policy.webhook_tolerance_seconds}s skew limit, event ids deduplicated. Signing secret: {st.security.webhook_secret_source}.</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      {owner && (
        <form className="form-grid" style={{ marginTop: 14 }} onSubmit={(e) => {
          e.preventDefault();
          const body: Record<string, unknown> = { airwallex_global_accounts: ga };
          if (secret) body.airwallex_webhook_secret = secret;
          run("aw", () => post("/organization", body, "PUT"), "Airwallex settings saved").then(() => setSecret(""));
        }}>
          {CCYS.map((c) => (
            <Field key={c} id={`ga-${c}`} label={`${c} global account id`} hint="Used for sandbox deposit simulation">
              <input id={`ga-${c}`} type="text" className="mono" value={ga[c] ?? ""} onChange={(e) => setGa({ ...ga, [c]: e.target.value })} />
            </Field>
          ))}
          <Field id="aw-secret" label="Airwallex webhook secret" hint={org.airwallex_webhook_secret_set ? "Set. Enter a new value to replace it; it is never shown again." : "Not set: the organization's local secret signs webhooks."}>
            <input id="aw-secret" type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} />
          </Field>
          <div className="wide form-actions" style={{ marginTop: 0 }}><button className="btn" disabled={!!busy}>Save Airwallex settings</button></div>
        </form>
      )}
    </Card>
  );
}

interface SandboxReceipt {
  request_id: string; currency: string; amount_minor: number; reference: string;
  status: string; provider_status?: string; deposit_id?: string; error_type?: string;
}

function SandboxReceipts() {
  const { can } = useAuth();
  const owner = can('owner');
  const toast = useToast();
  const list = useLoad(() => owner ? get<SandboxReceipt[]>('/integrations/sandbox/deposits') : Promise.resolve([]), [owner]);
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const [currency, setCurrency] = useState<Ccy>('EUR');
  const [amount, setAmount] = useState('1.23');
  const [payer, setPayer] = useState('Ledgerline sandbox verification');
  const [reference, setReference] = useState('Ledgerline verification');
  const [busy, setBusy] = useState(false);
  if (!owner) return null;
  const discover = async () => {
    setBusy(true);
    try {
      const r = await post<{ seen: number; ingested: string[]; already_known: number; other_account: number; before_cutoff: number; not_settled: number; rejected: number }>('/integrations/sandbox/deposits/discover');
      toast(`Checked ${r.seen} provider deposits: ${r.ingested.length} new${r.ingested.length ? ` (${r.ingested.join(', ')})` : ''}, ${r.already_known} already booked, ${r.not_settled} not settled, ${r.other_account + r.before_cutoff} outside this organization.`);
      list.reload();
    } catch (e) { toast((e as Error).message, 'error'); }
    finally { setBusy(false); }
  };
  const submit = async (sync: boolean) => {
    setBusy(true);
    try {
      if (sync) await post('/integrations/sandbox/deposits/sync');
      else {
        const minor = parseMajor(amount);
        if (minor === null || minor <= 0) throw new Error('Enter a positive sandbox amount with at most two decimal places.');
        await post('/integrations/sandbox/deposits', { request_id: requestId, currency, amount: majorString(minor), payer_name: payer, reference });
      }
      toast(sync ? 'Provider receipts checked; only settled funds are posted.' : 'Simulation request recorded. Check its status below.');
      list.reload();
    } catch (e) { toast((e as Error).message, 'error'); }
    finally { setBusy(false); }
  };
  return <Card title="Sandbox deposit verification">
    <p className="small muted">Airwallex sandbox only: no real money. Uses the dedicated account saved above. A pending response is not a settled receipt. Reusing this request ID cannot submit the same deposit twice.</p>
    <form className="form-grid" onSubmit={e => { e.preventDefault(); void submit(false); }}>
      <Field id="sandbox-currency" label="Sandbox receiving currency"><select id="sandbox-currency" value={currency} onChange={e => setCurrency(e.target.value as Ccy)}>{CCYS.map(c => <option key={c}>{c}</option>)}</select></Field>
      <Field id="sandbox-amount" label="Sandbox deposit amount"><input id="sandbox-amount" inputMode="decimal" value={amount} onChange={e => setAmount(e.target.value)} required /></Field>
      <Field id="sandbox-payer" label="Synthetic payer name"><input id="sandbox-payer" value={payer} onChange={e => setPayer(e.target.value)} maxLength={100} required /></Field>
      <Field id="sandbox-reference" label="Sandbox reference"><input id="sandbox-reference" value={reference} onChange={e => setReference(e.target.value)} maxLength={100} required /></Field>
      <div className="wide small muted">Request ID: {requestId}</div>
      <div className="wide form-actions"><button className="btn primary" disabled={busy}>Simulate sandbox deposit</button><button type="button" className="btn" disabled={busy} onClick={() => void submit(true)}>Sync sandbox receipts</button><button type="button" className="btn" disabled={busy} onClick={() => void discover()} title="Webhook fallback: lists provider deposits and books settled ones on this organization's accounts">Find missed deposits</button><button type="button" className="btn" disabled={busy} onClick={() => setRequestId(crypto.randomUUID())}>New deposit request</button></div>
    </form>
    {list.error && <ErrorNote error={list.error} onRetry={list.reload} />}
    {list.data && <div className="table-wrap"><table><thead><tr><th>Reference</th><th>Amount</th><th>Status</th><th>Provider</th></tr></thead><tbody>{list.data.map(r => <tr key={r.request_id}><td>{r.reference}{r.deposit_id && <div className="small">{r.deposit_id}</div>}</td><td>{r.currency} {(r.amount_minor / 100).toFixed(2)}</td><td>{r.status.replaceAll('_', ' ')}</td><td>{r.provider_status || r.error_type || 'Waiting'}</td></tr>)}</tbody></table></div>}
  </Card>;
}

interface BeneficiaryRow { id: string; name: string; currency: string; country: string; methods: string[]; account: string }
const BENE_FIELDS: Record<string, [string, string][]> = {
  EUR_DE_LOCAL: [['iban', 'IBAN']],
  GBP_GB_LOCAL: [['account_number', 'Account number (8 digits)'], ['sort_code', 'Sort code (6 digits)']],
  USD_US_LOCAL: [['account_number', 'Account number'], ['aba', 'ABA routing number (9 digits)']],
};

function SandboxBeneficiaries() {
  const list = useLoad(() => get<{ corridors: Record<string, string>; items: BeneficiaryRow[] }>('/integrations/sandbox/beneficiaries'), []);
  const customers = useLoad(() => get<Customer[]>('/customers'), []);
  const { run, busy } = useAction();
  const [corridor, setCorridor] = useState('EUR_DE_LOCAL');
  const [schema, setSchema] = useState<{ provider_required: string[] } | null>(null);
  const [f, setF] = useState<Record<string, string>>({ company_name: '', bank_name: '', street_address: '', city: '', postcode: '' });
  const [customer, setCustomer] = useState('');
  useEffect(() => {
    setSchema(null);
    get<{ provider_required: string[] }>(`/integrations/sandbox/beneficiaries/schema?corridor=${corridor}`).then(setSchema).catch(() => setSchema(null));
  }, [corridor]);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const text = (k: string, label: string) => <Field key={k} id={`bn-${k}`} label={label}><input id={`bn-${k}`} value={f[k] ?? ''} onChange={set(k)} required /></Field>;
  return <Card title="Refund beneficiaries (Airwallex sandbox)">
    <p className="small muted">Refunds are paid to a sandbox beneficiary. New ones are checked by Airwallex (validate) before they are created. Synthetic details only; account numbers are shown masked.</p>
    {list.error && <ErrorNote error={list.error} onRetry={list.reload} />}
    {list.data && (list.data.items.length === 0 ? <p className="small">No beneficiaries yet.</p> : <div className="table-wrap"><table><thead><tr><th>Name</th><th>Currency</th><th>Method</th><th>Account</th><th>Id</th></tr></thead><tbody>
      {list.data.items.map((b) => <tr key={b.id}><td>{b.name}</td><td>{b.currency} · {b.country}</td><td>{b.methods.join(', ')}</td><td className="mono">{b.account}</td><td className="mono small">{b.id}</td></tr>)}
    </tbody></table></div>)}
    <form className="form-grid" style={{ marginTop: 14 }} onSubmit={(e) => {
      e.preventDefault();
      run('bene', () => post<BeneficiaryRow>('/integrations/sandbox/beneficiaries', { corridor, ...f, customer_id: customer || null }),
        (b) => `Beneficiary ${b.name} created${customer ? ` and set as ${customer}'s refund destination` : ''}`)
        .then((r) => { if (r) { list.reload(); customers.reload(); } });
    }}>
      <Field id="bn-corridor" label="Corridor" hint={schema ? `Airwallex schema requires: ${schema.provider_required.map((s) => s.split('.').pop()).join(', ')}` : 'Reading the Airwallex schema…'}>
        <select id="bn-corridor" value={corridor} onChange={(e) => setCorridor(e.target.value)}>
          {Object.entries(list.data?.corridors ?? { EUR_DE_LOCAL: 'EUR · Germany · SEPA (IBAN)' }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Field>
      {text('company_name', 'Company name')}
      {text('bank_name', 'Bank name')}
      {text('street_address', 'Street address')}
      {text('city', 'City')}
      {text('postcode', 'Postcode')}
      {BENE_FIELDS[corridor].map(([k, label]) => text(k, label))}
      <Field id="bn-customer" label="Use for customer (optional)" hint="Sets that customer's refund destination">
        <select id="bn-customer" value={customer} onChange={(e) => setCustomer(e.target.value)}>
          <option value="">Do not link</option>
          {(customers.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name} ({c.id})</option>)}
        </select>
      </Field>
      <div className="wide form-actions" style={{ marginTop: 0 }}><button className="btn primary" disabled={!!busy}>{busy ? 'Validating…' : 'Validate and create'}</button></div>
    </form>
  </Card>;
}

function PolicyEditor({ policy }: { policy: Policy }) {
  const { can } = useAuth();
  const { run, busy } = useAction();
  const owner = can("owner");
  const fields = ["fee_tolerance_minor", "refund_auto_limit_minor", "reserve_minor", "ring_fenced_minor"] as const;
  const labels: Record<(typeof fields)[number], string> = {
    fee_tolerance_minor: "Bank-fee tolerance",
    refund_auto_limit_minor: "Refund auto-approval limit",
    reserve_minor: "Minimum reserve",
    ring_fenced_minor: "Set aside from planning",
  };
  const init = () => Object.fromEntries(fields.map((f) => [f, Object.fromEntries(CCYS.map((c) => [c, majorString(policy[f][c])]))])) as Record<string, Record<Ccy, string>>;
  const [v, setV] = useState(init);
  const [bps, setBps] = useState(String(policy.fee_tolerance_bps));
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setV(init()), [policy]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = (e: React.FormEvent) => {
    e.preventDefault();
    const body: Record<string, unknown> = {};
    for (const f of fields) {
      const out: Record<string, number> = {};
      for (const c of CCYS) {
        const m = parseMajor(v[f][c]);
        if (m === null) return setErr(`${labels[f]} ${c}: enter an amount like 25.00`);
        out[c] = m;
      }
      body[f] = out;
    }
    if (!/^\d+$/.test(bps)) return setErr("Fee tolerance share must be whole basis points");
    body.fee_tolerance_bps = Number(bps);
    setErr(null);
    run("policy", () => post("/settings/policy", body, "PUT"), "Policy saved");
  };
  return (
    <Card title="Policy">
      <form onSubmit={save} noValidate>
        <div className="small muted" style={{ marginBottom: 10 }}>Limits live in code and the database, never in a model prompt. {owner ? "Changes are audited." : "Only owners can change policy."}</div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Rule</th>{CCYS.map((c) => <th key={c} className="num">{c}</th>)}</tr></thead>
            <tbody>
              {fields.map((f) => (
                <tr key={f}>
                  <td>{labels[f]}</td>
                  {CCYS.map((c) => (
                    <td key={c} className="num">
                      <input type="text" inputMode="decimal" aria-label={`${labels[f]} ${c}`} style={{ width: 120, textAlign: "right" }} disabled={!owner}
                        value={v[f][c]} onChange={(e) => setV({ ...v, [f]: { ...v[f], [c]: e.target.value } })} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="row" style={{ marginTop: 12, justifyContent: "space-between" }}>
          <Field id="pol-bps" label="Fee tolerance cap (basis points of amount billed)">
            <input id="pol-bps" type="text" inputMode="numeric" style={{ width: 120 }} value={bps} disabled={!owner} onChange={(e) => setBps(e.target.value)} />
          </Field>
          {owner && <button className="btn primary" disabled={!!busy}>Save policy</button>}
        </div>
        {err && <div className="notice risk small" role="alert" style={{ marginTop: 10 }}>{err}</div>}
      </form>
    </Card>
  );
}

function AccountCard() {
  const { me } = useAuth();
  const { run, busy } = useAction();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const ids = useLoad(() => get<Identities>("/auth/identities"), []);
  return (
    <Card title="Your account">
      <dl className="kv small" style={{ marginBottom: 12 }}>
        <dt>Name</dt><dd>{me?.user.name}</dd>
        <dt>Email</dt><dd>{me?.user.email}</dd>
        <dt>Session ends</dt><dd>{when(me?.session_expires_at)} at the latest; after 2 hours idle</dd>
      </dl>
      {ids.data && !ids.data.has_password ? (
        <p className="muted small" style={{ margin: 0 }}>You sign in with {ids.data.identities.map((i) => PROVIDER_LABEL[i.provider]).join(" or ")}. This account has no Ledgerline password.</p>
      ) : (
      <form className="stack" style={{ gap: 10 }} onSubmit={async (e) => {
        e.preventDefault();
        const r = await run("pw", () => post("/auth/change-password", { current_password: cur, new_password: next }), "Password changed; other sessions were signed out");
        if (r) { setCur(""); setNext(""); }
      }}>
        <Field id="pw-cur" label="Current password"><input id="pw-cur" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></Field>
        <Field id="pw-new" label="New password" hint="12+ characters, upper- and lower-case letters and a digit"><input id="pw-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
        <div><button className="btn" disabled={!!busy || !cur || !next}>Change password</button></div>
      </form>
      )}
    </Card>
  );
}

interface Identities {
  identities: { provider: ProviderId; email: string; created_at: string; last_login_at: string | null }[];
  has_password: boolean;
  available: Record<ProviderId, boolean>;
}

function SignInMethods() {
  const ids = useLoad(() => get<Identities>("/auth/identities"), []);
  const { run, busy } = useAction();
  const toast = useToast();
  useEffect(() => {
    const linked = hashParam("oauth_linked");
    const error = oauthErrorText(hashParam("oauth_error"));
    if (linked) toast(`${PROVIDER_LABEL[linked as ProviderId] ?? linked} connected`);
    if (error) toast(error, "error");
    if (linked || error) history.replaceState(null, "", "#/settings");
  }, [toast]);
  if (!ids.data) return <Card title="Sign-in methods"><Loading rows={2} /></Card>;
  const d = ids.data;
  return (
    <Card title="Sign-in methods">
      <ul className="signin-methods">
        <li>
          <span className="sm-icon" aria-hidden="true">@</span>
          <div><b>Email and password</b><small>{d.has_password ? "Set" : "Not set: this account signs in with a provider"}</small></div>
        </li>
        {(["google", "apple"] as ProviderId[]).map((p) => {
          const linked = d.identities.find((i) => i.provider === p);
          return (
            <li key={p}>
              <span className={`sm-icon ${p}`}><ProviderLogo id={p} /></span>
              <div>
                <b>{PROVIDER_LABEL[p]}</b>
                <small>{linked ? `Connected${linked.email ? ` · ${linked.email}` : ""}` : d.available[p] ? "Not connected" : "Not set up on this server"}</small>
              </div>
              {linked ? (
                <button className="btn small" disabled={!!busy} onClick={() => run(`unlink-${p}`, () => del(`/auth/identities/${p}`), `${PROVIDER_LABEL[p]} disconnected`).then(() => ids.reload())}>Disconnect</button>
              ) : d.available[p] ? (
                <a className="btn small" href={startUrl(p, { intent: "link" })}>Connect</a>
              ) : null}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
