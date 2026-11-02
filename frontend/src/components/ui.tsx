import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ApiError, post } from "../api";
import { STATUS_LABEL, money, tone } from "../format";

// ---------------------------------------------------------------- data loading
export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const { version } = useRefresh();
  const latest = useRef(0); // a slower, older response must never overwrite a newer one
  const run = useCallback(() => {
    const request = ++latest.current;
    setLoading(true);
    load()
      .then((d) => {
        if (request !== latest.current) return;
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => {
        if (request === latest.current) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (request === latest.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(run, [run, version]);
  return { data, error, loading, reload: run };
}

// Bumping this re-fetches every mounted view after a mutation.
const RefreshCtx = createContext<{ version: number; bump: () => void }>({ version: 0, bump: () => {} });
export function RefreshProvider({ children }: { children: ReactNode }) {
  const [version, setVersion] = useState(0);
  const bump = useCallback(() => setVersion((v) => v + 1), []);
  return <RefreshCtx.Provider value={{ version, bump }}>{children}</RefreshCtx.Provider>;
}
export const useRefresh = () => useContext(RefreshCtx);

// ---------------------------------------------------------------- toasts
type Toast = { id: number; text: string; kind: "info" | "error" };
const ToastCtx = createContext<(text: string, kind?: Toast["kind"]) => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: Toast["kind"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 9000 : 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind === "error" ? "error" : ""}`}>
            <span>{t.text}</span>
            <button aria-label="Dismiss" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}>×</button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

/** Run a mutation, toast the outcome, refresh views. Returns the result or null on error. */
export function useAction() {
  const toast = useToast();
  const { bump } = useRefresh();
  const [busy, setBusy] = useState<string | null>(null);
  const run = useCallback(
    async <T,>(key: string, fn: () => Promise<T>, success?: string | ((r: T) => string)): Promise<T | null> => {
      setBusy(key);
      try {
        const r = await fn();
        if (success) toast(typeof success === "function" ? success(r) : success);
        bump();
        return r;
      } catch (e) {
        const status = e instanceof ApiError ? e.status : 0;
        toast(status === 423 ? `Paused: ${(e as Error).message}` : (e as Error).message, "error");
        bump();
        return null;
      } finally {
        setBusy(null);
      }
    },
    [toast, bump],
  );
  return { run, busy };
}

// ---------------------------------------------------------------- small pieces
export function Pill({ status, label }: { status: string; label?: string }) {
  return <span className={`pill ${tone(status)}`}>{label ?? STATUS_LABEL[status] ?? status.replace(/_/g, " ")}</span>;
}

export function Money({ minor, ccy, sign }: { minor: number; ccy: string; sign?: boolean }) {
  return <span className={`num ${minor < 0 ? "neg" : ""}`}>{money(minor, ccy, { sign })}</span>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <b>{title}</b>
      {children}
    </div>
  );
}

export function Loading({ rows = 4 }: { rows?: number }) {
  return (
    <div className="card-body stack" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="notice risk row" role="alert" style={{ justifyContent: "space-between" }}>
      <span>Could not load: {error}</span>
      {onRetry && <button className="btn small" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Card({ title, actions, children, pad = true }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; pad?: boolean }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card-head">
          {typeof title === "string" ? <h2>{title}</h2> : title}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {pad ? <div className="card-body">{children}</div> : children}
    </section>
  );
}

function useFocusTrap(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  // Callers pass a new onClose on every render; keep the latest without re-running the effect (re-running would
  // move focus back to the first control on every keystroke in a field whose state lives in the caller).
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const node = ref.current;
    node?.querySelector<HTMLElement>("button, input, select, textarea, [tabindex]")?.focus();
    lockScroll(1);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close.current();
      if (e.key === "Tab" && node) {
        const items = Array.from(node.querySelectorAll<HTMLElement>("button:not([disabled]), input, select, textarea, a[href], [tabindex='0']"));
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          last.focus();
          e.preventDefault();
        } else if (!e.shiftKey && document.activeElement === last) {
          first.focus();
          e.preventDefault();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      lockScroll(-1);
      prev?.focus();
    };
  }, []);
  return ref;
}

// The page behind an open drawer or dialog does not scroll; nested ones (a dialog over a drawer) are counted.
let scrollLocks = 0;
function lockScroll(delta: number) {
  scrollLocks = Math.max(0, scrollLocks + delta);
  document.body.style.overflow = scrollLocks > 0 ? "hidden" : "";
}

export function Drawer({ title, subtitle, onClose, children }: { title: ReactNode; subtitle?: ReactNode; onClose: () => void; children: ReactNode }) {
  const ref = useFocusTrap(onClose);
  // Rendered at the end of <body> so no ancestor (the sidebar's colours or its transform on phones) affects it.
  return createPortal(
    <>
      <div className="scrim" onClick={onClose} />
      <div className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title" ref={ref}>
        <div className="drawer-head">
          <div>
            <h2 id="drawer-title">{title}</h2>
            {subtitle && <div className="muted small">{subtitle}</div>}
          </div>
          <button className="btn ghost" onClick={onClose} aria-label="Close panel">Close</button>
        </div>
        <div className="drawer-body">{children}</div>
      </div>
    </>,
    document.body,
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useFocusTrap(onClose);
  return createPortal(
    <>
      <div className="scrim modal-scrim" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" ref={ref}>
        <div className="modal-head">
          <h2 id="modal-title">{title}</h2>
          <button className="btn ghost small" onClick={onClose} aria-label="Close dialog">Close</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </>,
    document.body,
  );
}

export function Field({ label, hint, error, children, wide, id }: { label: string; hint?: string; error?: string | null; children: ReactNode; wide?: boolean; id: string }) {
  return (
    <div className={`field ${wide ? "wide" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {children}
      {error ? <span className="err" id={`${id}-err`}>{error}</span> : hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
}

export function CsvImport({ title, path, columns, example, onClose }: { title: string; path: string; columns: string; example: string; onClose: () => void }) {
  const { run, busy } = useAction();
  const [text, setText] = useState("");
  const [result, setResult] = useState<{ created: number; errors: number; results: { line: number; status: string; error?: string }[] } | null>(null);
  return (
    <Modal title={title} onClose={onClose}>
      {result ? (
        <div className="stack" style={{ gap: 10 }}>
          <div className="small">{result.created} added · {result.errors} with errors</div>
          {result.results.filter((r) => r.error).map((r) => <div key={r.line} className="small neg">Line {r.line}: {r.error}</div>)}
          <div className="form-actions"><button className="btn primary" onClick={onClose}>Done</button></div>
        </div>
      ) : (
        <form onSubmit={async (e) => {
          e.preventDefault();
          const r = await run("csv", () => post<NonNullable<typeof result>>(path, { csv: text }));
          if (r) setResult(r);
        }}>
          <Field id="csv-import" label="Paste CSV, including the header" hint={columns}>
            <textarea id="csv-import" rows={8} className="mono" value={text} placeholder={`${columns}\n${example}`} onChange={(e) => setText(e.target.value)} />
          </Field>
          <div className="form-actions"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!!busy || !text.trim()}>Import</button></div>
        </form>
      )}
    </Modal>
  );
}

export function Checks({ checks }: { checks: { name: string; label: string; passed: boolean; detail: string }[] }) {
  const order = ["signature", "binding", "records"];
  const byName = new Map(checks.map((c) => [c.name, c]));
  const fallback: Record<string, string> = {
    signature: "Signed by the registered customer key",
    binding: "Names this exact deposit and is fresh",
    records: "Our records agree",
  };
  return (
    <div className="checks">
      {order.map((n, i) => {
        const c = byName.get(n);
        const cls = c ? (c.passed ? "ok" : "risk") : "na";
        return (
          <div className="check" key={n}>
            <span className={`mark ${cls}`} aria-hidden="true">{c ? (c.passed ? "✓" : "✕") : "–"}</span>
            <div>
              <b>
                {i + 1}. {c?.label ?? fallback[n]} <span className="sr-only">{c ? (c.passed ? "passed" : "failed") : "not evaluated"}</span>
              </b>
              <span>{c?.detail ?? "Not evaluated for this evidence."}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
