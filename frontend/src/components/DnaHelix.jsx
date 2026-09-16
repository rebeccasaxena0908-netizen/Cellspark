import { useEffect, useRef } from "react";

/**
 * DnaHelix — the signature element.
 *
 * A double helix locked to a fixed diagonal, rotating about its own axis so
 * base pairs sweep front-to-back. The axis never moves, which is what keeps
 * it slanted.
 *
 * HOW THE 3D LOOK IS BUILT (all 2D canvas, no WebGL):
 *
 *   position   offset = AMP * sin(angle)      where the point sits
 *   depth      cos(angle)                     how near the viewer it is
 *
 * Depth drives radius, brightness, opacity and draw order. On top of that:
 *
 *   - the backbone is a BEADED TUBE: overlapping circles whose radius is
 *     modulated sinusoidally, so individual sugar-phosphate units bulge
 *   - each bead gets an offset specular highlight, which is what makes it
 *     read as a sphere rather than a flat dot
 *   - base pairs are short STUBS projecting inward from each strand rather
 *     than one bar spanning the gap
 *   - bloom comes from a second canvas drawing the same frame under a CSS
 *     blur. CSS filter is GPU-accelerated, far cheaper than per-shape
 *     shadowBlur on ~1000 circles.
 *
 * Geometry is derived from the container rather than fixed in pixels — a
 * radius that looks right in a 400px box vanishes in a full viewport.
 */
