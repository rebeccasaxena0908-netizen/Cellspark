import { useEffect, useRef } from "react";

/**
 * BinaryRain — the falling code from the reference video.
 *
 * Each column falls at its own speed with a bright leading character and a
 * fading tail. The tail uses a power curve rather than linear falloff, which
 * makes columns read as streaks instead of dotted lines.
 */
export default function BinaryRain({ opacity = 0.55 }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const ctx = canvas.getContext("2d");
    let w = 0, h = 0, dpr = 1, cols = [], raf = 0;
    const SIZE = 13;
    const GAP = 22;

    function resize() {
      const rect = canvas.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = rect.width; h = rect.height;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const n = Math.floor(w / GAP);
      cols = Array.from({ length: n }, (_, i) => ({
        x: i * GAP + GAP / 2,
        y: Math.random() * h,
        speed: 0.3 + Math.random() * 1.0,
        len: 8 + Math.floor(Math.random() * 18),
        bits: Array.from({ length: 24 }, () => (Math.random() > 0.5 ? "1" : "0")),
        tick: 0,
      }));
    }

    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();

    function frame() {
      ctx.clearRect(0, 0, w, h);
      ctx.font = `500 ${SIZE}px "IBM Plex Mono", monospace`;
      ctx.textAlign = "center";

      for (const c of cols) {
        c.y += c.speed;
        if (c.y - c.len * SIZE > h) {
          c.y = -Math.random() * 140;
          c.speed = 0.3 + Math.random() * 1.0;
        }
        c.tick++;
        if (c.tick % 18 === 0) {
          c.bits[Math.floor(Math.random() * c.bits.length)] =
            Math.random() > 0.5 ? "1" : "0";
        }

        for (let k = 0; k < c.len; k++) {
          const y = c.y - k * SIZE;
          if (y < -SIZE || y > h + SIZE) continue;
          // power curve: slower falloff reads as a streak, not dots
          const fade = Math.pow(1 - k / c.len, 0.7);
          if (k < 2) {
            // leading characters burn near-white
            ctx.fillStyle = `rgba(215,248,255,${(fade * 1.15).toFixed(3)})`;
          } else {
            ctx.fillStyle = `rgba(80,205,255,${(fade * 0.95).toFixed(3)})`;
          }
          ctx.fillText(c.bits[k % c.bits.length], c.x, y);
        }
      }
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);

    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="absolute inset-0 h-full w-full pointer-events-none"
      style={{ opacity }}
    />
  );
}