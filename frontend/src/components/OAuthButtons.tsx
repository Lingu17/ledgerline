import { useEffect, useState } from "react";
import { get } from "../api";

export type ProviderId = "google" | "apple";
type Providers = Record<ProviderId, { configured: boolean }>;

export const PROVIDER_LABEL: Record<ProviderId, string> = { google: "Google", apple: "Apple" };

// Short codes from the server's ?oauth_error=... redirect, in words.
const ERRORS: Record<string, string> = {
  cancelled: "Sign-in was cancelled.",
  not_configured: "That sign-in option is not set up on this server.",
  account_exists: "An account with this email already exists. Sign in with your password, then connect it under Settings → Sign-in methods.",
  email_unverified: "The provider did not confirm your email address.",
  signup_disabled: "New accounts are disabled on this server. Ask an owner for an invitation.",
  account_disabled: "This account is disabled.",
  identity_in_use: "That account is already connected to a different Ledgerline user.",
  already_linked: "A different account from that provider is already connected.",
  signin_required: "Sign in first, then connect the provider.",
  state_expired: "The sign-in took too long. Try again.",
  state_reused: "That sign-in link was already used. Try again.",
  browser_mismatch: "Sign-in must finish in the same browser it started in. Try again.",
  unknown_state: "That sign-in attempt is not recognised. Try again.",
  provider_unavailable: "The provider could not be reached. Try again shortly.",
};

export function oauthErrorText(code: string | null): string | null {
  if (!code) return null;
  return ERRORS[code] ?? "Sign-in with that provider failed. Try again.";
}

export function hashParam(name: string): string | null {
  const q = window.location.hash.split("?")[1] ?? "";
  return new URLSearchParams(q).get(name);
}

export function useProviders() {
  const [p, setP] = useState<Providers | null>(null);
  useEffect(() => {
    // A sleeping free-tier backend can fail the first request; retry for about a minute.
    let alive = true;
    let timer: number | undefined;
    const load = (attempt: number) => {
      get<Providers>("/auth/providers")
        .then((v) => { if (alive) setP(v); })
        .catch(() => { if (alive && attempt < 6) timer = window.setTimeout(() => load(attempt + 1), 10_000); });
    };
    load(0);
    return () => { alive = false; window.clearTimeout(timer); };
  }, []);
  return p;
}

export function startUrl(provider: ProviderId, params: Record<string, string> = {}) {
  const q = new URLSearchParams(params).toString();
  return `/api/auth/oauth/${provider}/start${q ? `?${q}` : ""}`;
}

export function ProviderLogo({ id }: { id: ProviderId }) {
  if (id === "google") {
    return (
      <svg viewBox="0 0 48 48" width="18" height="18" aria-hidden="true">
        <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
        <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
        <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
        <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="currentColor">
      <path d="M16.37 12.6c-.02-2.28 1.86-3.38 1.95-3.43-1.06-1.55-2.71-1.77-3.3-1.79-1.4-.14-2.74.83-3.45.83-.71 0-1.81-.81-2.98-.79-1.53.02-2.94.89-3.73 2.26-1.59 2.76-.41 6.84 1.14 9.08.76 1.1 1.66 2.33 2.84 2.28 1.14-.05 1.57-.74 2.95-.74 1.38 0 1.77.74 2.98.71 1.23-.02 2.01-1.11 2.76-2.21.87-1.27 1.23-2.5 1.25-2.57-.03-.01-2.39-.92-2.41-3.63zM14.1 5.9c.63-.76 1.05-1.82.94-2.87-.9.04-2 .6-2.65 1.36-.58.67-1.09 1.75-.95 2.79 1 .08 2.03-.51 2.66-1.28z" />
    </svg>
  );
}

/** Google sign-in; unavailable Google configuration is explained on the form. */
export function OAuthButtons({ returnTo, verb = "Continue" }: { returnTo?: string; verb?: string }) {
  const providers = useProviders();
  const ids: ProviderId[] = ["google"];
  const anyMissing = providers && ids.some((id) => !providers[id]?.configured);
  return (
    <div className="oauth">
      {ids.map((id) => {
        const ok = !!providers?.[id]?.configured;
        const label = `${verb} with ${PROVIDER_LABEL[id]}`;
        return ok ? (
          <a key={id} className={`oauth-btn ${id}`} href={startUrl(id, returnTo ? { return_to: returnTo } : {})}>
            <ProviderLogo id={id} /><span>{label}</span>
          </a>
        ) : (
          <button key={id} type="button" className={`oauth-btn ${id}`} disabled aria-describedby="oauth-note">
            <ProviderLogo id={id} /><span>{label}</span>
          </button>
        );
      })}
      {anyMissing && <p id="oauth-note" className="oauth-note">Disabled options have not been set up by this server's administrator.</p>}
      <div className="oauth-divider" role="separator"><span>or with email</span></div>
    </div>
  );
}