export default function DnaHelix({ progress = 1, speed = 1, compact = false }) {
  const glowRef = useRef(null);
  const mainRef = useRef(null);
  const rafRef = useRef(0);
  const phaseRef = useRef(1.2);
  const progressRef = useRef(progress);

  useEffect(() => { progressRef.current = progress; }, [progress]);

  useEffect(() => {
    const glowCanvas = glowRef.current;
    const mainCanvas = mainRef.current;
    if (!glowCanvas || !mainCanvas) return;

    const gctx = glowCanvas.getContext("2d");
    const mctx = mainCanvas.getContext("2d");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const SLANT = (-24 * Math.PI) / 180;      // fixed tilt — never animated
    const AMP_RATIO = compact ? 0.34 : 0.30;  // radius as a share of height
    const TURNS = compact ? 2.2 : 3.4;        // full turns across the span
    const NODES = compact ? 220 : 480;
    const RUNGS = compact ? 18 : 34;
    const BEAD = compact ? 150 : 300;         // beading frequency along the tube

    // Strand palettes, sampled from the reference video
    const CY = [90, 200, 255];
    const VI = [178, 140, 250];

    let width = 0, height = 0, dpr = 1;

    function resize() {
      const rect = mainCanvas.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = rect.width;
      height = rect.height;
      for (const [c, ctx] of [[glowCanvas, gctx], [mainCanvas, mctx]]) {
        c.width = Math.round(width * dpr);
        c.height = Math.round(height * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
    }

    const ro = new ResizeObserver(resize);
    ro.observe(mainCanvas);
    resize();

    /** Colour for a point, drifting gently along the length. */
    function strandColor(u, strand, depth, lit) {
      const m = 0.5 + 0.5 * Math.sin(u * Math.PI * 1.6 + (strand ? 2.4 : 0));
      const a = strand ? VI : CY;
      const b = strand ? CY : VI;
      // small crossover only — each strand keeps its identity
      const c = a.map((ch, i) => ch * (1 - m * 0.28) + b[i] * (m * 0.28));
      const k = lit ? 0.78 + 0.32 * depth : 0.30 + 0.20 * depth;
      return c.map((ch) => Math.min(255, Math.round(ch * k)));
    }

    function draw() {
      const phase = phaseRef.current;
      const prog = progressRef.current;
      const cx = width / 2;
      const cy = height / 2;
      const ca = Math.cos(SLANT);
      const sa = Math.sin(SLANT);

      const L = Math.min(width * 1.15, compact ? 320 : 1600);
      const AMP = Math.max(
        compact ? 26 : 70,
        Math.min(height * AMP_RATIO, compact ? 60 : 190)
      );
      const FREQ = (TURNS * 2 * Math.PI) / L;  // exactly TURNS across the span

      gctx.clearRect(0, 0, width, height);
      mctx.clearRect(0, 0, width, height);

      const project = (t, off) => [cx + t * ca - off * sa, cy + t * sa + off * ca];

      const items = [];

      for (let i = 0; i < NODES; i++) {
        const t = -L / 2 + (L * i) / (NODES - 1);
        const u = i / (NODES - 1);
        const a = t * FREQ + phase;
        for (let s = 0; s < 2; s++) {
          const ang = a + (s ? Math.PI : 0);
          items.push({ kind: "node", depth: (Math.cos(ang) + 1) / 2, t, ang, s, u });
        }
      }

      for (let i = 0; i < RUNGS; i++) {
        const t = -L / 2 + (L * i) / (RUNGS - 1);
        const u = i / (RUNGS - 1);
        const a = t * FREQ + phase;
        // skip rungs at strand crossings, where they'd have no length
        if (Math.abs(Math.sin(a) - Math.sin(a + Math.PI)) < 0.55) continue;
        items.push({ kind: "rung", depth: (Math.cos(a) + 1) / 2, t, ang: a, u });
      }

      items.sort((p, q) => p.depth - q.depth);   // painter's algorithm

      for (const it of items) {
        const lit = it.u <= prog;

        if (it.kind === "rung") {
          const p1 = project(it.t, AMP * Math.sin(it.ang));
          const p2 = project(it.t, AMP * Math.sin(it.ang + Math.PI));

          // two stubs, each reaching 41% of the way across
          for (const [pa, pb, sc] of [[p1, p2, 0], [p2, p1, 1]]) {
            const ex = [
              pa[0] + (pb[0] - pa[0]) * 0.41,
              pa[1] + (pb[1] - pa[1]) * 0.41,
            ];
            const [r, g, b] = strandColor(it.u, sc, it.depth * 0.8, lit);
            const w = AMP * 0.055 * (0.55 + 0.45 * it.depth);
            const alpha = (0.42 + 0.55 * it.depth) * (lit ? 1 : 0.5);

            for (const ctx of [gctx, mctx]) {
              ctx.beginPath();
              ctx.moveTo(pa[0], pa[1]);
              ctx.lineTo(ex[0], ex[1]);
              ctx.lineWidth = w;
              ctx.lineCap = "round";
              ctx.strokeStyle = `rgba(${r},${g},${b},${alpha})`;
              ctx.stroke();
            }
          }
        } else {
          const [x, y] = project(it.t, AMP * Math.sin(it.ang));
          const [r, g, b] = strandColor(it.u, it.s, it.depth, lit);
          // beading: radius pulses so individual units bulge
          const bead = 0.86 + 0.2 * Math.sin(it.u * BEAD);
          const rad = AMP * 0.085 * (0.62 + 0.38 * it.depth) * bead;
          const alpha = (0.62 + 0.38 * it.depth) * (lit ? 1 : 0.42);

          for (const ctx of [gctx, mctx]) {
            ctx.beginPath();
            ctx.arc(x, y, rad, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
            ctx.fill();
          }

          // specular highlight — what makes a circle read as a sphere
          if (lit && it.depth > 0.25) {
            const hr = rad * 0.34;
            const hl = [r, g, b].map((c) =>
              Math.min(255, Math.round(c * 0.72 + 255 * 0.28))
            );
            mctx.beginPath();
            mctx.arc(x - rad * 0.32, y - rad * 0.34, hr, 0, Math.PI * 2);
            mctx.fillStyle = `rgba(${hl[0]},${hl[1]},${hl[2]},${alpha * 0.55})`;
            mctx.fill();
          }
        }
      }
    }

    function frame() {
      // negative = the helix appears to travel up-right along its own axis
      phaseRef.current -= 0.006 * speed;
      draw();
      rafRef.current = requestAnimationFrame(frame);
    }

    if (reduced) draw();
    else rafRef.current = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
    };
  }, [speed, compact]);

  return (
    <div className="relative h-full w-full" aria-hidden="true">
      {/* bloom pass — same frame, blurred and screened underneath */}
      <canvas
        ref={glowRef}
        className="absolute inset-0 h-full w-full"
        style={{
          filter: `blur(${compact ? 8 : 30}px)`,
          opacity: 1.25,
          mixBlendMode: "screen",
        }}
      />
      {/* crisp pass */}
      <canvas ref={mainRef} className="absolute inset-0 h-full w-full" />
    </div>
  );
}