import { useEffect, useRef, useState } from "react";
import { get, post, type Me, type Status } from "./api";
import { AuthProvider, ROLE_LABEL, useAuth } from "./auth";
import { Field, Modal, RefreshProvider, ToastProvider, useLoad, useToast } from "./components/ui";
import { Ceo } from "./views/Ceo";
import { Inbox } from "./views/Inbox";
import { Payments } from "./views/Payments";
import { EvidenceView } from "./views/Evidence";
import { Approvals } from "./views/Approvals";
import { Treasury } from "./views/Treasury";
import { Ledger } from "./views/Ledger";
import { Activity } from "./views/Activity";
import { Customers } from "./views/Customers";
import { Settings } from "./views/Settings";
import { Team } from "./views/Team";
import { Walkthrough } from "./views/Walkthrough";
import { AcceptInvite, NoOrganization, ResetPassword, SignIn, friendly } from "./views/Auth";
import { Landing } from "./views/Landing";
import { Architecture } from "./views/Architecture";
import { ShowMe } from "./components/ShowMe";
import { Changelog, Help, Privacy, Security, Terms, VersionLine } from "./views/Legal";
import { PageError } from "./components/PageError";

export type Route = { page: string; params: URLSearchParams };

function parseHash(): Route {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [page, query = ""] = raw.split("?");
  return { page: page || "inbox", params: new URLSearchParams(query) };
}

export function go(page: string, params?: Record<string, string>) {
  const q = params ? new URLSearchParams(params).toString() : "";
  window.location.hash = `/${page}${q ? `?${q}` : ""}`;
}

