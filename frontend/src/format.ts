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

const dtf = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
const df = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : `${dtf.format(d)} UTC`;
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : df.format(d);
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
  refund_in_flight: "Refund in flight",
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
  evidence_rejected: "Evidence rejected",
  verified_invoice_payment: "Verified invoice payment",
  verified_advance_credit: "Verified advance → credit",
  verified_duplicate: "Verified duplicate",
  operator_resolution: "Resolved by operator",
  converted_settlement: "Converted to settle an invoice",
};

export const SOURCE_LABEL: Record<string, string> = {
  local_simulated_webhook: "Simulated webhook",
  manual_import: "Manually recorded",
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
