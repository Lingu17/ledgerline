// Thin client for the Ledgerline backend. The session lives in an HttpOnly cookie the
// browser sends automatically; this module only holds the CSRF token returned by /auth/me.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let csrfToken: string | null = null;
const unauthorizedListeners = new Set<() => void>();

export const session = {
  setCsrf(token: string | null) {
    csrfToken = token;
  },
  onUnauthorized(fn: () => void): () => void {
    unauthorizedListeners.add(fn);
    return () => {
      unauthorizedListeners.delete(fn);
    };
  },
};

function headers(json: boolean, mutating: boolean): HeadersInit {
  const h: Record<string, string> = {};
  if (mutating && csrfToken) h["X-CSRF-Token"] = csrfToken;
  if (json) h["Content-Type"] = "application/json";
  return h;
}

const UNAVAILABLE = "Ledgerline's server is not reachable right now. It may be restarting; try again in a minute.";

// fetch() only rejects when the network fails (offline, DNS, proxy cut); give that a readable message.
async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`/api${path}`, { credentials: "same-origin", ...init });
  } catch {
    throw new ApiError(0, UNAVAILABLE);
  }
}

async function handle<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    // A gateway error page (HTML) from the hosting proxy, not an API answer.
    body = { detail: [502, 503, 504].includes(res.status) ? UNAVAILABLE : text.slice(0, 200) };
  }
  if (res.status === 401 && !res.url.includes("/api/auth/")) unauthorizedListeners.forEach((fn) => fn());
  if (!res.ok) {
    const detail = body?.detail;
    const msg = Array.isArray(detail)
      ? detail.map((d: { loc?: string[]; msg: string }) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ")
      : detail || `Request failed (${res.status})`;
    throw new ApiError(res.status, msg);
  }
  return body as T;
}

export async function get<T>(path: string): Promise<T> {
  return handle<T>(await send(path, { headers: headers(false, false) }));
}

