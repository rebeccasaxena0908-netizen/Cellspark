import DnaHelix from "./DnaHelix";
import { TIERS } from "../lib/constants";
import { Eyebrow } from "./ui";

export default function RunningStep({ tier, frac }) {
  const overall = (tier + frac) / TIERS.length;

  return (
    <div className="mx-auto max-w-4xl px-6 py-14">
      <Eyebrow>Step 2 of 3</Eyebrow>
      <h2 className="mt-3 font-display text-3xl font-semibold">Working through it</h2>
      <p className="mt-2 text-ink-dim">
        Each stage narrows the field. You can leave this open.
      </p>

      {/* the helix IS the progress bar — it lights up as work completes */}
      <div className="relative mt-8 h-56 overflow-hidden rounded-xl border border-line bg-abyss">
        <DnaHelix progress={overall} speed={1.6} />
        <div className="pointer-events-none absolute bottom-4 left-5 font-mono text-sm text-cyan-glow">
          {Math.round(overall * 100)}%
        </div>
      </div>

      <ol className="mt-8 space-y-3">
        {TIERS.map((t, i) => {
          const done = i < tier;
          const active = i === tier;
          return (
            <li
              key={t.id}
              className={`flex items-start gap-4 rounded-xl border p-4 transition ${
                active ? "border-cyan-core/55 bg-cyan-core/6"
                : done ? "border-line bg-panel/50"
                : "border-line/50 bg-transparent opacity-55"
              }`}
            >
              <span
                className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full border text-[12px] font-semibold ${
                  done ? "border-ok/50 bg-ok/15 text-ok"
                  : active ? "border-cyan-core bg-cyan-core/20 text-cyan-glow cs-pulse"
                  : "border-line text-ink-mute"
                }`}
              >
                {done ? "✓" : t.id}
              </span>

              <div className="min-w-0 flex-1">
                <p className={`font-medium ${active ? "text-ink" : "text-ink-dim"}`}>
                  {t.name}
                </p>
                <p className="mt-0.5 text-sm text-ink-mute">{t.detail}</p>

                {active && (
                  <div className="mt-3 h-1 overflow-hidden rounded-full bg-raised">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-cyan-core to-violet-core transition-[width] duration-150"
                      style={{ width: `${frac * 100}%` }}
                    />
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}