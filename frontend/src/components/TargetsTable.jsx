import { Fragment, useState } from "react";
import { bandFor } from "../lib/mockApi";
import { Panel, Badge } from "./ui";

/** Renders a peptide with the mutated residue highlighted. */
export function PeptideChars({ seq, mutPos }) {
  return (
    <span className="font-mono tracking-wide">
      {seq.split("").map((c, i) => (
        <span
          key={i}
          className={
            i === mutPos
              ? "rounded bg-violet-core/25 px-0.5 font-semibold text-violet-glow"
              : ""
          }
        >
          {c}
        </span>
      ))}
    </span>
  );
}

export default function TargetsTable({ targets }) {
  const [open, setOpen] = useState(null);

  return (
    <Panel className="overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-5 py-4">
        <div>
          <h3 className="font-display text-lg font-semibold">Ranked targets</h3>
          <p className="mt-0.5 text-sm text-ink-dim">
            Sorted by predicted binding strength. Lower IC50 binds tighter.
          </p>
        </div>
        <Badge tone="info">{targets.length} candidates</Badge>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-line text-[11px] uppercase tracking-wider text-ink-mute">
              <th className="px-5 py-3 font-medium">#</th>
              <th className="px-3 py-3 font-medium">Peptide</th>
              <th className="px-3 py-3 font-medium">Gene</th>
              <th className="px-3 py-3 font-medium">Allele</th>
              <th className="px-3 py-3 font-medium text-right">IC50 (nM)</th>
              <th className="px-5 py-3 font-medium">Assessment</th>
            </tr>
          </thead>
          <tbody>
            {targets.map((t) => {
              const band = bandFor(t.ic50);
              const isOpen = open === t.rank;
              return (
                <Fragment key={t.rank}>
                  <tr
                    onClick={() => setOpen(isOpen ? null : t.rank)}
                    className={`cursor-pointer border-b border-line/50 transition hover:bg-raised/45 ${
                      isOpen ? "bg-raised/55" : ""
                    }`}
                  >
                    <td className="px-5 py-3.5 font-mono text-ink-mute">{t.rank}</td>
                    <td className="px-3 py-3.5">
                      <PeptideChars seq={t.peptide} mutPos={t.mutPos} />
                    </td>
                    <td className="px-3 py-3.5">
                      <span className="font-medium">{t.gene}</span>
                      <span className="ml-2 font-mono text-xs text-ink-mute">{t.change}</span>
                    </td>
                    <td className="px-3 py-3.5 font-mono text-xs text-ink-dim">{t.allele}</td>
                    <td className="px-3 py-3.5 text-right font-mono font-medium">{t.ic50}</td>
                    <td className="px-5 py-3.5">
                      <Badge tone={band.tone}>{band.label}</Badge>
                    </td>
                  </tr>

                  {isOpen && (
                    <tr className="border-b border-line/50 bg-abyss/60">
                      <td colSpan={6} className="px-5 py-4">
                        <div className="grid gap-5 sm:grid-cols-3">
                          <div>
                            <p className="text-[11px] uppercase tracking-wider text-ink-mute">
                              Healthy version
                            </p>
                            <p className="mt-1 font-mono text-ink-dim">{t.wildtype}</p>
                            <p className="mt-1 text-xs text-ink-mute">scores {t.wtIc50} nM</p>
                          </div>
                          <div>
                            <p className="text-[11px] uppercase tracking-wider text-ink-mute">
                              Mutated version
                            </p>
                            <p className="mt-1">
                              <PeptideChars seq={t.peptide} mutPos={t.mutPos} />
                            </p>
                            <p className="mt-1 text-xs text-ink-mute">scores {t.ic50} nM</p>
                          </div>
                          <div>
                            <p className="text-[11px] uppercase tracking-wider text-ink-mute">
                              Why it was kept
                            </p>
                            <p className="mt-1 text-sm leading-relaxed text-ink-dim">
                              The mutation improves binding{" "}
                              <span className="text-ink">
                                {(t.wtIc50 / t.ic50).toFixed(1)}×
                              </span>{" "}
                              over the healthy sequence, and this exact motif
                              does not occur anywhere in the human proteome.
                            </p>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}