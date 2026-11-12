function group(minor: number): string {
  const abs = Math.abs(minor);
  const whole = String(Math.floor(abs / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${whole}.${String(abs % 100).padStart(2, "0")}`;
}

/** Minor units -> "USD 4,985.00". String math only; the UI never sums across currencies. */
export function money(minor: number, ccy: string, opts: { sign?: boolean } = {}): string {
  const sign = minor < 0 ? "−" : opts.sign && minor > 0 ? "+" : ""; // U+2212, a true minus sign
  return `${ccy} ${sign}${group(minor)}`;
}

export function amountOnly(minor: number): string {
  return (minor < 0 ? "−" : "") + group(minor);
}

/** "1,250.00" -> 125000, or null when not a plain 2-dp decimal. */
export function parseMajor(input: string): number | null {
  const t = input.trim().replace(/,/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(t)) return null;
  const [w, f = ""] = t.split(".");
  return Number(w) * 100 + Number((f + "00").slice(0, 2));
}

/** What parseMajor accepted, in the plain form the API requires ("1,250.50" -> "1250.50"). */
export function plainAmount(input: string): string {
  return input.trim().replace(/,/g, "");
}

export function majorString(minor: number): string {
  return `${Math.floor(minor / 100)}.${String(minor % 100).padStart(2, "0")}`;
}

// Times read in the viewer's own time zone, with its short name ("05 Nov, 10:22 GMT+5:30"); whenUtc gives the
// same moment in UTC for tooltips. Calendar dates (day) stay as written: a due date is a day, not a moment.
const dtf = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "short" });
const utc = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "UTC" });
const df = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });

// Each browser joins the pieces its own way (Safari can write "at"), so the strings are built from the parts.
function parts(f: Intl.DateTimeFormat, d: Date): Record<string, string> {
  return Object.fromEntries(f.formatToParts(d).filter((x) => x.type !== "literal").map((x) => [x.type, x.value]));
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const p = parts(dtf, d);
  return `${p.day} ${p.month}, ${p.hour}:${p.minute} ${p.timeZoneName}`;
}

export function whenUtc(iso: string | null | undefined): string | undefined {
  if (!iso) return undefined;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return undefined;
  const p = parts(utc, d);
  return `${p.day} ${p.month} ${p.year}, ${p.hour}:${p.minute} UTC`;
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const p = parts(df, d);
  return `${p.day} ${p.month} ${p.year}`;
}

export function relativeDays(iso: string, now: string): string {
  const days = Math.round((new Date(iso).getTime() - new Date(now).getTime()) / 86_400_000);
  if (days === 0) return "today";
  return days > 0 ? `in ${days} d` : `${-days} d ago`;
}

export const STATUS_LABEL: Record<string, string> = {
  received: "Received",
  matched: "Matched",
  partially_applied: "Partly paid",
  awaiting_evidence: "Asking payer",
  escalated: "Needs review",
  credited: "Held as credit",
  refund_awaiting_approval: "Refund for approval",
  refund_in_flight: "Refund on its way",
  refunded: "Refunded",
};

export const CATEGORY_LABEL: Record<string, string> = {
  clean_match: "Exact match",
  clean_with_fee: "Match, bank fee written off",
  partial_payment: "Short payment",
  unknown_reference: "No reference",
  unidentified_payer: "Unknown payer",
  unknown_invoice: "Unknown invoice",
  reference_conflict: "Other customer's invoice",
  wrong_currency: "Wrong currency",
  apparent_duplicate: "Possible duplicate",
  overpayment: "Overpayment",
  evidence_rejected: "Payer's answer rejected",
  verified_invoice_payment: "Verified invoice payment",
  verified_advance_credit: "Verified advance → credit",
  verified_duplicate: "Verified duplicate",
  operator_resolution: "Decided by a person",
  converted_settlement: "Converted to settle an invoice",
};

export const SOURCE_LABEL: Record<string, string> = {
  local_simulated_webhook: "Simulated webhook",
  manual_import: "Manually recorded",
  csv_import: "Imported from CSV",
  airwallex_sandbox_simulation: "Sandbox simulation",
  airwallex_sandbox_webhook: "Sandbox webhook",
  airwallex_payment_link: "Airwallex payment link",
  practice_payment_link: "Practice payment link",
  practice_payment: "Practice payment",
};

export function tone(status: string): "ok" | "warn" | "risk" | "info" | "muted" {
  switch (status) {
    case "matched":
    case "refunded":
    case "credited":
    case "paid":
    case "settled":
    case "verified":
    case "approved":
    case "executed":
      return "ok";
    case "escalated":
    case "rejected":
    case "failed":
    case "invalidated":
      return "risk";
    case "partially_applied":
    case "awaiting_evidence":
    case "refund_awaiting_approval":
    case "pending":
    case "processing":
    case "sent":
    case "refund_in_flight":
    case "advisory":
      return "warn";
    default:
      return "muted";
  }
}

/** The rules' reasons, said for a finance team. The stored text stays as the rules wrote it (Replay compares it). */
const PLAIN: [RegExp, string][] = [
  [/no registered payer agent; route remittance text to evidence reader \/ operator/i,
    "This customer has no payer agent: read their remittance email (Read remittance…) or decide yourself"],
  [/^unidentified payer$/i, "The payer is not one of your customers"],
  [/^reference names another customer's invoice$/i, "The reference names another customer's invoice"],
  [/^currency mismatch between deposit and invoice$/i, "Paid in a different currency from the invoice"],
  [/references (.+), which every referenced invoice is already settled\./i, "references $1, and every invoice it names is already paid."],
  [/references (.+), which references a not-yet-issued invoice\./i, "references $1, an invoice that has not been issued yet."],
  [/every referenced invoice is already settled/i, "every invoice it names is already paid"],
  [/payer agent returned '(\w+)': /i, "the payer's agent answered \"$1\": "],
];

export function plainReason(text: string | null | undefined): string {
  let t = text ?? "";
  for (const [re, plain] of PLAIN) t = t.replace(re, plain);
  return t;
}

/** Audit event codes as sentences. The code itself stays in the log, the export and a tooltip. */
const ACTION_LABEL: Record<string, string> = {
  "deposit.received": "Payment received", "deposit.settled": "Payment settled", "deposit.resolved_by_operator": "Resolved by a person",
  "deposit.conversion_requested": "Conversion requested", "payment.recorded_manually": "Payment recorded by hand",
  "plan.initial": "Matched by the rules", "plan.revised": "Plan revised", "plan.operator": "Decided by a person",
  "evidence.received": "Payer's agent answered", "evidence.extracted": "Remittance read", "agent.asked_automatically": "Payer's agent asked automatically", "agent.outside_answer": "Answer from the customer's own agent (outside this server)",
  "allocation.created": "Applied to an invoice", "credit.created": "Held as customer credit", "writeoff.created": "Bank fee written off",
  "payment_link.drafted": "Balance request drafted",
  "payment_link.draft_fallback": "Balance request ready as an email draft (no hosted link)",
  "payment_link.sandbox_created": "Payment link created", "payment_link.paid": "Payment link paid",
  "payment_link.creation_unknown": "Payment link outcome unknown (check with the bank)", "approval.created": "Approval requested", "approval.approved": "Approved",
  "approval.rejected": "Rejected", "approval.invalidated": "Approval voided (something changed)", "approval.expired": "Approval expired",
  "approval.returned_to_person": "Returned to a person (over the limit)", "refund.created": "Refund sent to the bank",
  "refund.recorded_outside": "Refund recorded as paid outside", "refund.ambiguous": "Refund outcome unknown: checking",
  "refund.processing": "Refund processing", "refund.sent": "Refund sent", "refund.paid": "Refund paid", "refund.failed": "Refund failed",
  "refund.cancelled": "Refund cancelled", "practice_teammate.sent": "Practice teammate sent the refund",
  "bill_payment.proposed": "Bill payment proposed", "bill_payment.approved": "Bill payment approved", "bill_payment.rejected": "Bill payment rejected",
  "bill_payment.invalidated": "Bill payment voided", "bill_payment.approval_expired": "Bill payment approval expired",
  "bill_payment.submitting": "Bill payment sent to the bank", "bill_payment.processing": "Bill payment processing", "bill_payment.sent": "Bill payment sent",
  "bill_payment.paid": "Bill paid", "bill_payment.failed": "Bill payment failed", "bill_payment.ambiguous": "Bill payment outcome unknown: checking",
  "obligation.created": "Bill added", "obligation.paid": "Bill marked paid", "obligation.deferred": "Bill deferred",
  "treasury.decision": "Bill plan decided", "treasury.plan_run": "Bills re-planned", "fx.quote": "Conversion quote received",
  "early_pay.offered": "Early-payment offer made", "early_pay.paid": "Early payment received",
  "customer.created": "Customer added", "customer.updated": "Customer updated", "customer.payer_agent_registered": "Customer's own agent connected",
  "customer.payer_agent_removed": "Customer's own agent removed", "invoice.created": "Invoice added", "invoice.updated": "Invoice updated",
  "invoice.adjusted": "Invoice adjusted", "invoice.voided": "Invoice voided", "beneficiary.created": "Payee added",
  "wallet.opening_balance_set": "Opening balance set", "wallet.opening_balance_from_account": "Opening balance taken from the bank",
  "webhook.accepted": "Bank notification received", "webhook.duplicate_ignored": "Repeated bank notification ignored",
  "money_out.paused": "Money-out paused", "money_out.resumed": "Money-out resumed", "policy.updated": "Policy changed",
  "practice.tamper_tried": "Try to tamper: caught and restored", "practice.cash_squeeze_added": "Practice: cash squeeze added",
  "practice.unclear_payment_added": "Practice: unclear payment added", "practice.wrong_currency_added": "Practice: wrong-currency payment added",
  "demo.reset": "Practice data reset", "user.signup": "Signed up", "user.renamed": "Name changed", "user.password_changed": "Password changed",
  "user.password_reset": "Password reset with a link", "user.deleted": "Account deleted", "login.succeeded": "Signed in", "login.failed": "Failed sign-in",
  "member.invited": "Member invited", "member.joined": "Member joined", "member.left": "Member left", "member.removed": "Member removed",
  "member.role_changed": "Role changed", "member.invitation_revoked": "Invitation revoked", "member.reset_link_issued": "Reset link created",
  "invitation.authentication_failed": "Wrong password when joining", "org.created": "Organization created", "org.settings_updated": "Settings changed",
  "org.airwallex_connected": "Airwallex connected", "org.airwallex_disconnected": "Airwallex disconnected", "organization.deleted": "Organization deleted",
  "identity.linked": "Google sign-in linked", "identity.unlinked": "Google sign-in removed",
};

export function actionLabel(code: string): string {
  if (ACTION_LABEL[code]) return ACTION_LABEL[code];
  const words = code.replace(/[._]/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const ACCOUNT_LABEL: Record<string, string> = {
  unapplied_cash: "Received, not yet placed", customer_credit: "Customer credit", refund_payable: "Refunds owed",
  cash_in_transit: "Cash on its way out", accounts_receivable: "Owed by customers", revenue: "Revenue", opening_equity: "Opening balance",
  bills_paid: "Bills paid", bank_fee_expense: "Bank fees written off", fx_clearing: "Currency conversion", deposit_converted: "Payment converted",
};

/** Journal account names for people: "cash:GBP" reads "Cash (GBP)". The code stays in a tooltip. */
export function accountLabel(account: string): string {
  if (account.startsWith("cash:")) return `Cash (${account.slice(5)})`;
  return ACCOUNT_LABEL[account] ?? account.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

const ACTOR_LABEL: Record<string, string> = {
  rules: "Rules", system: "Ledgerline", "system:watcher": "Ledgerline (watcher)", "agent:auto": "Ledgerline (asks payer agents)",
  provider: "Bank", webhook: "Bank notification", manual_import: "Typed in by a person", csv_import: "CSV import",
  "practice-teammate": "Practice teammate", "policy:auto_limit": "Policy (refund auto-limit)",
};

/** Who did it, for people: "payer_agent:CUST-FJORD" reads "Payer's agent (CUST-FJORD)". Emails stay as they are. */
export function actorLabel(actor: string): string {
  if (ACTOR_LABEL[actor]) return ACTOR_LABEL[actor];
  if (actor.startsWith("payer_agent:")) return `Payer's agent (${actor.slice(12)})`;
  return actor;
}

/** "Asking payer" is true where the agent asks by itself, on arrival and again on retry. A practice company waits for a
 *  person to press Ask payer's agent, so there the same status reads "Ready to ask payer". */
export function statusLabel(status: string, practice: boolean): string | undefined {
  return status === "awaiting_evidence" && practice ? "Ready to ask payer" : undefined;
}
