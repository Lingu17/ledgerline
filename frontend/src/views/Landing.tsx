import { useEffect } from "react";
import { useAuth } from "../auth";
import { Globe } from "../components/Globe";
import "../landing.css";

function Logo() {
  return (
    <a className="lp-logo" href="#/home" aria-label="Ledgerline home">
      <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
        <rect width="32" height="32" rx="7" fill="#16263d" stroke="#2b4466" />
        <path d="M9 8v16h14" stroke="#5EC4B6" strokeWidth="3" fill="none" />
        <path d="M14 18h9" stroke="#fff" strokeWidth="3" />
      </svg>
      <span>Ledgerline</span>
    </a>
  );
}

const STEPS = [
  {
    n: "01", title: "Receive",
    body: "Incoming bank credits arrive by signed webhook, CSV statement import or manual entry. Each one is stored once, in integer minor units, with its remitter and reference.",
  },
  {
    n: "02", title: "Match",
    body: "Ledgerline matches the payment to the customer and their open invoices: exact, partial, overpaid, duplicate, short-paid by bank fees or from an unknown payer.",
  },
  {
    n: "03", title: "Verify",
    body: "When the case is ambiguous, it asks the payer's own agent over MCP. The answer comes back as Ed25519-signed evidence and is checked against your records before it counts.",
  },
  {
    n: "04", title: "Act",
    body: "Allocate, hold as credit, request the balance or return the money. Anything that moves money out needs an approval bound to the exact amount and destination.",
  },
];

const FEATURES = [
  { icon: "inbox", title: "Operational inbox", body: "One queue of payments that need a decision, oldest first. Everything else is posted and out of the way." },
  { icon: "split", title: "Partial and overpayments", body: "A 970 payment against a 1,000 invoice stays partial with 30 due. Fees within your tolerance close the invoice; anything more stays open with the exact balance requested." },
  { icon: "shield", title: "Signed payer evidence", body: "Three checks on every claim: signature, freshness and binding to this payment, and agreement with your own invoices." },
  { icon: "approve", title: "Four-eyes approvals", body: "Refunds above your limit need a second person, and the proposer can never approve. An approval is a hash of deposit, amount, currency and destination; if anything changes, it is void." },
  { icon: "fx", title: "Treasury and FX", body: "Wallet positions by currency, committed versus free cash, upcoming obligations and conversions that only post when settled." },
  { icon: "ledger", title: "Double-entry ledger", body: "Every movement is a balanced journal. Per-currency conservation checks run on every read of the ledger." },
  { icon: "audit", title: "Complete audit trail", body: "Who did what, when and why, searchable and exportable. Money history is never edited: changes are adjustments." },
  { icon: "team", title: "Organizations and roles", body: "Owners, operators and read-only viewers, with each organization's data kept in its own database." },
];

const ICONS: Record<string, React.ReactNode> = {
  inbox: <path d="M3 13h5l2 3h4l2-3h5M5 5h14l2 8v6H3v-6z" />,
  split: <path d="M4 12h6l4-6h6M14 18h6M10 12l4 6" />,
  shield: <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM8.5 12l2.5 2.5 4.5-5" />,
  approve: <path d="M8 11V6a2 2 0 014 0v4M12 10V5a2 2 0 014 0v7M4 13l4 7h9l3-8" />,
  fx: <path d="M4 8h13l-3-3M20 16H7l3 3" />,
  ledger: <path d="M5 4h14v16H5zM9 4v16M12 9h4M12 13h4" />,
  audit: <path d="M12 7v5l3 2M21 12a9 9 0 11-3-6.7M21 4v4h-4" />,
  team: <path d="M9 11a3 3 0 100-6 3 3 0 000 6zM3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M16 5a3 3 0 010 6M18 14c2 .6 3 2.6 3 6" />,
};

function Icon({ name }: { name: string }) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}

const CASES = [
  ["Exact", "Posted to the invoice"],
  ["Partial", "Invoice stays open, balance due"],
  ["Overpaid", "Excess held as customer credit"],
  ["Duplicate", "Refund proposed, needs approval"],
  ["Bank fee", "Closed within your tolerance"],
  ["Unknown payer", "Escalated with evidence request"],
];

const FAQ = [
  ["Is this a bank?", "No. Ledgerline sits beside your business account. It reads incoming payments and, when you approve, asks the account provider to return funds. In a local workspace the bank is simulated and every figure is synthetic."],
  ["Which banking provider does it use?", "New workspaces use a built-in simulated bank so you can try every flow safely. The Airwallex sandbox adapter is available when a server administrator configures sandbox API credentials. The current status is always shown in the top bar and under Settings → Integrations."],
  ["Where does AI come in?", "The payer side is an agent reached over the Model Context Protocol, and its answers are only accepted as signed, verified evidence. Claude can optionally read free-text remittance advice; its output is advisory and is checked against your invoices before anyone acts on it."],
  ["Can an AI move money on its own?", "Claude cannot: its output is advisory and never authorises anything. A payer agent's signed claim counts only after all three checks pass. Even then, a refund above your auto-limit needs a person other than the proposer, returns proposed by an operator always do, and small refunds auto-approve only on verified evidence within the limit you set. Operators can pause all money-out at any time; only an owner can resume."],
  ["How is data separated between companies?", "Each organization has its own database, simulated bank and signing keys. Every request is resolved from the signed-in session to a membership before any data is opened."],
  ["What does it cost?", "Nothing. Ledgerline is a hackathon project for the Airwallex Agentic Banking Hackathon and has no billing. It is not production banking software."],
];

