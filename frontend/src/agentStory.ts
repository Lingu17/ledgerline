import { get } from "./api";
import { money, plainReason } from "./format";

/** The conversation between Ledgerline's agent and a payer's agent about one payment, built only from what Ledgerline
 *  stored: the question in its first plan, the signed answer, the three checks as recorded, and the plan it ended with.
 *  Nothing here is invented or decided; it is read back. */
export interface Check { name: string; label: string; passed: boolean; detail: string }
export interface AgentStory {
  deposit: string;
  amount: string;
  payer: string;
  question: string | null;
  answer: string | null;
  keyId: string | null;
  source: string | null;
  verdict: string | null;
  checks: Check[];
  decision: string;
  lastPlanVersion: number;
}

interface DepositForStory {
  id: string; amount_minor: number; currency: string; customer_name: string | null; payer_name: string;
  plans: { version: number; summary: string; actions: { type: string; question?: string }[] }[];
  evidence: { source: string; verdict: string; checks: Check[]; envelope: Record<string, any> }[];
}

export async function loadStory(depositId: string): Promise<AgentStory> {
  const d = await get<DepositForStory>(`/deposits/${depositId}`);
  const ask = d.plans[0]?.actions.find((a) => a.type === "ask_payer_agent");
  const ev = [...d.evidence].reverse().find((e) => e.source === "mcp_signed") ?? null;
  const claim = ev?.envelope?.claim;
  const last = d.plans[d.plans.length - 1];
  return {
    deposit: d.id,
    amount: money(d.amount_minor, d.currency),
    payer: d.customer_name ?? d.payer_name,
    question: ask?.question ? plainReason(ask.question) : null,
    answer: claim ? String(claim.note ?? `${String(claim.reason ?? "").replace(/_/g, " ")} for ${claim.invoice_id}`) : null,
    keyId: ev?.envelope?.key_id ?? null,
    source: ev?.source ?? null,
    verdict: ev?.verdict ?? null,
    checks: Array.isArray(ev?.checks) ? ev!.checks : [],
    decision: last ? plainReason(last.summary) : "",
    lastPlanVersion: last?.version ?? 0,
  };
}

/** The lines of the conversation, in order, each with who says it. */
export function storyLines(s: AgentStory): { who: "ledgerline" | "payer"; text: string }[] {
  const lines: { who: "ledgerline" | "payer"; text: string }[] = [];
  if (s.question) lines.push({ who: "ledgerline", text: `About ${s.deposit}, ${s.amount}: ${s.question}` });
  if (s.answer) lines.push({ who: "payer", text: `${s.answer}${s.keyId ? ` Signed with key ${s.keyId}.` : ""}` });
  for (const c of s.checks) lines.push({ who: "ledgerline", text: `${c.label}: ${c.passed ? "passed." : `failed. ${plainReason(c.detail)}`}` });
  if (s.decision) lines.push({ who: "ledgerline", text: s.decision });
  return lines;
}
