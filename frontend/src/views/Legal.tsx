import { useEffect, useState } from "react";
import "../landing.css";
import { Logo } from "./Landing";

const UPDATED = "4 November 2026";

/** Public pages (privacy, terms, security): readable signed in or out, plain words, nothing promised that the code does not do. */
export function DocPage({ title, children, updated = UPDATED, wide = false }: { title: string; children: React.ReactNode; updated?: string | null; wide?: boolean }) {
  useEffect(() => {
    document.title = `${title} · Ledgerline`;
    window.scrollTo(0, 0);
  }, [title]);
  return (
    <div className="lp doc-page">
      <header className="lp-nav">
        <div className="lp-wrap lp-nav-row">
          <Logo />
          <nav className="lp-links" aria-label="Pages">
            <a href="#/privacy">Privacy</a>
            <a href="#/terms">Terms</a>
            <a href="#/security">Security</a>
            <a href="#/changelog">Changelog</a>
            <a href="#/help">Help</a>
          </nav>
        </div>
      </header>
      <main className="lp-wrap doc-body" style={wide ? { maxWidth: 1200 } : undefined}>
        <h1>{title}</h1>
        {updated && <p className="doc-updated">Last updated {updated}</p>}
        {children}
      </main>
      <LegalFooter />
    </div>
  );
}

export interface PublicInfo { version: string; commit: string | null; security_contact: string | null }

let infoCache: Promise<PublicInfo | null> | null = null;

/** The version and commit the server runs, and its security contact. Fetched once per page load. */
export function usePublicInfo(): PublicInfo | null {
  const [info, setInfo] = useState<PublicInfo | null>(null);
  useEffect(() => {
    infoCache ??= fetch("/api/public/info").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    let live = true;
    infoCache.then((i) => live && setInfo(i));
    return () => { live = false; };
  }, []);
  return info;
}

export function VersionLine() {
  const info = usePublicInfo();
  if (!info) return null;
  return <span className="mono">Version {info.version}{info.commit ? ` · ${info.commit.slice(0, 7)}` : ""}</span>;
}

export function LegalFooter() {
  return (
    <footer className="lp-footer">
      <div className="lp-wrap lp-footer-row">
        <Logo />
        <p>Not a bank. Runs against the Airwallex test environment; no real money moves. <VersionLine /></p>
        <nav aria-label="Footer">
          <a href="#/privacy">Privacy</a>
          <a href="#/terms">Terms</a>
          <a href="#/security">Security</a>
          <a href="#/changelog">Changelog</a>
        </nav>
      </div>
    </footer>
  );
}

export function Privacy() {
  return (
    <DocPage title="Privacy">
      <p>
        Ledgerline is a product built for the Airwallex Agentic Banking Hackathon. It works only with Airwallex's test
        environment (the sandbox) or a simulated bank, and no real money moves. Please use made-up data: do not enter real
        customers' personal or financial details.
      </p>
      <h2>What is stored</h2>
      <ul>
        <li><b>Your account:</b> your name, email address, and a password hash (scrypt), or the identifier Google gives when you sign in with Google. The password itself is never stored.</li>
        <li><b>Sign-in records:</b> a hash of each session token with your browser's user agent and times. Failed sign-in attempts are counted by email and network address to enforce a 15-minute limit.</li>
        <li><b>Sign-up limit:</b> the network address that created an account or company is kept for 2 days to limit sign-ups, and appears in that company's change log.</li>
        <li><b>Your company's data:</b> what you or your bank connection put in: customers, invoices, payments, plans, approvals, bills, and the audit log of every decision. A connected Airwallex sandbox key is stored encrypted and never shown again.</li>
      </ul>
      <h2>Where it is kept</h2>
      <ul>
        <li>On one server in Google Cloud's Mumbai region (asia-south1). Each company's data is in its own database.</li>
        <li>Nightly copies on the same server; the newest 7 are kept.</li>
        <li>If the operator has turned on off-server backups, encrypted copies go to a private Google Cloud Storage bucket in Asia and are deleted after 30 days.</li>
      </ul>
      <h2>Who else receives data</h2>
      <ul>
        <li><b>Airwallex</b>, for a company that connects its sandbox account: what each payment, transfer or conversion needs.</li>
        <li><b>Anthropic (Claude)</b>, only in a real company and only when someone asks: the text of a remittance email or PDF you give it to read, or the structured facts of a plan you ask it to explain. Practice companies never call Claude.</li>
        <li><b>Google</b>, if you choose to sign in with Google.</li>
        <li><b>A customer's own payer agent</b>, if your company registered one: six fields about the payment being asked about, nothing else.</li>
      </ul>
      <p>There are no analytics, advertising or tracking cookies. The only cookie is the one that keeps you signed in.</p>
      <h2>How long, and how to delete</h2>
      <ul>
        <li>Company data is kept until an Owner deletes the company under <b>Settings → Leave or delete</b>. Deletion is immediate on the server; backup copies age out as described above.</li>
        <li>You can delete your own account in the same place once you no longer belong to any company. Your name, email, password and sign-in links are erased. A company's audit log keeps the email that took each action, because that log is hash-chained and cannot be edited.</li>
        <li>Forgot your password? The server sends no email, so an Owner of your company can give you a one-hour reset link from <b>Team</b>.</li>
      </ul>
      <h2>Questions</h2>
      <p>Use the contact on the <a href="#/security">Security</a> page.</p>
    </DocPage>
  );
}

