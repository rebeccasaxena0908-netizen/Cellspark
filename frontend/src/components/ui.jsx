export function Panel({ children, className = "", ...rest }) {
  return (
    <div
      className={`rounded-xl border border-line bg-panel/80 backdrop-blur-sm ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

export function Button({ variant = "primary", className = "", ...rest }) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg px-5 py-3 text-[15px] font-medium transition disabled:opacity-40 disabled:cursor-not-allowed";
  const styles = {
    primary:
      "bg-cyan-core text-void hover:bg-cyan-glow shadow-[0_0_28px_-6px_rgba(56,189,248,.65)]",
    ghost:
      "border border-line text-ink-dim hover:text-ink hover:border-cyan-core/60 hover:bg-raised/40",
  };
  return <button className={`${base} ${styles[variant]} ${className}`} {...rest} />;
}

export function Eyebrow({ children }) {
  return (
    <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-ink-mute">
      {children}
    </p>
  );
}

export function Badge({ tone = "ok", children }) {
  const tones = {
    ok:    "bg-ok/12 text-ok border-ok/35",
    warn:  "bg-warn/12 text-warn border-warn/35",
    alert: "bg-alert/12 text-alert border-alert/35",
    info:  "bg-cyan-core/12 text-cyan-glow border-cyan-core/35",
  };
  return (
    <span className={`inline-block rounded-full border px-2.5 py-1 text-[11px] font-medium whitespace-nowrap ${tones[tone]}`}>
      {children}
    </span>
  );
}