import { useEffect, useRef } from "react";

// Decorative 3D background: a slowly turning globe of points with payment arcs
// travelling between currency centres. Plain canvas 2D with a perspective
// projection; no WebGL library. Static frame when the viewer prefers reduced motion.

type V3 = [number, number, number];

const HUBS: { label: string; lat: number; lon: number }[] = [
  { label: "GBP", lat: 51.5, lon: -0.1 },
  { label: "EUR", lat: 50.1, lon: 8.7 },
  { label: "USD", lat: 40.7, lon: -74 },
  { label: "SGD", lat: 1.35, lon: 103.8 },
  { label: "HKD", lat: 22.3, lon: 114.2 },
  { label: "AUD", lat: -33.9, lon: 151.2 },
  { label: "CNY", lat: 31.2, lon: 121.5 },
];
const ROUTES: [number, number][] = [[0, 2], [1, 3], [2, 5], [0, 4], [6, 1], [3, 5], [4, 2], [1, 0]];

function fromLatLon(lat: number, lon: number): V3 {
  const p = (lat * Math.PI) / 180;
  const l = (lon * Math.PI) / 180;
  return [Math.cos(p) * Math.sin(l), Math.sin(p), Math.cos(p) * Math.cos(l)];
}

function slerp(a: V3, b: V3, t: number, lift: number): V3 {
  const dot = Math.min(1, Math.max(-1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
  const w = Math.acos(dot) || 1e-6;
  const s = Math.sin(w);
  const k1 = Math.sin((1 - t) * w) / s;
  const k2 = Math.sin(t * w) / s;
  const h = 1 + lift * Math.sin(Math.PI * t);
  return [(a[0] * k1 + b[0] * k2) * h, (a[1] * k1 + b[1] * k2) * h, (a[2] * k1 + b[2] * k2) * h];
}

export function Globe({ className }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const N = 900;
    const dots: V3[] = [];
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      dots.push([Math.cos(golden * i) * r, y, Math.sin(golden * i) * r]);
    }
    const hubs = HUBS.map((h) => fromLatLon(h.lat, h.lon));
    const arcs = ROUTES.map(([a, b]) => Array.from({ length: 48 }, (_, i) => slerp(hubs[a], hubs[b], i / 47, 0.28)));

    let w = 0, h = 0, dpr = 1, raf = 0, visible = true;
    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      if (reduced) draw(0);
    };
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; });
    io.observe(canvas);

    const tilt = 0.38;
    const draw = (time: number) => {
      const rot = reduced ? 0.9 : time * 0.00006 + 0.9;
      const R = Math.min(w, h) * 0.42;
      const cx = w * 0.5, cy = h * 0.52;
      const cr = Math.cos(rot), sr = Math.sin(rot), ct = Math.cos(tilt), st = Math.sin(tilt);
      const project = (p: V3) => {
        const x1 = p[0] * cr + p[2] * sr;
        const z1 = -p[0] * sr + p[2] * cr;
        const y2 = p[1] * ct - z1 * st;
        const z2 = p[1] * st + z1 * ct;
        const persp = 3 / (3 - z2);
        return { x: cx + x1 * R * persp, y: cy - y2 * R * persp, z: z2, s: persp };
      };

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      const glow = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 1.35);
      glow.addColorStop(0, "rgba(94,196,182,0.10)");
      glow.addColorStop(1, "rgba(94,196,182,0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, w, h);

      for (const d of dots) {
        const p = project(d);
        const front = (p.z + 1) / 2;
        ctx.fillStyle = `rgba(198,214,232,${0.06 + front * 0.5})`;
        const size = (0.6 + front * 1.1) * p.s;
        ctx.fillRect(p.x - size / 2, p.y - size / 2, size, size);
      }

      arcs.forEach((pts, i) => {
        ctx.beginPath();
        pts.forEach((pt, j) => {
          const p = project(pt);
          if (j === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
        });
        const mid = project(pts[24]);
        ctx.strokeStyle = `rgba(94,196,182,${0.12 + Math.max(0, mid.z) * 0.4})`;
        ctx.lineWidth = 1.2;
        ctx.stroke();

        const t = reduced ? 0.5 : ((time * 0.00018 + i * 0.37) % 1);
        const k = Math.floor(t * 47);
        const p = project(pts[k]);
        if (p.z > -0.25) {
          ctx.beginPath();
          ctx.fillStyle = "rgba(255,214,140,0.95)";
          ctx.arc(p.x, p.y, 2.4 * p.s, 0, Math.PI * 2);
          ctx.fill();
        }
      });

      ctx.font = "600 11px 'IBM Plex Mono', monospace";
      hubs.forEach((hub, i) => {
        const p = project(hub);
        if (p.z < 0) return;
        ctx.beginPath();
        ctx.fillStyle = "#5EC4B6";
        ctx.arc(p.x, p.y, 3.5 * p.s, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = `rgba(230,240,250,${0.35 + p.z * 0.6})`;
        ctx.fillText(HUBS[i].label, p.x + 7, p.y - 6);
      });
    };

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    const loop = (t: number) => {
      if (visible) draw(t);
      raf = requestAnimationFrame(loop);
    };
    if (!reduced) raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); };
  }, []);

  return <canvas ref={ref} className={className} aria-hidden="true" />;
}
