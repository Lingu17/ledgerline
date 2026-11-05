import { useEffect, useState } from "react";
import { get, post } from "../api";
import { go } from "../App";
import { type AgentStory, loadStory, storyLines } from "../agentStory";

interface DemoState { next: string | null; blocked: string | null; steps: { id: string; done: boolean }[] }

/** Run the practice steps in order until `target` is done. Never resets, and stops at anything waiting for a person. */
async function runUntil(target: string) {
  for (let i = 0; i < 8; i++) {
    const s = await get<DemoState>("/demo");
    if (s.steps.find((x) => x.id === target)?.done || !s.next || s.next === "seed" || s.blocked) return;
    await post("/demo/step", { step: s.next });
  }
}

interface Stop { page: string; params?: Record<string, string>; title: string; text: string; prepare?: () => Promise<unknown>; talk?: string }

const STOPS: Stop[] = [
  { page: "inbox", title: "A practice company", text: "Made-up customers and invoices in USD, EUR and GBP. Nothing here touches a real bank. Six payments have just arrived." },
  { page: "payments", title: "Six payments arrived", prepare: () => runUntil("deposits"),
    text: "Rules in code made the first plan for each. Clean matches closed at once, a small bank fee was written off within tolerance, and the unclear ones are waiting." },
  { page: "payments", params: { deposit: "DEP-1005" }, title: "A suspected duplicate",
    prepare: async () => {
      const d = await get<{ status: string }>("/deposits/DEP-1005");
      if (d.status === "awaiting_evidence") await post("/deposits/DEP-1005/ask-agent");
    },
    talk: "DEP-1005",
    text: "DEP-1005 looked like a second payment of a paid invoice, so the rules proposed a refund. Ledgerline asked the payer's agent; its signed answer says it is an advance, all three checks passed, and the refund was dropped before any money moved. Press Replay this decision in the history to re-run the rules on the stored inputs." },
  { page: "evidence", title: "Every answer is checked", prepare: () => runUntil("agents"), talk: "DEP-1004",
    text: "Each answer shows its three checks: who signed it, that it names this payment and is fresh, and that our records agree. DEP-1004's agent named another customer's invoice, so it failed and went to a person with the reason." },
  { page: "approvals", title: "Two people for money out",
    text: "DEP-1006 really was paid twice. The refund is above the limit, so one person approves the exact amount and destination, and a different person sends it. In a practice company the labelled practice teammate can be that second person." },
  { page: "activity", title: "A log that shows tampering",
    text: "Every decision is in a hash-chained log. Use Try to tamper to change one recorded amount the way an insider could, and watch the chain catch that exact row. Then restore it." },
  { page: "ledger", title: "Every cent accounted for",
    text: "Per currency: received = applied + customer credit + refunded + still unapplied. Finish the remaining practice steps, including the send, from Practice steps." },
];

// Narration reads the captions aloud with the browser's own speech (no network, no keys). It starts only when the person
// presses Play. On the two payer-agent stops it becomes the conversation the two agents had, read from this company's data.
const speech: SpeechSynthesis | null = typeof window !== "undefined" && "speechSynthesis" in window && "SpeechSynthesisUtterance" in window
  ? window.speechSynthesis : null;

function voices(): { ledgerline: SpeechSynthesisVoice | null; payer: SpeechSynthesisVoice | null } {
  const en = (speech?.getVoices() ?? []).filter((v) => v.lang?.toLowerCase().startsWith("en"));
  return { ledgerline: en[0] ?? null, payer: en.find((v) => v !== en[0]) ?? null };
}

/** Say the lines one after another; onLine(i) fires as each starts. Returns a stop function. */
function sayLines(lines: { who: "ledgerline" | "payer" | "caption"; name?: string; text: string }[], onLine: (i: number) => void): void {
  if (!speech) return;
  speech.cancel();
  const v = voices();
  lines.forEach((line, i) => {
    const voice = line.who === "payer" ? v.payer : v.ledgerline;
    // With one voice only, the speaker is named so the two sides stay clear.
    const spoken = line.who !== "caption" && !v.payer ? `${line.name}: ${line.text}` : line.text;
    const u = new SpeechSynthesisUtterance(spoken);
    if (voice) u.voice = voice;
    u.lang = voice?.lang ?? "en-GB";
    u.onstart = () => onLine(i);
    speech.speak(u);
  });
}

