import { useEffect, useRef, useState } from "react";

// Interactive architecture view: the deployed components as nodes in 3D, with pulses travelling along each data
// flow. Plain canvas 2D with a perspective projection (no WebGL library). Drag or use the arrow keys to turn it.
// Reduced motion: no auto-rotation or pulses. The same information is in the text list below for screen readers.

type V3 = [number, number, number];
type Zone = "edge" | "app" | "data" | "ext" | "agent";
const NODES: { id: string; label: string; sub: string; at: V3; zone: Zone }[] = [
  { id: "browser", label: "Browser", sub: "React UI, same origin", at: [-1.6, 0.9, 0], zone: "edge" },
  { id: "caddy", label: "Caddy", sub: "HTTPS, headers, CSP", at: [-0.7, 0.9, 0], zone: "edge" },
  { id: "api", label: "FastAPI", sub: "rules, approvals, ledger", at: [0.3, 0.6, 0], zone: "app" },
  { id: "sqlite", label: "SQLite", sub: "per-org files, backups", at: [0.3, -0.6, 0.55], zone: "data" },
  { id: "keys", label: "Payer keys", sub: "Ed25519, per org", at: [-0.5, -0.7, -0.4], zone: "data" },
  { id: "mcp", label: "Payer agents", sub: "MCP explain_payment", at: [1.3, -0.3, -0.7], zone: "agent" },
  { id: "claude", label: "Claude", sub: "typed proposals only", at: [1.4, 0.75, -0.6], zone: "ext" },
  { id: "airwallex", label: "Airwallex", sub: "sandbox API + webhooks", at: [1.5, 0.1, 0.8], zone: "ext" },
];
const EDGES: [string, string, string][] = [
  ["browser", "caddy", "HTTPS"], ["caddy", "api", "/api"], ["api", "sqlite", "journal"], ["api", "keys", "load"],
  ["api", "mcp", "signed claim"], ["api", "claude", "remittance text/PDF"], ["api", "airwallex", "quotes, transfers"],
  ["airwallex", "api", "deposit.settled"],
];
const COLOR: Record<Zone, string> = { edge: "#8fb4d9", app: "#5EC4B6", data: "#e7c27d", ext: "#c39bd3", agent: "#f08a7e" };

function Arch3D() {
  const ref = useRef<HTMLCanvasElement>(null);
  const yaw = useRef(0.55);
  const pitch = useRef(0.32);
  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0, h = 0, dpr = 1, raf = 0, dragging = false, lastX = 0, lastY = 0, idle = 0;
    const byId = Object.fromEntries(NODES.map((n) => [n.id, n]));
    const project = (p: V3) => {
      const cy = Math.cos(yaw.current), sy = Math.sin(yaw.current), cp = Math.cos(pitch.current), sp = Math.sin(pitch.current);
      const x1 = p[0] * cy + p[2] * sy, z1 = -p[0] * sy + p[2] * cy;
      const y2 = p[1] * cp - z1 * sp, z2 = p[1] * sp + z1 * cp;
      const s = 4 / (4 - z2);
      const R = Math.min(w / 4.2, h / 2.8);
      return { x: w / 2 + x1 * R * s, y: h / 2 - y2 * R * s, z: z2, s };
    };
    const draw = (t: number) => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      EDGES.forEach(([a, b], i) => {
        const pa = project(byId[a].at), pb = project(byId[b].at);
        const back = a === "airwallex";
        ctx.beginPath();
        ctx.setLineDash(back ? [5, 5] : []);
        ctx.moveTo(pa.x, pa.y);
        ctx.lineTo(pb.x, pb.y);
        ctx.strokeStyle = `rgba(160,190,220,${0.25 + ((pa.z + pb.z) / 2 + 1) * 0.2})`;
        ctx.lineWidth = 1.4;
        ctx.stroke();
        ctx.setLineDash([]);
        if (!reduced) {
          const k = (t * 0.00035 + i * 0.23) % 1;
          ctx.beginPath();
          ctx.fillStyle = back ? "rgba(255,214,140,0.95)" : "rgba(94,196,182,0.95)";
          ctx.arc(pa.x + (pb.x - pa.x) * k, pa.y + (pb.y - pa.y) * k, 2.6, 0, Math.PI * 2);
          ctx.fill();
        }
      });
      const order = NODES.map((n) => ({ n, p: project(n.at) })).sort((a, b) => a.p.z - b.p.z);
      ctx.textAlign = "center";
      for (const { n, p } of order) {
        const r = 9 * p.s;
        ctx.beginPath();
        ctx.fillStyle = COLOR[n.zone];
        ctx.globalAlpha = 0.55 + (p.z + 1) * 0.22;
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.fillStyle = "#e6eef7";
        ctx.font = `600 ${Math.round(12 * p.s)}px 'IBM Plex Sans', sans-serif`;
        ctx.fillText(n.label, p.x, p.y - r - 14);
        ctx.fillStyle = "rgba(200,215,232,0.75)";
        ctx.font = `400 ${Math.round(10.5 * p.s)}px 'IBM Plex Sans', sans-serif`;
        ctx.fillText(n.sub, p.x, p.y - r - 2);
      }
    };
    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      draw(performance.now());
    };
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();
    const loop = (t: number) => {
      if (!dragging && t - idle > 1500) yaw.current += 0.0016;
      draw(t);
      raf = requestAnimationFrame(loop);
    };
    if (!reduced) raf = requestAnimationFrame(loop);
    const down = (e: PointerEvent) => { dragging = true; lastX = e.clientX; lastY = e.clientY; canvas.setPointerCapture(e.pointerId); };
    const move = (e: PointerEvent) => {
      if (!dragging) return;
      yaw.current += (e.clientX - lastX) * 0.008;
      pitch.current = Math.max(-0.9, Math.min(0.9, pitch.current + (e.clientY - lastY) * 0.006));
      lastX = e.clientX; lastY = e.clientY;
      if (reduced) draw(0);
    };
    const up = () => { dragging = false; idle = performance.now(); };
    const key = (e: KeyboardEvent) => {
      const d: Record<string, [number, number]> = { ArrowLeft: [-0.15, 0], ArrowRight: [0.15, 0], ArrowUp: [0, -0.1], ArrowDown: [0, 0.1] };
      if (!d[e.key]) return;
      e.preventDefault();
      yaw.current += d[e.key][0];
      pitch.current = Math.max(-0.9, Math.min(0.9, pitch.current + d[e.key][1]));
      idle = performance.now();
      if (reduced) draw(0);
    };
    canvas.addEventListener("pointerdown", down);
    canvas.addEventListener("pointermove", move);
    canvas.addEventListener("pointerup", up);
    canvas.addEventListener("pointercancel", up);
    canvas.addEventListener("keydown", key);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      canvas.removeEventListener("pointerdown", down);
      canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerup", up);
      canvas.removeEventListener("pointercancel", up);
      canvas.removeEventListener("keydown", key);
    };
  }, []);
  return <canvas ref={ref} className="arch-canvas" tabIndex={0}
    aria-label="Interactive 3D architecture diagram. Drag or use the arrow keys to rotate. The same components and flows are listed below." />;
}