export function Terms() {
  return (
    <DocPage title="Terms">
      <p>These terms are written in plain words. They are not legal advice.</p>
      <h2>What Ledgerline is</h2>
      <ul>
        <li>A product built for a hackathon, for trying out with Airwallex's test environment and made-up data. No real money moves.</li>
        <li>Not a bank or a payment institution, and not financial, legal or tax advice.</li>
        <li>Rules in code make the decisions. Claude's output is advice for a person and never moves money.</li>
      </ul>
      <h2>What we ask of you</h2>
      <ul>
        <li>Use test data only. Do not enter real customers' personal or financial details, or real bank credentials.</li>
        <li>Keep your password to yourself, and give team roles only to people you trust: approvals and sends are recorded under their names.</li>
        <li>Do not try to reach other people's companies, overload the service, or test it in ways that affect others. Report problems instead (see <a href="#/security">Security</a>).</li>
      </ul>
      <h2>Availability</h2>
      <ul>
        <li>It runs on one server with no uptime promise. It may change, pause or end, and its data may be deleted when it ends.</li>
        <li>It is provided as it is, without warranties, to the extent the law allows.</li>
      </ul>
      <h2>Changes</h2>
      <p>These terms may change; the date at the top shows the last change.</p>
    </DocPage>
  );
}

export function Security() {
  const contact = usePublicInfo()?.security_contact ?? null;
  const href = contact && (contact.startsWith("mailto:") || contact.startsWith("https://")) ? contact : null;
  return (
    <DocPage title="Security">
      <p>How Ledgerline protects accounts, money decisions and records, in plain words. Each item is enforced by the server, not only by the screen.</p>
      <h2>Accounts and sessions</h2>
      <ul>
        <li>Passwords are stored only as scrypt hashes and need 12 or more characters with upper- and lower-case letters and a digit.</li>
        <li>Five failed sign-ins for an email or a network address within 15 minutes means waiting before trying again.</li>
        <li>Sessions end after 2 hours idle or 12 hours at most. The cookie is HttpOnly, Secure and SameSite=Strict, and every change also needs a separate CSRF token.</li>
        <li>Each company's data is in its own database, reachable only through that company's members and roles.</li>
      </ul>
      <h2>Money out</h2>
      <ul>
        <li>Two people: whoever proposes a refund or bill payment cannot approve it, and when the agent proposed a refund, the person who approves it cannot also send it.</li>
        <li>An approval is bound to the exact amount, currency, destination and evidence. If any of them changes, the approval is void.</li>
        <li>An approval not sent in time (72 hours by default; an Owner can set 1 to 720) goes back to the approvers.</li>
        <li>One live refund per payment, with a stable request id, so a timeout cannot pay twice. Only PAID counts as done.</li>
        <li>A pause switch stops every payment out at once; matching keeps running.</li>
        <li>Optionally, the operator can move the Airwallex keys into a separate process that the app cannot read; the app then asks it to send by id only. A compromised app could still request a send that its own database says was approved.</li>
      </ul>
      <h2>Agents and AI</h2>
      <ul>
        <li>A payer agent's answer is a signed claim, used only if its signature, its freshness and binding to this payment, and your own records all check out.</li>
        <li>Claude reads documents and explains plans as advice. It cannot approve, send or change an amount. Instructions hidden in an email or a payer's name are treated as text; this is tested.</li>
      </ul>
      <h2>Records</h2>
      <ul>
        <li>Every decision is in an audit log where each entry's hash covers the previous one, so editing or removing an entry shows at that entry. A practice company can try this under Activity → Try to tamper.</li>
        <li>Any plan the rules made can be replayed on its stored inputs to show it gives the same plan.</li>
        <li>Off-server backups, when turned on, are encrypted before they leave the server.</li>
      </ul>
      <h2>The server</h2>
      <ul>
        <li>HTTPS only, with HSTS and a strict content security policy. Only the web and SSH ports are open.</li>
        <li>The app runs as its own unprivileged user with a restricted service sandbox. Dependencies are pinned by hash.</li>
      </ul>
      <h2>Reporting a problem</h2>
      <p>
        {href
          ? <>If you find a security problem, please report it privately: <a href={href}>{contact!.replace(/^mailto:/, "")}</a> (also in <a href="/.well-known/security.txt">security.txt</a>). </>
          : <>The operator of this server has not published a reporting address yet. </>}
        Use your own practice company to show a problem, and do not access other people's data or degrade the service.
      </p>
    </DocPage>
  );
}