export function Landing() {
  const { me } = useAuth();
  const signedIn = !!me;

  useEffect(() => {
    document.title = "Ledgerline — reconcile every incoming payment, with proof";
    window.scrollTo(0, 0);
  }, []);

  // Section links (#how, #faq) scroll in place instead of changing the hash route.
  const onClick = (e: React.MouseEvent) => {
    const a = (e.target as HTMLElement).closest("a");
    const href = a?.getAttribute("href") || "";
    if (href.startsWith("#") && !href.startsWith("#/")) {
      e.preventDefault();
      document.getElementById(href.slice(1))?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  const primary = signedIn
    ? { href: "#/inbox", label: "Open your workspace" }
    : { href: "#/signup", label: "Create an organization" };

  return (
    <div className="lp" onClick={onClick}>
      <header className="lp-nav">
        <div className="lp-wrap lp-nav-row">
          <Logo />
          <nav className="lp-links" aria-label="Product">
            <a href="#how">How it works</a>
            <a href="#features">Features</a>
            <a href="#safety">Safety</a>
            <a href="#faq">FAQ</a>
            <a href="#/architecture">Architecture</a>
          </nav>
          <div className="lp-nav-cta">
            {!signedIn && <a className="lp-btn ghost" href="#/signin">Sign in</a>}
            <a className="lp-btn primary" href={primary.href}>{signedIn ? "Open workspace" : "Get started"}</a>
          </div>
        </div>
      </header>

      <section className="lp-hero">
        <Globe className="lp-globe" />
        <div className="lp-wrap lp-hero-grid">
          <div className="lp-hero-copy">
            <span className="lp-eyebrow">Receivables reconciliation for multi-currency businesses</span>
            <h1>Every incoming payment, matched and settled with proof.</h1>
            <p className="lp-lead">
              Ledgerline reconciles the money your customers send against the invoices they owe, asks the payer's agent when
              something does not add up, and keeps a person in control of money leaving above the limit you set.
            </p>
            <div className="lp-hero-cta">
              <a className="lp-btn primary lg" href={primary.href}>{primary.label}</a>
              <a className="lp-btn outline lg" href="#how">See how it works</a>
            </div>
            <p className="lp-fineprint">Free to try with a sample company. Synthetic data and a simulated bank by default.</p>
          </div>

          <div className="lp-stage" aria-hidden="true">
            <div className="lp-card3d">
              <div className="lp-mock-head">
                <span className="dot" /><span className="dot" /><span className="dot" />
                <b>Inbox</b><span className="lp-mock-pill">3 need a decision</span>
              </div>
              <div className="lp-mock-row">
                <div><b>Fjord Logistikk AS</b><small>EUR 1,750.00 · no reference</small></div>
                <span className="lp-tag warn">Ask payer</span>
              </div>
              <div className="lp-mock-row">
                <div><b>Calder and Finch Ltd</b><small>GBP 2,400.00 · part payment</small></div>
                <span className="lp-tag">Partial · balance due</span>
              </div>
              <div className="lp-mock-row">
                <div><b>Dunmore Analytics LLC</b><small>USD 1,200.00 · invoice already paid</small></div>
                <span className="lp-tag risk">Refund · approval</span>
              </div>
              <div className="lp-mock-evidence">
                <span className="lp-check">✓</span> Signature <span className="lp-check">✓</span> Fresh &amp; bound <span className="lp-check">✓</span> Matches records
              </div>
            </div>
            <div className="lp-float lp-float-a"><small>Ledger</small><b>Balanced</b><span>GBP · EUR · USD</span></div>
            <div className="lp-float lp-float-b"><small>Approval</small><b>Four-eyes</b><span>Scope-bound</span></div>
          </div>
        </div>
      </section>

      <section className="lp-cases" aria-label="Payment cases handled">
        <div className="lp-wrap">
          <p className="lp-cases-title">Six things that happen to real receivables, each handled differently</p>
          <ul className="lp-case-grid">
            {CASES.map(([k, v]) => <li key={k}><b>{k}</b><span>{v}</span></li>)}
          </ul>
        </div>
      </section>

      <section id="how" className="lp-section">
        <div className="lp-wrap">
          <div className="lp-head">
            <span className="lp-eyebrow dark">How it works</span>
            <h2>From bank credit to closed invoice in four steps</h2>
            <p>Automation handles the clear cases. Anything uncertain becomes a decision with evidence attached.</p>
          </div>
          <ol className="lp-steps">
            {STEPS.map((s) => (
              <li key={s.n}>
                <span className="lp-step-n">{s.n}</span>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="features" className="lp-section alt">
        <div className="lp-wrap">
          <div className="lp-head">
            <span className="lp-eyebrow dark">Features</span>
            <h2>Everything a finance operations team needs for incoming cash</h2>
          </div>
          <div className="lp-features">
            {FEATURES.map((f) => (
              <article key={f.title} className="lp-feature">
                <span className="lp-icon"><Icon name={f.icon} /></span>
                <h3>{f.title}</h3>
                <p>{f.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="safety" className="lp-section dark">
        <div className="lp-wrap lp-safety">
          <div>
            <span className="lp-eyebrow">Safety by design</span>
            <h2>Agents can propose. Code verifies. People approve what is above your limit.</h2>
            <p>
              Ledgerline treats every answer from an AI or a payer as data to be checked, never as an instruction. The controls
              that protect money-out are enforced by the server, not just hidden in the interface.
            </p>
          </div>
          <ul className="lp-safety-list">
            <li><b>Approval bound to scope</b><span>Changing the amount, currency, destination or evidence voids the approval.</span></li>
            <li><b>One live refund per deposit</b><span>Enforced by a database constraint, with idempotent provider requests.</span></li>
            <li><b>Uncertain is not final</b><span>Ambiguous provider results stay pending until looked up; a sent refund is not yet a settled one.</span></li>
            <li><b>Pause switch</b><span>Operators can stop all money-out instantly; only an owner can resume it.</span></li>
            <li><b>Secure sessions</b><span>scrypt passwords, HttpOnly cookies, CSRF checks, expiry and sign-in throttling.</span></li>
          </ul>
        </div>
      </section>

      <section className="lp-section">
        <div className="lp-wrap">
          <div className="lp-head">
            <span className="lp-eyebrow dark">Built for teams</span>
            <h2>The right access for everyone who touches cash</h2>
          </div>
          <div className="lp-roles">
            <article><h3>Owner</h3><p>Sets policy and tolerances, manages the team and integrations, records opening balances and resumes money-out.</p></article>
            <article><h3>Operator</h3><p>Works the inbox: records and imports payments, resolves cases, asks payers and approves other people's proposals.</p></article>
            <article><h3>Viewer</h3><p>Reads everything and exports the audit trail. Ideal for auditors and accountants. Cannot change anything.</p></article>
          </div>
        </div>
      </section>

      <section className="lp-section alt">
        <div className="lp-wrap">
          <div className="lp-head">
            <span className="lp-eyebrow dark">Integrations</span>
            <h2>Clear about what is connected</h2>
            <p>Every screen shows which bank you are working against. Nothing is labelled live unless it has been checked.</p>
          </div>
          <div className="lp-integrations">
            <article><span className="lp-tag">Default</span><h3>Simulated bank</h3><p>A local bank with synthetic accounts, webhooks, FX and refunds, including failures and delays, for safe practice.</p></article>
            <article><span className="lp-tag warn">Sandbox</span><h3>Airwallex</h3><p>Verified in the sandbox: signed deposit webhooks, current FX rates, beneficiaries, conversions and an approved refund from SENT to PAID. Reserved for the operator's organization, so sample workspaces never touch it.</p></article>
            <article><span className="lp-tag">Optional</span><h3>Claude</h3><p>Reads free-text remittance advice into structured suggestions. Advisory only, and verified against your invoices.</p></article>
            <article><span className="lp-tag">Protocol</span><h3>MCP payer agents</h3><p>Payers answer questions about their payments through the Model Context Protocol with signed responses.</p></article>
          </div>
        </div>
      </section>

      <section id="faq" className="lp-section">
        <div className="lp-wrap lp-faq-wrap">
          <div className="lp-head">
            <span className="lp-eyebrow dark">FAQ</span>
            <h2>Questions finance teams ask</h2>
          </div>
          <div className="lp-faq">
            {FAQ.map(([q, a]) => (
              <details key={q}>
                <summary>{q}</summary>
                <p>{a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-cta">
        <div className="lp-wrap lp-cta-row">
          <div>
            <h2>See it with a sample company in under a minute.</h2>
            <p>Six received payments, three currencies and every hard case, ready to work through.</p>
          </div>
          <a className="lp-btn primary lg" href={primary.href}>{primary.label}</a>
        </div>
      </section>

      <footer className="lp-footer">
        <div className="lp-wrap lp-footer-row">
          <Logo />
          <p>Built for the Airwallex Agentic Banking Hackathon. Not a bank and not production banking software. Local workspaces use synthetic data only.</p>
          <nav aria-label="Footer">
            <a href="#how">How it works</a>
            <a href="#faq">FAQ</a>
            <a href="#/architecture">Architecture</a>
            <a href={signedIn ? "#/inbox" : "#/signin"}>{signedIn ? "Workspace" : "Sign in"}</a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
