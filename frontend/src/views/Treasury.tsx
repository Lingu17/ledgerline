import { useEffect, useState } from "react";
import { get, post, type Operation, type Wallet } from "../api";
import { Card, Empty, ErrorNote, Field, Loading, Modal, Money, Pill, useAction, useLoad } from "../components/ui";
import { useAuth } from "../auth";
import { parseMajor, plainAmount } from "../format";
import { money, when, day } from "../format";

interface Obligation { id: string; payee: string; currency: string; amount_minor: number; due_at: string; description: string; status: string }
interface ObPlan { deficit: number; source_currency: string | null; explanation: string; source_candidates: { currency: string; surplus: number; indicative_rate: string; surplus_in_target: number }[] }
interface QuotePreview {
  quote: { id: string; source: string; sell_currency: string; buy_currency: string; sell_amount_minor: number; buy_amount_minor: number; rate: string; obligation_id: string; valid_to: string; used_by_operation: string | null };
  expired: boolean; used: boolean; seconds_left: number;
  before: Record<string, number>; after: Record<string, number>;
  source_reserve: number; source_free_after: number; target_projected_after: number;
}
interface TreasuryData { wallets: Wallet[]; obligations: Obligation[]; plans: Record<string, ObPlan>; quotes: QuotePreview[]; conversions: Operation[]; rates: { sell: string; buy: string; rate: string }[]; rate_source: string }