/** A short guided tour of a practice company. It runs only practice steps, and never approves or sends money. */
export function ShowMe({ onClose }: { onClose: () => void }) {
  const [i, setI] = useState(0);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [narrate, setNarrate] = useState(false);
  const [paused, setPaused] = useState(false);
  const [ready, setReady] = useState(-1);  // the stop whose preparation has finished
  const [story, setStory] = useState<AgentStory | null>(null);
  const [line, setLine] = useState(-1);
  const stop = STOPS[i];
  const lines = story ? storyLines(story) : [];
  const names = { ledgerline: "Ledgerline's agent", payer: `${story?.payer ?? "The payer"}'s agent (simulated)` };
  // The conversation is read from the payment once the stop is ready (the agent has answered by then).
  useEffect(() => {
    let live = true;
    setStory(null);
    setLine(-1);
    if (ready === i && stop.talk) loadStory(stop.talk).then((s) => { if (live) setStory(s); }).catch(() => {});
    return () => { live = false; };
  }, [ready, i]); // eslint-disable-line react-hooks/exhaustive-deps
  // Read each stop once it is ready; stop talking on the next stop, on close and when the page goes away.
  useEffect(() => {
    if (!narrate || ready !== i || (stop.talk && !story)) return;
    setPaused(false);
    if (stop.talk && story && lines.length) {
      sayLines(lines.map((l) => ({ ...l, name: names[l.who] })), setLine);
    } else {
      sayLines([{ who: "caption", text: `${stop.title}. ${stop.text}` }], () => {});
    }
    return () => speech?.cancel();
  }, [i, narrate, ready, story]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const quiet = () => speech?.cancel();
    window.addEventListener("pagehide", quiet);
    return () => { window.removeEventListener("pagehide", quiet); quiet(); };
  }, []);
  useEffect(() => {  // leave room under the page and the drawer for this panel, and keep toasts off it
    document.body.classList.add("tour-open");
    return () => document.body.classList.remove("tour-open");
  }, []);
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
      if (live) {
        go(stop.page, stop.params);
        setReady(i);
      }
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
      {stop.talk && story && lines.length > 0 && (
        <div className="agent-chat" aria-label="The two agents' conversation">
          <div className="muted small">Simulated payer agent: real signatures and checks</div>
          {lines.map((l, n) => (
            <div key={n} className={`bubble ${l.who}${narrate && n > line ? " later" : ""}${narrate && n === line ? " now" : ""}`}>
              <span className="who">{names[l.who]}</span>
              <span>{l.text}</span>
            </div>
          ))}
        </div>
      )}
      <div className="row" style={{ gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
        {speech && (!narrate
          ? <button className="btn small" onClick={() => setNarrate(true)}>Hear the two agents talk</button>
          : <>
              <button className="btn small" onClick={() => { if (paused) { speech.resume(); setPaused(false); } else { speech.pause(); setPaused(true); } }}>
                {paused ? "Resume" : "Pause"}
              </button>
              <button className="btn small" onClick={() => { speech.cancel(); setNarrate(false); setPaused(false); }}>Stop narration</button>
            </>)}
        <button className="btn small ghost" onClick={() => { speech?.cancel(); onClose(); }}>Close</button>
        {i > 0 && <button className="btn small" disabled={busy} onClick={() => setI(i - 1)}>Back</button>}
        {i < STOPS.length - 1
          ? <button className="btn small primary" disabled={busy} onClick={() => setI(i + 1)}>Next</button>
          : <button className="btn small primary" onClick={() => { speech?.cancel(); onClose(); go("walkthrough"); }}>Practice steps</button>}
      </div>
    </section>
  );
}
