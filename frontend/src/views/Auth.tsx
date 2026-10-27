import { useEffect, useState } from "react";
import { ApiError, get, post, type Me } from "../api";
import { useAuth } from "../auth";
import { Field } from "../components/ui";
import { hashParam, OAuthButtons, oauthErrorText } from "../components/OAuthButtons";

function Brand() {
  return (
    <a className="auth-brand" href="#/home" aria-label="Ledgerline home">
      <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
        <rect width="32" height="32" rx="6" fill="#0f1b2d" />
        <path d="M9 8v16h14" stroke="#5EC4B6" strokeWidth="3" fill="none" />
        <path d="M14 18h9" stroke="#fff" strokeWidth="3" />
      </svg>
      <span>Ledgerline</span>
    </a>
  );
}

function AuthFrame({ title, children, foot }: { title: string; children: React.ReactNode; foot?: React.ReactNode }) {
  return (
    <div className="auth-page">
      <main className="auth-card" aria-labelledby="auth-title">
        <Brand />
        <h1 id="auth-title">{title}</h1>
        {children}
        {foot && <div className="auth-foot">{foot}</div>}
      </main>
      <p className="auth-note">Reconciliation for multi-currency receivables. Local workspaces use a simulated bank and synthetic data.</p>
    </div>
  );
}

