/**
 * LogoMark — a small, crisp DNA helix drawn as SVG.
 *
 * The canvas DnaHelix is built for large hero rendering; squeezed into a
 * 36px box it shows less than half a turn and reads as a blob. This is a
 * separate mark, tuned so two full turns and their base pairs are legible
 * at 32-44px.
 *
 * Geometry is computed rather than hardcoded so the proportions can be
 * tuned in one place.
 */
export default function LogoMark({ size = 34, className = "" }) {
  const W = 44;
  const H = 34;
  const cx = W / 2;
  const cy = H / 2;
  const AMP = 9.5;
  const TURNS = 2;
  const L = 34;
  const SLANT = (-22 * Math.PI) / 180;
  const ca = Math.cos(SLANT);
  const sa = Math.sin(SLANT);

  const proj = (t, off) => [cx + t * ca - off * sa, cy + t * sa + off * ca];

  const strandPath = (phase) => {
    const n = 44;
    let d = "";
    for (let i = 0; i < n; i++) {
      const t = -L / 2 + (L * i) / (n - 1);
      const a = (t / L) * TURNS * 2 * Math.PI + phase;
      const [x, y] = proj(t, AMP * Math.sin(a));
      d += `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)} `;
    }
    return d.trim();
  };

  // Base pairs, skipping the ones at strand crossings where the two points
  // coincide and the rung would have zero length.
  const rungs = [];
  const N = 17;
  for (let i = 0; i < N; i++) {
    const t = -L / 2 + (L * i) / (N - 1);
    const a = (t / L) * TURNS * 2 * Math.PI;
    const o1 = AMP * Math.sin(a);
    const o2 = AMP * Math.sin(a + Math.PI);
    if (Math.abs(o1 - o2) < AMP * 0.5) continue; // too near a crossing
    const [x1, y1] = proj(t, o1);
    const [x2, y2] = proj(t, o2);
    const depth = (Math.cos(a) + 1) / 2;
    rungs.push({ x1, y1, x2, y2, depth, key: i });
  }

  return (
    <svg
      width={size * (W / H)}
      height={size}
      viewBox={`0 0 ${W} ${H}`}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      role="img"
      aria-label="CellSpark"
    >
      <defs>
        <linearGradient id="csStrandA" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#38BDF8" />
          <stop offset="100%" stopColor="#7DD3FC" />
        </linearGradient>
        <linearGradient id="csStrandB" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#A78BFA" />
          <stop offset="100%" stopColor="#C4A9F5" />
        </linearGradient>
        <filter id="csGlow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="1.4" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <g filter="url(#csGlow)">
        {rungs.map((r) => (
          <line
            key={r.key}
            x1={r.x1}
            y1={r.y1}
            x2={r.x2}
            y2={r.y2}
            stroke="#8FA8E8"
            strokeWidth={0.9 + 0.7 * r.depth}
            strokeLinecap="round"
            opacity={0.25 + 0.45 * r.depth}
          />
        ))}
        <path
          d={strandPath(0)}
          stroke="url(#csStrandA)"
          strokeWidth="2.1"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d={strandPath(Math.PI)}
          stroke="url(#csStrandB)"
          strokeWidth="2.1"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
    </svg>
  );
}