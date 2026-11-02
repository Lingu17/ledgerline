import { useState } from "react";
import { get } from "../api";
import { Card, ErrorNote, Loading, Pill, useLoad } from "../components/ui";
import { amountOnly, money, when } from "../format";

interface Cons {
  currency: string; deposits: number; allocated: number; customer_credits: number; refunds_paid: number; refunds_pending: number; unapplied: number; converted: number;
  opening_balance: number; fx_in: number; fx_out: number; refunds_cash_out: number; cash_in_transit: number; wallet_cash: number; bank_fee_writeoffs: number;
  balanced: boolean; checks: { name: string; passed: boolean; detail: string }[];
}
interface LedgerData {
  conservation: { currencies: Record<string, Cons>; all_balanced: boolean };
  per_deposit: { deposit_id: string; amount: number; allocated: number; credited: number; refund_paid: number; refund_pending: number; unapplied: number; ok: boolean }[];
  journal: { id: number; memo: string; ref_type: string; ref_id: string; at: string; lines: { account: string; currency: string; debit_minor: number; credit_minor: number }[] }[];
}

const CHECK_LABEL: Record<string, string> = {
  deposit_conservation: "Deposits fully accounted for",
  journal_trial_balance: "Journal debits equal credits",
  refund_liability: "Refund liability matches unpaid refunds",
  cash_walk: "Wallet cash walks from opening balance",
  no_negative_unapplied: "No negative unapplied balance",
};

export function Ledger() {
  const l = useLoad(() => get<LedgerData>("/ledger"), []);
  const [ccy, setCcy] = useState("");
  if (l.error) return <ErrorNote error={l.error} onRetry={l.reload} />;
  if (!l.data) return <div className="card"><Loading rows={8} /></div>;
  const cur = Object.values(l.data.conservation.currencies);
  const journal = l.data.journal.filter((e) => !ccy || e.lines.some((x) => x.currency === ccy));
  return (
    <div className="stack">
      {cur.map((c) => (
        <Card key={c.currency} title={<h2 className="row" style={{ gap: 8 }}>{c.currency} <Pill status={c.balanced ? "matched" : "escalated"} label={c.balanced ? "Balanced to the cent" : "Out of balance"} /></h2>}>
          <div className="equation" aria-label={`${c.currency} conservation`}>
            <span className="term"><span>Deposits</span>{amountOnly(c.deposits)}</span>
            <span className="op">=</span>
            <span className="term"><span>Applied</span>{amountOnly(c.allocated)}</span><span className="op">+</span>
            <span className="term"><span>Credits</span>{amountOnly(c.customer_credits)}</span><span className="op">+</span>
            <span className="term"><span>Refunds paid</span>{amountOnly(c.refunds_paid)}</span><span className="op">+</span>
            <span className="term"><span>Refunds pending</span>{amountOnly(c.refunds_pending)}</span><span className="op">+</span>
            <span className="term"><span>Not yet placed (journal)</span>{amountOnly(c.unapplied)}</span>
            {c.converted > 0 && <><span className="op">+</span><span className="term"><span>Converted for invoices</span>{amountOnly(c.converted)}</span></>}
          </div>
          <div className="grid-2" style={{ marginTop: 14 }}>
            <dl className="kv small">
              <dt>Opening wallet balance</dt><dd>{money(c.opening_balance, c.currency)}</dd>
              <dt>FX bought / sold</dt><dd>{money(c.fx_in, c.currency)} / {money(c.fx_out, c.currency)}</dd>
              <dt>Refund cash sent</dt><dd>{money(c.refunds_cash_out, c.currency)}{c.cash_in_transit ? ` (${money(c.cash_in_transit, c.currency)} in transit)` : ""}</dd>
              <dt>Wallet cash (journal)</dt><dd><b>{money(c.wallet_cash, c.currency)}</b></dd>
              <dt>Bank fees written off</dt><dd>{money(c.bank_fee_writeoffs, c.currency)} <span className="muted">(invoice side)</span></dd>
            </dl>
            <ul className="small" style={{ margin: 0, paddingLeft: 0, listStyle: "none" }}>
              {c.checks.map((k) => (
                <li key={k.name} style={{ marginBottom: 4 }}>
                  <span className={k.passed ? "" : "neg"} aria-hidden="true">{k.passed ? "✓" : "✕"}</span> {CHECK_LABEL[k.name] ?? k.name}
                  <span className="sr-only">{k.passed ? "passed" : "failed"}</span>
                  <div className="muted mono" style={{ fontSize: 11.5 }}>{k.detail}</div>
                </li>
              ))}
            </ul>
          </div>
        </Card>
      ))}

      <Card title="Per deposit" pad={false}>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Deposit</th><th className="num">Amount</th><th className="num">Applied</th><th className="num">Credit</th><th className="num">Refunded</th><th className="num">Refund pending</th><th className="num">Unapplied</th></tr></thead>
            <tbody>
              {l.data.per_deposit.map((p) => (
                <tr key={p.deposit_id}>
                  <td><a href={`#/payments?deposit=${p.deposit_id}`} className="mono">{p.deposit_id}</a></td>
                  {[p.amount, p.allocated, p.credited, p.refund_paid, p.refund_pending, p.unapplied].map((v, i) => <td className="num" key={i}>{amountOnly(v)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Journal" pad={false} actions={
        <select aria-label="Filter journal by currency" value={ccy} onChange={(e) => setCcy(e.target.value)}>
          <option value="">All currencies</option><option>USD</option><option>EUR</option><option>GBP</option>
        </select>}>
        <div className="table-wrap" style={{ maxHeight: 520, overflowY: "auto" }}>
          <table>
            <thead><tr><th>#</th><th>Entry</th><th>Account</th><th className="num">Debit</th><th className="num">Credit</th></tr></thead>
            <tbody>
              {journal.flatMap((e) =>
                e.lines.map((x, i) => (
                  <tr key={`${e.id}-${i}`}>
                    <td className="muted small">{i === 0 ? e.id : ""}</td>
                    <td className="small">{i === 0 ? <><div>{e.memo}</div><div className="secondary">{when(e.at)}</div></> : ""}</td>
                    <td className="mono small">{x.account}</td>
                    <td className="num">{x.debit_minor ? money(x.debit_minor, x.currency) : ""}</td>
                    <td className="num">{x.credit_minor ? money(x.credit_minor, x.currency) : ""}</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