/** The changelog from the server, rendered from its small Markdown subset: headings, bullets and inline code. */
export function Changelog() {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    fetch("/api/public/changelog").then((r) => (r.ok ? r.text() : "")).then(setText).catch(() => setText(""));
  }, []);
  return (
    <DocPage title="Changelog">
      {text === null ? <p>Loading…</p> : <Markdown text={text} />}
    </DocPage>
  );
}

function inline(t: string): React.ReactNode[] {
  return t.split(/(`[^`]+`)/g).map((part, i) => (part.startsWith("`") && part.endsWith("`") ? <code key={i}>{part.slice(1, -1)}</code> : part));
}

function Markdown({ text }: { text: string }) {
  const blocks: React.ReactNode[] = [];
  let items: string[] = [];
  let para: string[] = [];
  const flush = () => {
    if (items.length) blocks.push(<ul key={blocks.length}>{items.map((it, i) => <li key={i}>{inline(it)}</li>)}</ul>);
    if (para.length) blocks.push(<p key={blocks.length}>{inline(para.join(" "))}</p>);
    items = [];
    para = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    if (line.startsWith("# ")) continue;  // the page has its own title
    if (line.startsWith("## ")) { flush(); blocks.push(<h2 key={blocks.length}>{inline(line.slice(3))}</h2>); }
    else if (line.startsWith("- ")) { if (para.length) flush(); items.push(line.slice(2)); }
    else if (line.startsWith("  ") && items.length) items[items.length - 1] += " " + line.trim();
    else if (!line) flush();
    else para.push(line);
  }
  flush();
  return <>{blocks}</>;
}

const HELP: [string, string, string[]][] = [
  ["start", "Getting started", [
    "Choose Practice company to learn with made-up data, or My company to set up your own. A practice company has a Show me tour at the top right and Practice steps in the menu.",
    "For your own company: connect your Airwallex sandbox account in Settings, invite at least one more Operator under Team (money out needs a second person), then add customers, invoices and bills, or import them from CSV.",
  ]],
  ["inbox", "Inbox", ["Cash by currency and the payments that need a decision. Each item says its next step."]],
  ["ceo", "CEO view", ["The company on one screen: is cash safe, what happened, and what needs a person."]],
  ["payments", "Payments", [
    "Every payment received, how it was matched, and what is left. Clean matches settle by themselves; a bank fee within your tolerance is written off.",
    "For anything unclear, open the payment and use Ask payer's agent or Read remittance. A signed answer is used only if it passes three checks. Replay this decision re-runs the rules on the stored inputs.",
  ]],
  ["approvals", "Approvals", [
    "Refunds above your limit and every bill payment need a second person. The approval is bound to the exact amount and destination, and expires after 72 hours.",
    "If the agent proposed a refund, the person who approves it cannot also send it. SENT is not final; only PAID is.",
  ]],
  ["evidence", "Evidence", ["Every payer-agent answer and document reading, with its three checks and how the plan changed."]],
  ["treasury", "Treasury", [
    "What to pay first: each bill shows Fund, Convert, Defer or Escalate, with the reason. Convert buys only the shortfall above your reserve.",
    "Bring cash in early offers a capped discount through a hosted payment link. Plan history replays any earlier plan.",
  ]],
  ["ledger", "Ledger", ["Per currency: received equals applied plus customer credit plus refunded plus still unapplied, to the cent. Every movement is a balanced journal."]],
  ["customers", "Customers & invoices", ["Who pays you, under which names, what they owe and their credits. Import CSV with name, country, payer_names, refund_beneficiary."]],
  ["activity", "Activity", ["Every decision and money movement, searchable. Verify log integrity checks the hash chain; Download CSV files or the evidence JSON for your records."]],
  ["team", "Team", ["Invite people as Owner, Operator or Viewer. Nothing is emailed: send the link yourself. An Owner can create a one-hour reset link for a member who forgot their password."]],
  ["settings", "Settings", ["Pause all money-out, connect Airwallex, set policy limits, change your name or password, export, leave or delete."]],
  ["walkthrough", "Practice steps", ["The practice story step by step. Alone, the labelled practice teammate can send a refund you approved; it exists only in practice companies."]],
];

/** How to use each screen, in a few lines each. Every page's Help link opens its own section. */
export function Help({ topic }: { topic: string | null }) {
  useEffect(() => {
    if (topic) setTimeout(() => document.getElementById(`help-${topic}`)?.scrollIntoView({ block: "start" }), 50);
  }, [topic]);
  return (
    <DocPage title="Help">
      <p>
        Short answers for each screen. Back to <a href="#/inbox">your workspace</a>. In a practice company, the <b>Show me</b> button
        at the top right walks you through the whole story.
      </p>
      {HELP.map(([id, title, lines]) => (
        <section key={id} id={`help-${id}`} className={topic === id ? "help-current" : undefined}>
          <h2>{title}</h2>
          {lines.map((l, i) => <p key={i}>{l}</p>)}
        </section>
      ))}
      <h2>Still stuck?</h2>
      <p>See <a href="#/security">Security</a> for how to report a problem, and <a href="#/privacy">Privacy</a> for what is stored.</p>
    </DocPage>
  );
}
