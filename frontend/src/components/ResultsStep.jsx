import { Panel, Button, Eyebrow, Badge } from "./ui";
import TargetsTable from "./TargetsTable";
import MrnaPanel from "./MrnaPanel";
import FormulationPanel from "./FormulationPanel";
import Copilot from "./Copilot";

function Stat({ label, value }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wider text-ink-mute">{label}</p>
      <p className="mt-1 font-display text-2xl font-semibold text-ink">{value}</p>
    </div>
  );
}

/** "11 Oct 2026, 21:56" in the viewer's locale. */
function formatRunDate(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export default function ResultsStep({ result, onRestart, onBack }) {
  const { stats, targets, mrna, benchmark, reopened } = result;
  const top = targets[0];

  return (
    <div className="mx-auto max-w-6xl px-6 py-12 cs-fade-up">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          {reopened ? (
            // History, not a run that just happened.
            <p className="flex flex-wrap items-center gap-2">
              <Badge tone="info">Saved run</Badge>
              <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-ink-mute">
                Ran {formatRunDate(reopened.startedAt)}
              </span>
            </p>
          ) : (
            <Eyebrow>Step 3 of 3 · complete</Eyebrow>
          )}
          <h2 className="mt-3 font-display text-3xl font-semibold">Results</h2>
          <p className="mt-2 text-ink-dim">
            <span className="font-mono text-ink">{result.fileName}</span> ·{" "}
            {result.alleles.join(", ")}
            {result.algorithm && (
              <> · screened with <span className="text-ink">{result.algorithm}</span></>
            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          {onBack && <Button variant="ghost" onClick={onBack}>Back to history</Button>}
          <Button variant="ghost" onClick={onRestart}>New analysis</Button>
        </div>
      </div>

      {result.unavailableNote && (
        <p role="note" className="mt-6 rounded-lg border border-warn/40 bg-warn/8 p-4 text-sm text-ink-dim">
          {result.unavailableNote}
        </p>
      )}

      {/* the single answer, before any detail */}
      {top && <Panel className="mt-8 p-5">
        <p className="text-[11px] uppercase tracking-wider text-ink-mute">
          Leading candidate
        </p>
        <p className="mt-2 font-mono text-3xl text-cyan-glow">{top.peptide}</p>
        <p className="mt-2 text-ink-dim">
          from <span className="text-ink">{top.gene}</span>{" "}
          <span className="font-mono text-sm">{top.change}</span>, binding{" "}
          <span className="text-ink">{top.allele}</span> at{" "}
          <span className="text-ink">{top.ic50} nM</span>
        </p>
      </Panel>}

      {/* the funnel: three billion characters down to ten targets */}
      <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-5">
        {[
          ["Variants read", stats.variantsRead],
          ["Missense", stats.missense],
          ["Peptides built", stats.candidates],
          ["Matched self", stats.selfRejected],
          ["Scored", stats.screened],
        ].map(([label, v]) => (
          <Panel key={label} className="p-5">
            <Stat label={label} value={v.toLocaleString()} />
          </Panel>
        ))}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        {/* min-w-0: a grid item defaults to min-width:auto, so without this it
            refuses to shrink below the targets table's min-content width and
            the whole page scrolls sideways on a phone. */}
        <div className="min-w-0 space-y-6 lg:col-span-2">
          <TargetsTable targets={targets} result={result} />
          {mrna && <MrnaPanel mrna={mrna} />}
          {/* Tier 5 sits under the mRNA panel: it formulates what that panel
              shows. Needs a saved run, because the server formulates the
              construct it stored rather than one sent from here. */}
          {mrna && result.apiRaw?.run_id && (
            <FormulationPanel runId={result.apiRaw.run_id} />
          )}

          <Panel className="p-5">
            <h3 className="font-display text-lg font-semibold">Search performance</h3>
            <p className="mt-1 text-sm text-ink-dim">
              Time to screen one peptide against the reference proteome.
            </p>
            <div className="mt-4 space-y-3">
              {benchmark.map((b) => {
                const max = Math.max(...benchmark.map((x) => x.ms));
                return (
                  <div key={b.algo}>
                    <div className="flex justify-between text-sm">
                      <span className="text-ink-dim">{b.algo}</span>
                      <span className="font-mono">{b.ms} ms</span>
                    </div>
                    <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-raised">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-cyan-core to-violet-core"
                        style={{ width: `${(b.ms / max) * 100}%` }}
                      />
                    </div>
                    <p className="mt-1 text-xs text-ink-mute">{b.note}</p>
                  </div>
                );
              })}
            </div>
          </Panel>
        </div>

        <div className="min-w-0 lg:col-span-1">
          <Copilot result={result} />
        </div>
      </div>

      {/* Honest labelling of what's computed vs simulated. Keep this until
          every tier is genuinely implemented. */}
      {result.real && (
        <Panel className="mt-8 p-5">
          <h3 className="font-display text-lg font-semibold">What produced these numbers</h3>
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            {[
              ["Genomic search and tolerance screening", result.real.tier1],
              ["Binding affinity prediction", result.real.tier2],
              ["mRNA codon optimisation", result.real.tier3],
              ["Clinical summary", result.real.tier4],
            ].map(([label, isReal]) => (
              <div key={label} className="flex items-center gap-2.5 text-sm">
                <Badge tone={isReal ? "ok" : "warn"}>
                  {isReal ? "Computed" : "Simulated"}
                </Badge>
                <span className="text-ink-dim">{label}</span>
              </div>
            ))}
          </div>
          {result.proteome && (
            <p className="mt-4 border-t border-line pt-3 text-sm text-ink-mute">
              Screened against {result.proteome.proteins.toLocaleString()} proteins
              ({result.proteome.residues.toLocaleString()} residues), generating{" "}
              {result.peptidesPerMutation} peptides per mutation.
            </p>
          )}
        </Panel>
      )}

      <p className="mt-10 border-l-2 border-warn/45 pl-4 text-[13px] leading-relaxed text-ink-mute">
        These are computational predictions intended to prioritise laboratory
        work. They are not a diagnosis and not a treatment recommendation.
      </p>
    </div>
  );
}