export function SignIn({ initialMode = "signin" }: { initialMode?: "signin" | "signup" }) {
  const { setMe } = useAuth();
  const [mode, setMode] = useState<"signin" | "signup">(initialMode);
  const [f, setF] = useState({ email: "", password: "", name: "", organization_name: "", start_with: "empty" as "empty" | "sample" });
  const [err, setErr] = useState<string | null>(() => oauthErrorText(hashParam("oauth_error")));
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    if (mode === "signup" && f.password.length < 12) return setErr("Use at least 12 characters with upper- and lower-case letters and a digit.");
    setBusy(true);
    try {
      const me = mode === "signin"
        ? await post<Me>("/auth/login", { email: f.email, password: f.password })
        : await post<Me>("/auth/signup", { email: f.email, password: f.password, name: f.name, organization_name: f.organization_name, start_with: f.start_with });
      setMe(me);
      window.location.hash = "/inbox";
    } catch (ex) {
      setErr(ex instanceof ApiError && ex.status === 429 ? "Too many failed attempts. Wait 15 minutes and try again." : (ex as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame
      title={mode === "signin" ? "Sign in" : "Create your organization"}
      foot={mode === "signin"
        ? <>New to Ledgerline? <button className="linkish" onClick={() => { setMode("signup"); setErr(null); }}>Create an organization</button></>
        : <>Already have an account? <button className="linkish" onClick={() => { setMode("signin"); setErr(null); }}>Sign in</button></>}
    >
      <OAuthButtons verb={mode === "signin" ? "Continue" : "Sign up"} />
      <form onSubmit={submit} noValidate className="stack" style={{ gap: 12 }}>
        {mode === "signup" && (
          <>
            <Field id="su-name" label="Your name"><input id="su-name" type="text" autoComplete="name" value={f.name} onChange={set("name")} /></Field>
            <Field id="su-org" label="Organization" hint="Your company's legal or trading name">
              <input id="su-org" type="text" autoComplete="organization" value={f.organization_name} onChange={set("organization_name")} />
            </Field>
          </>
        )}
        <Field id="au-email" label="Work email"><input id="au-email" type="email" autoComplete="username" value={f.email} onChange={set("email")} /></Field>
        <Field id="au-pass" label="Password" hint={mode === "signup" ? "12+ characters, upper- and lower-case letters and a digit" : undefined}>
          <input id="au-pass" type="password" autoComplete={mode === "signin" ? "current-password" : "new-password"} value={f.password} onChange={set("password")} />
        </Field>
        {mode === "signup" && (
          <fieldset className="choice">
            <legend>Start with</legend>
            <label><input type="radio" name="start" checked={f.start_with === "empty"} onChange={() => setF({ ...f, start_with: "empty" })} />
              <span><b>An empty workspace</b><small>Add your customers, invoices and received payments.</small></span></label>
            <label><input type="radio" name="start" checked={f.start_with === "sample"} onChange={() => setF({ ...f, start_with: "sample" })} />
              <span><b>Sample data</b><small>A synthetic company with six received payments to work through.</small></span></label>
          </fieldset>
        )}
        {err && <div className="notice risk small" role="alert">{err}</div>}
        <button className="btn primary" disabled={busy} style={{ height: 36 }}>
          {busy ? "Please wait…" : mode === "signin" ? "Sign in" : "Create organization"}
        </button>
      </form>
    </AuthFrame>
  );
}

export function AcceptInvite({ token }: { token: string }) {
  const { setMe, me } = useAuth();
  const [info, setInfo] = useState<{ email: string; role: string; org_name: string; existing_user: boolean } | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    get<typeof info>(`/invitations/${encodeURIComponent(token)}`).then(setInfo).catch((e) => setLoadErr(e.message));
  }, [token]);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      setMe(await post<Me>(`/invitations/${encodeURIComponent(token)}/accept`, { name, password }));
      window.location.hash = "/inbox";
    } catch (ex) {
      setErr((ex as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (loadErr) return <AuthFrame title="Invitation unavailable" foot={<a href="#/inbox">Go to sign in</a>}><p>{loadErr}</p></AuthFrame>;
  if (!info) return <AuthFrame title="Checking invitation…"><div className="skeleton" /></AuthFrame>;
  const signedInAsInvitee = me && me.user.email.toLowerCase() === info.email.toLowerCase();
  const joinSignedIn = async () => {
    setBusy(true);
    setErr(null);
    try {
      await post(`/invitations/${encodeURIComponent(token)}/accept-signed-in`);
      setMe(await get<Me>("/auth/me"));
      window.location.hash = "/inbox";
    } catch (ex) {
      setErr((ex as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (signedInAsInvitee) {
    return (
      <AuthFrame title={`Join ${info.org_name}`}>
        <p className="muted small" style={{ marginTop: 0 }}>Invited as <b>{info.role}</b> · signed in as {me.user.email}</p>
        {err && <div className="notice risk small" role="alert" style={{ marginBottom: 12 }}>{err}</div>}
        <button className="btn primary" style={{ height: 36, width: "100%" }} disabled={busy} onClick={joinSignedIn}>{busy ? "Joining…" : "Join organization"}</button>
      </AuthFrame>
    );
  }
  return (
    <AuthFrame title={`Join ${info.org_name}`}>
      <p className="muted small" style={{ marginTop: 0 }}>Invited as <b>{info.role}</b> · {info.email}</p>
      {me && <div className="notice small" style={{ marginBottom: 12 }}>You are signed in as {me.user.email}, but this invitation is for {info.email}.</div>}
      {!me && <OAuthButtons returnTo={`/#/invite?token=${token}`} />}
      <form onSubmit={submit} noValidate className="stack" style={{ gap: 12 }}>
        {!info.existing_user && (
          <Field id="inv-name" label="Your name"><input id="inv-name" type="text" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        )}
        <Field id="inv-pass" label={info.existing_user ? "Your Ledgerline password" : "Choose a password"} hint={info.existing_user ? undefined : "12+ characters, upper- and lower-case letters and a digit"}>
          <input id="inv-pass" type="password" autoComplete={info.existing_user ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {err && <div className="notice risk small" role="alert">{err}</div>}
        <button className="btn primary" disabled={busy} style={{ height: 36 }}>{busy ? "Joining…" : "Join organization"}</button>
      </form>
    </AuthFrame>
  );
}

export function NoOrganization() {
  const { setMe, signOut, me } = useAuth();
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  return (
    <AuthFrame title="No organization" foot={<button className="linkish" onClick={signOut}>Sign out</button>}>
      <p className="small">{me?.user.email} is not a member of any organization. Ask an owner for an invitation, or create a new one.</p>
      <form className="stack" style={{ gap: 12 }} onSubmit={async (e) => {
        e.preventDefault();
        try {
          setMe(await post<Me>("/organizations", { name, start_with: "empty" }));
        } catch (ex) {
          setErr((ex as Error).message);
        }
      }}>
        <Field id="no-org" label="Organization name"><input id="no-org" type="text" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        {err && <div className="notice risk small" role="alert">{err}</div>}
        <button className="btn primary">Create organization</button>
      </form>
    </AuthFrame>
  );
}