export async function post<T>(path: string, body?: unknown, method = "POST"): Promise<T> {
  return handle<T>(
    await send(path, {
      method,
      headers: headers(body !== undefined, true),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  );
}

export function del<T>(path: string): Promise<T> {
  return post<T>(path, undefined, "DELETE");
}

/** GET that also returns the X-Total-Count header for paginated lists. */
export async function getPage<T>(path: string): Promise<{ items: T; total: number }> {
  const res = await send(path, { headers: headers(false, false) });
  const total = Number(res.headers.get("X-Total-Count") ?? "0");
  return { items: await handle<T>(res), total };
}

export async function download(path: string, filename: string) {
  const res = await fetch(`/api${path}`, { headers: headers(false, false), credentials: "same-origin" });
  if (!res.ok) throw new ApiError(res.status, `Export failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------- types
export type Ccy = "USD" | "EUR" | "GBP";

export interface Buckets {
  amount: number;
  allocated: number;
  credited: number;
  refund_paid: number;
  refund_pending: number;
  converted: number;
  unapplied: number;
}

export interface PlanAction {
  type: string;
  invoice_id?: string;
  amount_minor?: number;
  customer_id?: string;
  reason?: string;
  question?: string;
  status?: string;
  earmark_invoice_id?: string | null;
}

export interface Plan {
  id: number;
  deposit_id: string;
  version: number;
  kind: "initial" | "revised" | "operator";
  category: string;
  summary: string;
  actions: PlanAction[];
  evidence_id: string | null;
  created_at: string;
}

export interface Check {
  name: string;
  label: string;
  passed: boolean;
  detail: string;
}

export interface Evidence {
  id: string;
  deposit_id: string;
  asked_customer_id: string | null;
  version: number;
  source: "mcp_signed" | "claude_extracted" | "fixture_extracted";
  transport: string | null;
  envelope: Record<string, any>;
  claim_hash: string;
  checks: Check[];
  verdict: "verified" | "rejected" | "advisory";
  reason: string;
  created_at: string;
}

export interface Deposit {
  id: string;
  provider_ref: string;
  source: string;
  currency: Ccy;
  amount_minor: number;
  payer_name: string;
  reference: string;
  received_at: string;
  status: string;
  category: string | null;
  customer_id: string | null;
  customer_name: string | null;
  version: number;
  escalation_reason: string | null;
  buckets: Buckets;
  plan: Plan | null;
  plan_count: number;
}

export interface Approval {
  id: string;
  sender_must_differ: boolean;
  operation_type: string;
  deposit_id: string;
  scope: {
    operation: string;
    deposit_id: string;
    deposit_version: number;
    amount_minor: number;
    currency: Ccy;
    destination: string;
    evidence_id: string | null;
    evidence_version: number | null;
    evidence_claim_hash: string | null;
    latest_evidence_id: string | null;
  };
  scope_hash: string;
  status: "pending" | "approved" | "rejected" | "invalidated" | "executed";
  reason: string;
  decided_by: string | null;
  decided_at: string | null;
  invalidated_reason: string | null;
  created_at: string;
  created_by: string | null;
  evidence: { id: string; verdict: string; reason: string; checks: Check[]; source: string } | null;
  operation: Operation | null;
}

export interface OperationEvent {
  id: number;
  from_status: string | null;
  to_status: string;
  detail: string;
  at: string;
}

export interface Operation {
  id: string;
  kind: "refund" | "fx_conversion";
  deposit_id: string | null;
  request_id: string;
  currency: Ccy;
  amount_minor: number;
  destination: string;
  status: string;
  approval_id: string | null;
  provider_id: string | null;
  needs_reconciliation: number;
  attempts: number;
  last_error: string | null;
  detail: Record<string, any> | string;
  created_at: string;
  updated_at: string;
  events?: OperationEvent[];
}

export interface Wallet {
  currency: Ccy;
  cash: number;
  reserve: number;
  customer_credits: number;
  unapplied_held: number;
  refunds_reserved: number;
  obligations_due_in_window: number;
  fx_out_reserved: number;
  fx_in_pending: number;
  free_after_commitments: number;
  projected_after_pending_fx: number;
}

export interface Status {
  now: string;
  bank: { mode: string; label: string; airwallex_credentials_present: boolean; airwallex_executed_in_this_build: boolean; sandbox_available: boolean; global_accounts_configured: string[] };
  claude: { mode: string; model: string | null; label: string };
  payer_agents: { transport: string; label: string };
  security: { bind_host: string; cookie_secure: boolean; allowed_origins: string[]; webhook_secret_source: string; webhook_path: string | null };
  org: { id: string; name: string; kind: "workspace" | "sample"; bank_mode: string } | null;
  role: Role;
  paused: boolean;
  pause_info: { by: string; at: string; reason: string } | null;
  policy: Policy;
  demo_fx_rates: { sell: string; buy: string; rate: string }[];
}

export interface Policy {
  fee_tolerance_minor: Record<Ccy, number>;
  fee_tolerance_bps: number;
  refund_auto_limit_minor: Record<Ccy, number>;
  reserve_minor: Record<Ccy, number>;
  ring_fenced_minor: Record<Ccy, number>;
  obligation_lookahead_days: number;
  evidence_max_ttl_seconds: number;
  evidence_clock_skew_seconds: number;
  webhook_tolerance_seconds: number;
}

export interface AuditEvent {
  id: number;
  at: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  operation_id: string | null;
  detail: Record<string, any>;
}

export interface Invoice {
  id: string;
  effective_amount_minor: number;
  effective_status: "open" | "scheduled" | "paid" | "void";
  voided_at: string | null;
  adjustments: { id: string; delta_minor: number; reason: string; created_by: string; created_at: string }[];
  customer_id: string;
  customer_name: string;
  currency: Ccy;
  amount_minor: number;
  prior_paid_minor: number;
  status: "open" | "scheduled" | "paid";
  issued_at: string;
  due_at: string;
  description: string;
  remaining_minor: number;
  allocated_minor: number;
  written_off_minor: number;
  payment_links: { id: string; status: string; amount_minor: number; note: string; url: string | null }[];
}

export interface Customer {
  id: string;
  name: string;
  country: string;
  payer_names: string[];
  agent_key_id: string | null;
  refund_beneficiary: string;
  demo_only: number;
  credits: { id: number; deposit_id: string; currency: Ccy; amount_minor: number; earmark_invoice_id: string | null }[];
}

export type Role = "owner" | "operator" | "viewer";

export interface Me {
  user: { id: string; email: string; name: string };
  csrf_token: string;
  session_expires_at: string;
  organization: { id: string; name: string; kind: "workspace" | "sample"; role: Role } | null;
  role: Role | null;
  organizations: { id: string; name: string; kind: "workspace" | "sample"; role: Role }[];
  signup_enabled: boolean;
}