function useRoute() {
  const [route, setRoute] = useState<Route>(parseHash);
  useEffect(() => {
    let page = parseHash().page;
    const on = () => {
      const next = parseHash();
      // A different page starts at the top instead of keeping the previous page's scroll position.
      if (next.page !== page) window.scrollTo(0, 0);
      page = next.page;
      setRoute(next);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

const NAV: { id: string; label: string; section?: string; sampleOnly?: boolean }[] = [
  { id: "ceo", label: "CEO view", section: "Operations" },
  { id: "inbox", label: "Inbox" },
  { id: "payments", label: "Payments" },
  { id: "approvals", label: "Approvals" },
  { id: "evidence", label: "Evidence" },
  { id: "treasury", label: "Treasury", section: "Money" },
  { id: "ledger", label: "Ledger" },
  { id: "customers", label: "Customers & invoices", section: "Records" },
  { id: "activity", label: "Activity" },
  { id: "team", label: "Team", section: "Organization" },
  { id: "settings", label: "Settings" },
  { id: "walkthrough", label: "Practice steps", sampleOnly: true },
];

const TITLES: Record<string, [string, string]> = {
  ceo: ["CEO view", "Are we safe, what happened, and what needs you"],
  inbox: ["Inbox", "Cash position and work that needs a decision"],
  payments: ["Payments", "Received funds, how each was matched, and what is left"],
  approvals: ["Approvals", "Money-out decisions bound to an exact scope"],
  evidence: ["Evidence", "Payer answers, the three checks, and how plans changed"],
  treasury: ["Treasury", "What to pay first, reserves and conversions"],
  ledger: ["Ledger", "Per-currency conservation and the journal"],
  customers: ["Customers & invoices", "Who pays, what they owe, and their credits"],
  activity: ["Activity", "Audit trail of every decision and operation"],
  team: ["Team", "Members, roles and invitations"],
  settings: ["Settings", "Organization, integrations, controls and policy"],
  walkthrough: ["Practice steps", "A guided run through the practice company's payments"],
};

function OrgMenu({ me }: { me: Me }) {
  const { switchOrg, setMe } = useAuth();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [start, setStart] = useState<"empty" | "sample">("empty");
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const org = me.organization!;
  return (
    <div className="org-menu" ref={ref}>
      <button className="org-button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="org-name">{org.name}</span>
        <small>{org.kind === "sample" ? "Practice company" : "Organization"} · {ROLE_LABEL[org.role]}</small>
      </button>
      {open && (
        <div className="menu" role="menu" onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
          <div className="menu-label">Switch organization</div>
          {me.organizations.map((o) => (
            <button key={o.id} role="menuitemradio" aria-checked={o.id === org.id} className="menu-item"
              onClick={() => { setOpen(false); if (o.id !== org.id) switchOrg(o.id).catch((e) => toast(e.message, "error")); }}>
              <span>{o.name}</span><small>{ROLE_LABEL[o.role]}{o.kind === "sample" ? " · practice" : ""}</small>
            </button>
          ))}
          <div className="menu-sep" />
          <button role="menuitem" className="menu-item" onClick={() => { setOpen(false); setCreating(true); }}>New organization…</button>
        </div>
      )}
      {creating && (
        <Modal title="New organization" onClose={() => setCreating(false)}>
          <form onSubmit={async (e) => {
            e.preventDefault();
            try {
              setMe(await post<Me>("/organizations", { name, start_with: start }));
              setCreating(false);
              window.location.hash = "/inbox";
            } catch (ex) {
              setErr(friendly(ex as Error));
            }
          }}>
            <div className="stack" style={{ gap: 12 }}>
              <Field id="no-name" label="Name"><input id="no-name" type="text" value={name} onChange={(e) => setName(e.target.value)} /></Field>
              <fieldset className="choice">
                <legend>Start with</legend>
                <label><input type="radio" name="ns" checked={start === "empty"} onChange={() => setStart("empty")} /><span><b>My company</b></span></label>
                <label><input type="radio" name="ns" checked={start === "sample"} onChange={() => setStart("sample")} /><span><b>Practice company</b><small>Made-up customers and six payments, separate from your real data.</small></span></label>
              </fieldset>
              {err && <div className="notice risk small" role="alert">{err}</div>}
            </div>
            <div className="form-actions"><button type="button" className="btn" onClick={() => setCreating(false)}>Cancel</button><button className="btn primary">Create</button></div>
          </form>
        </Modal>
      )}
    </div>
  );
}

function Shell({ me }: { me: Me }) {
  const route = useRoute();
  const { signOut } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [tour, setTour] = useState(false);
  const [narrow, setNarrow] = useState(() => window.matchMedia("(max-width: 820px)").matches);
  useEffect(() => {
    const m = window.matchMedia("(max-width: 820px)");
    const f = () => setNarrow(m.matches);
    m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, []);
  useEffect(() => setMenuOpen(false), [route.page]);
  const status = useLoad(() => get<Status>("/status"), [me.organization?.id]);
  const counts = useLoad(() => get<{ work_queue: { kind: string }[]; deposit_counts: Record<string, number> }>("/overview"), [me.organization?.id]);
  const pendingApprovals = counts.data?.work_queue.filter((w) => w.kind === "approval").length ?? 0;
  const needsReview = counts.data?.deposit_counts?.escalated ?? 0;
  const known = !!TITLES[route.page];
  const page = known ? route.page : "inbox";
  const [title, sub] = TITLES[page];
  const s = status.data;
  const localMode = s?.bank.mode === "local";
  const isSample = me.organization?.kind === "sample";

  useEffect(() => {
    document.title = `${title} · ${me.organization?.name ?? "Ledgerline"}`;
  }, [title, me.organization?.name]);

  return (
    <div className="shell">
      {/* Hash routing: a #main link would change the route, so the skip control moves focus instead. */}
      <button type="button" className="skip-link" onClick={() => document.getElementById("main")?.focus()}>Skip to content</button>
      <aside className={`sidebar ${menuOpen ? "open" : ""}`} aria-label="Main navigation" {...(narrow && !menuOpen ? { inert: "" } : {})}>
        <a className="brand" href="#/home" aria-label="Ledgerline home">
          <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="6" fill="#16263d" />
            <path d="M9 8v16h14" stroke="#5EC4B6" strokeWidth="3" fill="none" />
            <path d="M14 18h9" stroke="#fff" strokeWidth="3" />
          </svg>
          <span>Ledgerline</span>
        </a>
        <OrgMenu me={me} />
        <nav className="nav">
          {NAV.filter((n) => !n.sampleOnly || isSample).map((n) => (
            <div key={n.id}>
              {n.section && <div className="nav-section">{n.section}</div>}
              <a href={`#/${n.id}`} aria-current={page === n.id ? "page" : undefined}>
                <span>{n.label}</span>
                {n.id === "approvals" && pendingApprovals > 0 && <span className="count warn" aria-label={`${pendingApprovals} pending`}>{pendingApprovals}</span>}
                {n.id === "payments" && needsReview > 0 && <span className="count" aria-label={`${needsReview} need review`}>{needsReview}</span>}
              </a>
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="who">{me.user.name}</div>
          <div className="small" style={{ overflowWrap: "anywhere" }}>{me.user.email}</div>
          <button className="btn small ghost signout" onClick={signOut}>Sign out</button>
        </div>
      </aside>
      {menuOpen && <div className="scrim" style={{ zIndex: 24 }} onClick={() => setMenuOpen(false)} />}
      <div className="main">
        <header className="topbar">
          <div className="row" style={{ gap: 12, flexWrap: "nowrap", minWidth: 0 }}>
            <button className="btn menu-btn" aria-label="Open navigation" onClick={() => setMenuOpen(true)}>Menu</button>
            <div style={{ minWidth: 0 }}>
              <h1>{title}</h1>
              <div className="sub hide-sm">{sub}</div>
            </div>
          </div>
          <div className="topbar-right">
            <a className="btn small ghost" href={`#/help?topic=${page}`}>Help</a>
            {isSample && !tour && <button className="btn small" onClick={() => setTour(true)}>Show me</button>}
            {s?.paused && (
              <a className="badge paused" href="#/settings" title={s.pause_info ? `Paused by ${s.pause_info.by}${s.pause_info.reason ? `: ${s.pause_info.reason}` : ""}` : "Money-out paused"}><b>Money-out paused</b></a>
            )}
            {me.role === "viewer" && <span className="badge" title="You can view and export, but not change anything"><b>Read-only</b></span>}
            {s && (
              <a className="badge" href="#/settings" title={s.bank.label}>
                <b>{isSample ? "Practice company" : localMode ? "No bank connected" : "Airwallex"}</b>
                <span className="hide-sm">{isSample ? "made-up data" : localMode ? "manual records" : "test environment"}</span>
              </a>
            )}
          </div>
        </header>
        {tour && isSample && <ShowMe onClose={() => setTour(false)} />}
        <main className="content" id="main" tabIndex={-1}>
          <PageError key={route.page}>
          {!known && route.page !== "inbox" && (
            <div className="card"><div className="empty"><b>Page not found</b>
              There is no page at #/{route.page}. <a href="#/inbox">Go to the inbox</a> or <a href="#/help">open Help</a>.</div></div>
          )}
          {page === "ceo" && <Ceo />}
          {known && page === "inbox" && <Inbox />}
          {page === "payments" && <Payments route={route} />}
          {page === "approvals" && <Approvals localMode={localMode} recordsOnly={localMode && !isSample} sandboxMode={s?.bank.mode === "airwallex_sandbox"} />}
          {page === "evidence" && <EvidenceView route={route} />}
          {page === "treasury" && <Treasury localMode={localMode} recordsOnly={localMode && !isSample} />}
          {page === "ledger" && <Ledger />}
          {page === "customers" && <Customers route={route} />}
          {page === "activity" && <Activity />}
          {page === "team" && <Team />}
          {page === "settings" && <Settings />}
          {page === "walkthrough" && <Walkthrough />}
          </PageError>
          <footer className="app-footer small muted">
            <a href="#/help">Help</a> · <a href="#/privacy">Privacy</a> · <a href="#/terms">Terms</a> · <a href="#/security">Security</a> · <a href="#/changelog">Changelog</a>
            <div><VersionLine /></div>
          </footer>
        </main>
      </div>
    </div>
  );
}

function Gate() {
  const { me, loading } = useAuth();
  const route = useRoute();
  if (route.page === "invite" && route.params.get("token")) return <AcceptInvite token={route.params.get("token")!} />;
  if (route.page === "reset" && route.params.get("token")) return <ResetPassword token={route.params.get("token")!} />;
  if (loading) return <div className="auth-page"><div className="skeleton" style={{ width: 240 }} aria-label="Loading" /></div>;
  if (route.page === "home") return <Landing />;
  if (route.page === "architecture") return <Architecture />;
  if (route.page === "privacy") return <Privacy />;
  if (route.page === "terms") return <Terms />;
  if (route.page === "security") return <Security />;
  if (route.page === "changelog") return <Changelog />;
  if (route.page === "help") return <Help topic={route.params.get("topic")} />;
  if (!me) {
    if (route.page === "signup") return <SignIn key="signup" initialMode="signup" />;
    if (route.page === "signin") return <SignIn key="signin" />;
    // Visitors without a session start on the product home page; deep links go to sign-in.
    return window.location.hash.replace(/^#\/?/, "") ? <SignIn /> : <Landing />;
  }
  if (!me.organization) return <NoOrganization />;
  return (
    <RefreshProvider key={me.organization.id}>
      <Shell me={me} />
    </RefreshProvider>
  );
}

export function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </ToastProvider>
  );
}