export function Treasury({ localMode }: { localMode: boolean }) {
  const t = useLoad(() => get<TreasuryData>("/treasury"), []);
  const { run, busy } = useAction();
  const { can } = useAuth();
  const op = can("operator");
  const owner = can("owner");
  const [modal, setModal] = useState<"" | "obligation" | "opening">("");
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const i = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(i);
  }, []);
  if (t.error) return <ErrorNote error={t.error} onRetry={t.reload} />;
  if (!t.data) return <div className="card"><Loading rows={8} /></div>;
  const d = t.data;
  const liveQuote = d.quotes.find((q) => !q.used && new Date(q.quote.valid_to).getTime() > now);

  return (
    <div className="stack">
      <Card title="Wallet position" pad={false} actions={owner && localMode && <button className="btn small" onClick={() => setModal("opening")}>Set opening balance</button>}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Currency</th><th className="num">Settled cash</th><th className="num">Reserve</th><th className="num">Credits &amp; unapplied</th>
                <th className="num">Refunds reserved</th><th className="num">Bills in window</th><th className="num">FX out reserved</th>
                <th className="num">Free (settled)</th><th className="num">Pending FX in</th><th className="num">Forecast</th>
              </tr>
            </thead>
            <tbody>
              {d.wallets.map((w) => (
                <tr key={w.currency}>
                  <td><b>{w.currency}</b></td>
                  <td className="num">{money(w.cash, w.currency)}</td>
                  <td className="num">{money(w.reserve, w.currency)}</td>
                  <td className="num">{money(w.customer_credits + w.unapplied_held, w.currency)}</td>
                  <td className="num">{money(w.refunds_reserved, w.currency)}</td>
                  <td className="num">{money(w.obligations_due_in_window, w.currency)}</td>
                  <td className="num">{money(w.fx_out_reserved, w.currency)}</td>
                  <td className={`num ${w.free_after_commitments < 0 ? "neg" : ""}`}><b>{money(w.free_after_commitments, w.currency)}</b></td>
                  <td className="num muted">{money(w.fx_in_pending, w.currency)}</td>
                  <td className={`num ${w.projected_after_pending_fx < 0 ? "neg" : ""}`}>{money(w.projected_after_pending_fx, w.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card-body small muted">
          Free (settled) is what can be spent or sold. Pending FX in is forecast cover from conversions that have not settled; it is never spendable.
          No cross-currency total is shown.
        </div>
      </Card>

      <div className="split">
        <Card title="Obligations" pad={false} actions={op && <button className="btn small primary" onClick={() => setModal("obligation")}>Add obligation</button>}>
          {d.obligations.length === 0 && <Empty title="No upcoming obligations">Add supplier bills and payroll so Ledgerline can keep each currency covered.</Empty>}
          <div className="table-wrap">
          <table>
            <thead><tr><th>Payee</th><th>Due</th><th className="num">Amount</th><th>Coverage</th><th /></tr></thead>
            <tbody>
              {d.obligations.map((o) => {
                const p = d.plans[o.id];
                return (
                  <tr key={o.id}>
                    <td><div className="primary-text">{o.payee}</div><div className="secondary">{o.description}</div></td>
                    <td className="nowrap">{day(o.due_at)}</td>
                    <td className="num"><Money minor={o.amount_minor} ccy={o.currency} /></td>
                    <td className="small">
                      {p.deficit > 0 ? <><Pill status="escalated" label={`Short ${money(p.deficit, o.currency)}`} /><div className="secondary">{p.explanation}</div></>
                        : <Pill status="matched" label="Covered" />}
                    </td>
                    <td>
                      {op && p.deficit > 0 && p.source_currency && (
                        <button className="btn small" disabled={!!busy}
                          onClick={() => run("quote", () => post(`/treasury/obligations/${o.id}/quote`), "Quote received")}>
                          Quote {p.source_currency}→{o.currency}
                        </button>
                      )}
                      {p.deficit > 0 && !p.source_currency && <span className="small neg">No currency has surplus above reserve</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        </Card>

        <Card title="Conversion quote">
          {!liveQuote ? (
            <Empty title="No live quote">Request a quote for an obligation that is short. Quotes expire and can be used once.</Empty>
          ) : (
            <QuoteBox q={liveQuote} now={now} busy={busy} canConvert={op}
              onConvert={() => run("convert", () => post<Operation>(`/treasury/quotes/${liveQuote.quote.id}/execute`), (op) => `Conversion ${op.id}: ${op.status}`)} />
          )}
          <div className="small muted" style={{ marginTop: 12 }}>
            Rates: {localMode ? "fixed synthetic local-workspace rates" : "Airwallex sandbox quotes"} ·{" "}
            {d.rates.map((r) => `${r.sell}→${r.buy} ${r.rate}`).join(" · ")}
          </div>
        </Card>
      </div>

      <Card title="Conversions" pad={false}>
        {d.conversions.length === 0 ? <Empty title="No conversions yet" /> : (
          <div className="table-wrap">
          <table>
            <thead><tr><th>Operation</th><th>Status</th><th className="num">Sold</th><th className="num">Bought</th><th /></tr></thead>
            <tbody>
              {d.conversions.map((c) => {
                const det = typeof c.detail === "string" ? JSON.parse(c.detail) : c.detail;
                return (
                  <tr key={c.id}>
                    <td style={{ minWidth: 140 }}><div className="mono nowrap">{c.id}</div><div className="secondary">{when(c.created_at)}{c.needs_reconciliation ? " · outcome unknown, reservation held" : ""}</div></td>
                    <td><Pill status={c.status} /></td>
                    <td className="num"><Money minor={c.amount_minor} ccy={c.currency} /></td>
                    <td className="num"><Money minor={det.buy_amount_minor} ccy={det.buy_currency} /></td>
                    <td>{op && c.status === "processing" && <button className="btn small" disabled={!!busy} onClick={() => run("sync", () => post(`/operations/${c.id}/sync`), "Checked with provider")}>Check status</button>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        )}
      </Card>
      {modal === "obligation" && <ObligationForm onClose={() => setModal("")} />}
      {modal === "opening" && <OpeningForm onClose={() => setModal("")} />}
    </div>
  );
}

function ObligationForm({ onClose }: { onClose: () => void }) {
  const { run, busy } = useAction();
  const [f, setF] = useState({ payee: "", currency: "EUR", amount: "", due_date: "", description: "" });
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal title="Add an obligation" onClose={onClose}>
      <form noValidate onSubmit={async (e) => {
        e.preventDefault();
        if (f.payee.trim().length < 2) return setErr("Enter who is being paid.");
        if ((parseMajor(f.amount) ?? 0) <= 0) return setErr("Enter an amount greater than zero, like 9000.00.");
        if (!f.due_date) return setErr("Choose a due date.");
        setErr(null);
        if (await run("ob", () => post("/treasury/obligations", { ...f, amount: plainAmount(f.amount) }), "Obligation added")) onClose();
      }}>
        <div className="form-grid">
          <Field id="ob-payee" label="Payee" wide><input id="ob-payee" type="text" value={f.payee} onChange={set("payee")} /></Field>
          <Field id="ob-ccy" label="Currency"><select id="ob-ccy" value={f.currency} onChange={set("currency")}><option>USD</option><option>EUR</option><option>GBP</option></select></Field>
          <Field id="ob-amt" label="Amount"><input id="ob-amt" type="text" inputMode="decimal" value={f.amount} onChange={set("amount")} /></Field>
          <Field id="ob-due" label="Due date"><input id="ob-due" type="date" value={f.due_date} onChange={set("due_date")} /></Field>
          <Field id="ob-desc" label="Description"><input id="ob-desc" type="text" value={f.description} onChange={set("description")} /></Field>
        </div>
        {err && <div className="notice risk small" role="alert" style={{ marginTop: 12 }}>{err}</div>}
        <div className="form-actions"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!!busy}>Add obligation</button></div>
      </form>
    </Modal>
  );
}

function OpeningForm({ onClose }: { onClose: () => void }) {
  const { run, busy } = useAction();
  const [ccy, setCcy] = useState("USD");
  const [amount, setAmount] = useState("");
  return (
    <Modal title="Set an opening balance" onClose={onClose}>
      <form noValidate onSubmit={async (e) => {
        e.preventDefault();
        if (await run("open", () => post("/treasury/opening-balance", { currency: ccy, amount: plainAmount(amount) }), `${ccy} opening balance set`)) onClose();
      }}>
        <p className="small muted" style={{ marginTop: 0 }}>Once per currency, before any cash activity in it. Later corrections need an explicit journal adjustment.</p>
        <div className="form-grid">
          <Field id="op-ccy" label="Currency"><select id="op-ccy" value={ccy} onChange={(e) => setCcy(e.target.value)}><option>USD</option><option>EUR</option><option>GBP</option></select></Field>
          <Field id="op-amt" label="Balance"><input id="op-amt" type="text" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        </div>
        <div className="form-actions"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!!busy || (parseMajor(amount) ?? -1) < 0}>Set balance</button></div>
      </form>
    </Modal>
  );
}

function QuoteBox({ q, now, busy, onConvert, canConvert }: { q: QuotePreview; now: number; busy: string | null; onConvert: () => void; canConvert: boolean }) {
  const left = Math.max(0, Math.round((new Date(q.quote.valid_to).getTime() - now) / 1000));
  const s = q.quote.sell_currency;
  const b = q.quote.buy_currency;
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <div className="muted small">Buy exactly the shortfall</div>
          <div style={{ fontSize: 20, fontWeight: 600 }} className="num">{money(q.quote.buy_amount_minor, b)}</div>
          <div className="small">for {money(q.quote.sell_amount_minor, s)} at {q.quote.rate} {b}/{s}</div>
        </div>
        <Pill status={left > 10 ? "pending" : "escalated"} label={left > 0 ? `Expires in ${left}s` : "Expired"} />
      </div>
      <div className="table-wrap">
      <table>
        <thead><tr><th>Wallet</th><th className="num">Before</th><th className="num">After settlement</th></tr></thead>
        <tbody>
          <tr><td>{s}</td><td className="num">{money(q.before[s], s)}</td><td className="num">{money(q.after[s], s)}</td></tr>
          <tr><td>{b}</td><td className="num">{money(q.before[b], b)}</td><td className="num">{money(q.after[b], b)}</td></tr>
        </tbody>
      </table>
      </div>
      <dl className="kv small">
        <dt>{s} reserve kept</dt><dd>{money(q.source_reserve, s)}</dd>
        <dt>{s} free after</dt><dd className={q.source_free_after < 0 ? "neg" : ""}>{money(q.source_free_after, s)}</dd>
        <dt>{b} forecast after</dt><dd>{money(q.target_projected_after, b)}</dd>
        <dt>Quote</dt><dd className="mono">{q.quote.id} · single use</dd>
      </dl>
      {canConvert && (
        <button className="btn primary" disabled={!!busy || left === 0} onClick={onConvert}>
          {busy === "convert" ? "Converting…" : `Convert ${money(q.quote.sell_amount_minor, s)}`}
        </button>
      )}
      <div className="small muted">Cash moves in the ledger only when the provider reports the conversion SETTLED.</div>
    </div>
  );
}