export function Architecture() {
  const [mobile] = useState(() => window.matchMedia("(max-width: 640px)").matches);
  return (
    <div className="lp arch">
      <header className="lp-nav">
        <div className="lp-wrap lp-nav-row">
          <a className="lp-logo" href="#/home">Ledgerline</a>
          <div className="lp-nav-cta"><a className="lp-btn ghost" href="#/home">Back to home</a></div>
        </div>
      </header>
      <main className="lp-wrap arch-main">
        <h1>How Ledgerline is deployed</h1>
        <p className="lp-lead">One Google Cloud VM serves the website, the API and the data. Money rules run in code; Claude and payer agents only
          supply evidence that code checks before anything moves.</p>
        {mobile ? <p className="small muted">The 3D view is skipped on small screens; the full description follows.</p> : <Arch3D />}
        <div className="arch-legend" aria-hidden="true">
          {(Object.keys(COLOR) as Zone[]).map((z) => <span key={z}><i style={{ background: COLOR[z] }} />{{ edge: "Edge", app: "Application", data: "Data on disk", ext: "External service", agent: "Payer agents" }[z]}</span>)}
          <span><i className="dash" />Inbound webhook</span>
        </div>
        <h2>Data flow</h2>
        <ol className="arch-flow">
          <li><b>Browser → Caddy → FastAPI.</b> One HTTPS origin; Caddy adds HSTS and a strict content security policy and forwards to the API on 127.0.0.1.</li>
          <li><b>Airwallex → webhook.</b> <code>deposit.settled</code> arrives signed (HMAC over timestamp and raw body), is deduplicated by event id and booked once.</li>
          <li><b>Rules in code.</b> Exact, partial, fee-tolerated, duplicate and unknown payments get a deterministic first plan, all in integer minor units.</li>
          <li><b>Payer agent over MCP.</b> <code>explain_payment</code> returns an Ed25519-signed claim; signature, freshness and our records must all agree.</li>
          <li><b>Claude.</b> Reads pasted text or a PDF and must answer through one of four typed tools. The output is advisory evidence and can never authorise money.</li>
          <li><b>Money out.</b> Refunds and conversions need scoped approvals (a second person above the limit), a stable request id and a pause switch; SENT is not final, only PAID releases the liability.</li>
          <li><b>Storage.</b> Each organization has its own SQLite files and payer keys on the VM's persistent disk, backed up nightly.</li>
        </ol>
      </main>
    </div>
  );
}
