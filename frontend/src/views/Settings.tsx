import { useEffect, useState } from "react";
import { del, get, post, type Ccy, type Policy, type Status } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorNote, Field, Loading, Pill, useAction, useLoad, useToast } from "../components/ui";
import { majorString, parseMajor, when } from "../format";
import { hashParam, oauthErrorText, PROVIDER_LABEL, ProviderLogo, startUrl, type ProviderId } from "../components/OAuthButtons";

const CCYS: Ccy[] = ["USD", "EUR", "GBP"];

interface OrgSettings {
  id: string; name: string; kind: string; bank_mode: "local" | "airwallex_sandbox";
  airwallex_global_accounts: Partial<Record<Ccy, string>>; airwallex_webhook_secret_set: boolean; webhook_path: string;
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
      <IntegrationsCard st={s.data} org={org.data} />
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
        <span className="small muted">{org.kind === "sample" ? "Sample organization (synthetic data, walkthrough available)" : "Workspace"} · <span className="mono">{org.id}</span></span>
      </form>
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
                {owner ? (
                  <select aria-label="Bank mode" value={org.bank_mode} disabled={!!busy}
                    onChange={(e) => run("bank", () => post("/organization", { bank_mode: e.target.value }, "PUT"), "Bank mode updated")}>
                    <option value="local">Local workspace (simulated bank)</option>
                    <option value="airwallex_sandbox" disabled={!org.server.sandbox_allowed}>Airwallex sandbox{org.server.sandbox_allowed ? "" : org.server.airwallex_credentials_present ? " (reserved for operator-approved organizations)" : " (server credentials missing)"}</option>
                  </select>
                ) : <Pill status="muted" label={org.bank_mode === "local" ? "Local simulation" : "Airwallex sandbox"} />}
              </td>
              <td className="small">
                Airwallex API credentials are set by the server operator ({org.server.airwallex_credentials_present ? "present" : "not set"}).
                The sandbox adapter follows the documented endpoints but has not been executed against the live sandbox in this build.
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
              <td className="small">explain_payment is called over MCP. The customer agents in this build are local simulations with their own signing keys.</td>
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

function PolicyEditor({ policy }: { policy: Policy }) {
  const { can } = useAuth();
  const { run, busy } = useAction();
  const owner = can("owner");
  const fields = ["fee_tolerance_minor", "refund_auto_limit_minor", "reserve_minor"] as const;
  const labels: Record<(typeof fields)[number], string> = {
    fee_tolerance_minor: "Bank-fee tolerance",
    refund_auto_limit_minor: "Refund auto-approval limit",
    reserve_minor: "Minimum reserve",
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
