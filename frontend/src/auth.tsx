import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, get, post, session, type Me, type Role } from "./api";

const RANK: Record<Role, number> = { viewer: 0, operator: 1, owner: 2 };

interface AuthState {
  me: Me | null;
  loading: boolean;
  setMe: (me: Me | null) => void;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
  switchOrg: (id: string) => Promise<void>;
  can: (min: Role) => boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMeState] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const setMe = useCallback((m: Me | null) => {
    session.setCsrf(m?.csrf_token ?? null);
    setMeState(m);
  }, []);
  const refresh = useCallback(async () => {
    try {
      const s = await get<Me & { signed_in: boolean }>("/auth/session");  // 200 either way: no 401 for a visitor
      setMe(s.signed_in ? s : null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setMe(null);
      else throw e;
    } finally {
      setLoading(false);
    }
  }, [setMe]);
  useEffect(() => {
    refresh().catch(() => setLoading(false));
    return session.onUnauthorized(() => setMe(null));
  }, [refresh, setMe]);
  const signOut = useCallback(async () => {
    try {
      await post("/auth/logout");
    } finally {
      setMe(null);
      window.location.hash = "/inbox";
    }
  }, [setMe]);
  const switchOrg = useCallback(
    async (id: string) => {
      setMe(await post<Me>("/auth/switch-organization", { organization_id: id }));
      window.location.hash = "/inbox";
    },
    [setMe],
  );
  const can = useCallback((min: Role) => !!me?.role && RANK[me.role] >= RANK[min], [me]);
  return <Ctx.Provider value={{ me, loading, setMe, refresh, signOut, switchOrg, can }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export const ROLE_LABEL: Record<Role, string> = { owner: "Owner", operator: "Operator", viewer: "Viewer" };
export const ROLE_HELP: Record<Role, string> = {
  owner: "Everything, plus team, policy, integrations and resuming money-out",
  operator: "Day-to-day work: payments, customers, invoices, approvals of others' proposals, treasury",
  viewer: "Read-only access, including evidence export",
};
