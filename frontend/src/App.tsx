import { useEffect, useRef, useState } from "react";
import { get, post, type Me, type Status } from "./api";
import { AuthProvider, ROLE_LABEL, useAuth } from "./auth";
import { Field, Modal, RefreshProvider, ToastProvider, useLoad, useToast } from "./components/ui";
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
import { AcceptInvite, NoOrganization, SignIn } from "./views/Auth";
import { Landing } from "./views/Landing";

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
  { id: "inbox", label: "Inbox", section: "Operations" },
  { id: "payments", label: "Payments" },
  { id: "approvals", label: "Approvals" },
  { id: "evidence", label: "Evidence" },
  { id: "treasury", label: "Treasury", section: "Money" },
  { id: "ledger", label: "Ledger" },
  { id: "customers", label: "Customers & invoices", section: "Records" },
  { id: "activity", label: "Activity" },
  { id: "team", label: "Team", section: "Organization" },
  { id: "settings", label: "Settings" },
  { id: "walkthrough", label: "Walkthrough", sampleOnly: true },
];

const TITLES: Record<string, [string, string]> = {
  inbox: ["Inbox", "Cash position and work that needs a decision"],
  payments: ["Payments", "Received funds, how each was matched, and what is left"],
  approvals: ["Approvals", "Money-out decisions bound to an exact scope"],
  evidence: ["Evidence", "Payer answers, the three checks, and how plans changed"],
  treasury: ["Treasury", "Reserves, upcoming obligations and conversions"],
  ledger: ["Ledger", "Per-currency conservation and the journal"],
  customers: ["Customers & invoices", "Who pays, what they owe, and their credits"],
  activity: ["Activity", "Audit trail of every decision and operation"],
  team: ["Team", "Members, roles and invitations"],
  settings: ["Settings", "Organization, integrations, controls and policy"],
  walkthrough: ["Walkthrough", "Optional guided run of the reference scenario"],
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
        <small>{org.kind === "sample" ? "Sample organization" : "Organization"} · {ROLE_LABEL[org.role]}</small>
      </button>
      {open && (
        <div className="menu" role="menu" onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
          <div className="menu-label">Switch organization</div>
          {me.organizations.map((o) => (
            <button key={o.id} role="menuitemradio" aria-checked={o.id === org.id} className="menu-item"
              onClick={() => { setOpen(false); if (o.id !== org.id) switchOrg(o.id).catch((e) => toast(e.message, "error")); }}>
              <span>{o.name}</span><small>{ROLE_LABEL[o.role]}{o.kind === "sample" ? " · sample" : ""}</small>
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
              setErr((ex as Error).message);
            }
          }}>
            <div className="stack" style={{ gap: 12 }}>
              <Field id="no-name" label="Name"><input id="no-name" type="text" value={name} onChange={(e) => setName(e.target.value)} /></Field>
              <fieldset className="choice">
                <legend>Start with</legend>
                <label><input type="radio" name="ns" checked={start === "empty"} onChange={() => setStart("empty")} /><span><b>Empty workspace</b></span></label>
                <label><input type="radio" name="ns" checked={start === "sample"} onChange={() => setStart("sample")} /><span><b>Sample data</b><small>Synthetic customers and six payments; includes the walkthrough.</small></span></label>
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
  useEffect(() => setMenuOpen(false), [route.page]);
  const status = useLoad(() => get<Status>("/status"), [me.organization?.id]);
  const counts = useLoad(() => get<{ work_queue: { kind: string }[]; deposit_counts: Record<string, number> }>("/overview"), [me.organization?.id]);
  const pendingApprovals = counts.data?.work_queue.filter((w) => w.kind === "approval").length ?? 0;
  const needsReview = counts.data?.deposit_counts?.escalated ?? 0;
  const page = TITLES[route.page] ? route.page : "inbox";
  const [title, sub] = TITLES[page];
  const s = status.data;
  const localMode = s?.bank.mode === "local";
  const isSample = me.organization?.kind === "sample";

  useEffect(() => {
    document.title = `${title} · ${me.organization?.name ?? "Ledgerline"}`;
  }, [title, me.organization?.name]);

  return (
    <div className="shell">
      <aside className={`sidebar ${menuOpen ? "open" : ""}`} aria-label="Main navigation">
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
            {s?.paused && (
              <a className="badge paused" href="#/settings" title={s.pause_info?.reason || "Money-out paused"}><b>Money-out paused</b></a>
            )}
            {me.role === "viewer" && <span className="badge" title="You can view and export, but not change anything"><b>Read-only</b></span>}
            {s && (
              <a className="badge" href="#/settings" title={s.bank.label}>
                <b>{localMode ? "Local workspace" : "Sandbox"}</b>
                <span className="hide-sm">{localMode ? "simulated bank" : "Airwallex test"}</span>
              </a>
            )}
          </div>
        </header>
        <main className="content" id="main">
          {page === "inbox" && <Inbox />}
          {page === "payments" && <Payments route={route} />}
          {page === "approvals" && <Approvals localMode={localMode} sandboxMode={s?.bank.mode === "airwallex_sandbox"} />}
          {page === "evidence" && <EvidenceView route={route} />}
          {page === "treasury" && <Treasury localMode={localMode} />}
          {page === "ledger" && <Ledger />}
          {page === "customers" && <Customers route={route} />}
          {page === "activity" && <Activity />}
          {page === "team" && <Team />}
          {page === "settings" && <Settings />}
          {page === "walkthrough" && <Walkthrough />}
        </main>
      </div>
    </div>
  );
}

function Gate() {
  const { me, loading } = useAuth();
  const route = useRoute();
  if (route.page === "invite" && route.params.get("token")) return <AcceptInvite token={route.params.get("token")!} />;
  if (loading) return <div className="auth-page"><div className="skeleton" style={{ width: 240 }} aria-label="Loading" /></div>;
  if (route.page === "home") return <Landing />;
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
