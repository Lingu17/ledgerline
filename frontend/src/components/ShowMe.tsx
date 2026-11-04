import { useEffect, useState } from "react";
import { get, post } from "../api";
import { go } from "../App";

interface DemoState { next: string | null; blocked: string | null; steps: { id: string; done: boolean }[] }

/** Run the practice steps in order until `target` is done. Never resets, and stops at anything waiting for a person. */
async function runUntil(target: string) {
  for (let i = 0; i < 8; i++) {
    const s = await get<DemoState>("/demo");
    if (s.steps.find((x) => x.id === target)?.done || !s.next || s.next === "seed" || s.blocked) return;
    await post("/demo/step", { step: s.next });
  }
}

interface Stop { page: string; params?: Record<string, string>; title: string; text: string; prepare?: () => Promise<unknown> }

const STOPS: Stop[] = [
  { page: "inbox", title: "A practice company", text: "Made-up customers and invoices in USD, EUR and GBP. Nothing here touches a real bank. Six payments are about to arrive." },
  { page: "payments", title: "Six payments arrive", prepare: () => runUntil("deposits"),
    text: "Rules in code made the first plan for each. Clean matches closed at once, a small bank fee was written off within tolerance, and the unclear ones are waiting." },
  { page: "payments", params: { deposit: "DEP-1005" }, title: "A suspected duplicate",
    prepare: async () => {
      const d = await get<{ status: string }>("/deposits/DEP-1005");
      if (d.status === "awaiting_evidence") await post("/deposits/DEP-1005/ask-agent");
    },
    text: "DEP-1005 looked like a second payment of a paid invoice, so the rules proposed a refund. Ledgerline asked the payer's agent; its signed answer says it is an advance, all three checks passed, and the refund was dropped before any money moved. Press Replay this decision in the history to re-run the rules on the stored inputs." },
  { page: "evidence", title: "Every answer is checked", prepare: () => runUntil("agents"),
    text: "Each answer shows its three checks: who signed it, that it names this payment and is fresh, and that our records agree. DEP-1004's agent named another customer's invoice, so it failed and went to a person with the reason." },
  { page: "approvals", title: "Two people for money out",
    text: "DEP-1006 really was paid twice. The refund is above the limit, so one person approves the exact amount and destination, and a different person sends it. In a practice company the labelled practice teammate can be that second person." },
  { page: "activity", title: "A log that shows tampering",
    text: "Every decision is in a hash-chained log. Use Try to tamper to change one recorded amount the way an insider could, and watch the chain catch that exact row. Then restore it." },
  { page: "ledger", title: "Every cent accounted for",
    text: "Per currency: received = applied + customer credit + refunded + still unapplied. Finish the remaining practice steps, including the send, from Practice steps." },
];

/** A short guided tour of a practice company. It runs only practice steps, and never approves or sends money. */
export function ShowMe({ onClose }: { onClose: () => void }) {
  const [i, setI] = useState(0);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const stop = STOPS[i];
  useEffect(() => {
    let live = true;
    (async () => {
      setNote(null);
      if (stop.prepare) {
        setBusy(true);
        try {
          await stop.prepare();
        } catch (e) {
          if (live) setNote((e as Error).message);
        } finally {
          if (live) setBusy(false);
        }
      }
      if (live) go(stop.page, stop.params);
    })();
    return () => { live = false; };
  }, [i]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <section className="showme" role="region" aria-label="Show me tour" aria-live="polite">
      <div className="row" style={{ justifyContent: "space-between", gap: 8 }}>
        <b>{stop.title}</b>
        <span className="muted small">{i + 1} of {STOPS.length}</span>
      </div>
      <p className="small" style={{ margin: "6px 0 10px" }}>{busy ? "Working…" : stop.text}</p>
      {note && <p className="small neg" style={{ margin: "0 0 8px" }}>{note}</p>}
      <div className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
        <button className="btn small ghost" onClick={onClose}>Close</button>
        {i > 0 && <button className="btn small" disabled={busy} onClick={() => setI(i - 1)}>Back</button>}
        {i < STOPS.length - 1
          ? <button className="btn small primary" disabled={busy} onClick={() => setI(i + 1)}>Next</button>
          : <button className="btn small primary" onClick={() => { onClose(); go("walkthrough"); }}>Practice steps</button>}
      </div>
    </section>
  );
}
