import { Fragment, useState } from "react";
import { bandFor } from "../lib/mockApi";
import { Panel, Badge, focusRing } from "./ui";
import { SequenceChars, SequenceLegend } from "./SequenceLegend";
import { PassageRow } from "./Passages";
import { crossCheck } from "../lib/mockApi";
import { agretopicityOf } from "../lib/sequence";

/** Renders a peptide with the mutated residue highlighted. */
export function PeptideChars({ seq, mutPos }) {
  return <SequenceChars seq={seq} mutPos={mutPos} kind="protein" />;
}

const WEAK_AGRETOPICITY_LABEL =
  "Wild-type binds as tightly or tighter — the mutation did not create this " +
  "epitope, so T-cells for it may have been removed by central tolerance.";

/**
 * Marker for a candidate whose mutation did not improve binding.
 *
 * Deliberately a flag rather than a demotion: the row keeps its rank and its
 * position. Ranking is by IC50 because binding is the necessary condition for
 * presentation, and folding two different measurements into one score would
 * hide exactly the trade-off this marker exists to show.
 */
function WeakAgretopicityFlag() {
  return (
    <span
      title={WEAK_AGRETOPICITY_LABEL}
      className="inline-flex items-center gap-1 rounded border border-warn/35 bg-warn/12 px-1.5 py-0.5 text-[10px] font-medium text-warn"
    >
      <span aria-hidden="true">▲</span>
      <span className="sr-only">Warning: </span>
      below 1
    </span>
  );
}

/**
 * How the corpus covered this gene — a statement about the index, never
 * about the gene.
 *
 * The wording avoids "evidence" and "known target" deliberately. The index is
 * a few hundred abstracts; a gene can be among the most studied in oncology
 * and still be missing from it, so a miss here is a gap in CellSpark's
 * collection and nothing more.
 */
const COVERAGE = {
  well_covered: { tone: "ok", label: "Covered by the indexed corpus" },
  thin: { tone: "warn", label: "Thinly covered — few matching abstracts" },
  not_covered: { tone: "mute", label: "Not in the indexed corpus" },
  unavailable: { tone: "mute", label: "Lookup unavailable" },
};

function CoverageBadge({ coverage }) {
  const c = COVERAGE[coverage] || COVERAGE.unavailable;
  if (c.tone === "mute") {
    return (
      <span className="inline-block rounded-full border border-line bg-raised/60 px-2.5 py-1 text-[11px] font-medium whitespace-nowrap text-ink-mute">
        {c.label}
      </span>
    );
  }
  return <Badge tone={c.tone}>{c.label}</Badge>;
}

function CrossCheckPanel({ data, loading, gene }) {
  if (loading) {
    return (
      <div className="cs-inset px-4 py-3 text-sm text-ink-dim" aria-live="polite">
        Searching the indexed corpus for {gene}…
      </div>
    );
  }
  if (!data) return null;

  return (
    <div className="cs-inset px-4 py-4" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <CoverageBadge coverage={data.coverage} />
        {data.provider && data.provider !== "offline" && (
          <span className="cs-chip">{data.provider}</span>
        )}
      </div>

      <p className="mt-3 whitespace-pre-wrap text-[13px] leading-relaxed text-ink-dim">
        {data.summary}
      </p>

      {data.passages?.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {data.passages.map((p, i) => (
            <PassageRow key={`${p.pmid}-${i}`} passage={p} />
          ))}
        </ul>
      )}

      {/* Always visible, never behind a disclosure — a reader who misses this
          will over-read a hit just as easily as a miss. */}
      <p className="mt-3 border-t border-line pt-3 text-[12px] leading-relaxed text-ink-mute">
        {data.caveat}
      </p>
    </div>
  );
}

export default function TargetsTable({ targets, result }) {
  const [open, setOpen] = useState(null);
  // One lookup at a time: `busy` holds the rank being fetched, and every
  // button is disabled while it is set.
  const [busy, setBusy] = useState(null);
  const [checks, setChecks] = useState({});

  async function runCrossCheck(t) {
    if (busy !== null) return;
    setBusy(t.rank);
    setOpen(t.rank);
    const data = await crossCheck(t.gene, t.change, result);
    setChecks((c) => ({ ...c, [t.rank]: data }));
    setBusy(null);
  }

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

      <p className="border-b border-line px-5 py-3 text-[12.5px] leading-relaxed text-ink-mute">
        Agretopicity is wild-type IC50 divided by mutant IC50. Above 1 means the
        mutation improved binding; below 1 means it did not, and those rows are
        flagged rather than reordered.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-line text-[11px] uppercase tracking-wider text-ink-mute">
              <th className="px-5 py-3 font-medium">#</th>
              <th className="px-2 py-3 font-medium">Peptide</th>
              <th className="px-2 py-3 font-medium">Gene</th>
              <th className="px-2 py-3 font-medium">Allele</th>
              <th className="px-2 py-3 font-medium text-right">IC50 (nM)</th>
              <th className="px-2 py-3 font-medium text-right">Agretopicity</th>
              <th className="px-5 py-3 font-medium">Assessment</th>
            </tr>
          </thead>
          <tbody>
            {targets.map((t) => {
              const band = bandFor(t.ic50);
              const isOpen = open === t.rank;
              const agreto = agretopicityOf(t);
              const weak = agreto !== null && agreto < 1;
              return (
                <Fragment key={t.rank}>
                  <tr
                    onClick={() => setOpen(isOpen ? null : t.rank)}
                    className={`cursor-pointer border-b border-line/50 transition hover:bg-raised/45 ${
                      isOpen ? "bg-raised/55" : ""
                    }`}
                  >
                    <td className="px-5 py-3.5 font-mono tabular-nums text-ink-mute">{t.rank}</td>
                    <td className="px-2 py-3.5">
                      <PeptideChars seq={t.peptide} mutPos={t.mutPos} />
                    </td>
                    <td className="px-2 py-3.5">
                      <span className="font-medium">{t.gene}</span>
                      <span className="ml-2 font-mono text-xs text-ink-mute">{t.change}</span>
                    </td>
                    <td className="px-2 py-3.5 font-mono text-xs text-ink-dim">{t.allele}</td>
                    <td className="px-2 py-3.5 text-right font-mono tabular-nums font-medium">{t.ic50}</td>
                    <td className="px-2 py-3.5 text-right">
                      <span className="inline-flex items-center justify-end gap-2 whitespace-nowrap">
                        <span className={`font-mono tabular-nums ${weak ? "text-warn" : "text-ink"}`}>
                          {agreto === null ? "—" : agreto.toFixed(2)}
                        </span>
                        {/* The flag sits in a reserved slot of fixed width, present
                            whether or not the row is flagged, so adding a marker
                            never pushes the number it annotates out of column. */}
                        <span className="w-16 shrink-0 text-left">
                          {weak && <WeakAgretopicityFlag />}
                        </span>
                      </span>
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={band.tone}>{band.label}</Badge>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); runCrossCheck(t); }}
                          disabled={busy !== null}
                          aria-label={`Cross-check ${t.gene} ${t.change} against the indexed corpus`}
                          className={`whitespace-nowrap rounded-full border border-line px-2.5 py-1 text-[11px] text-ink-dim transition hover:border-cyan-core/55 hover:text-ink disabled:opacity-40 ${focusRing}`}
                        >
                          {busy === t.rank ? "Checking…" : "Cross-check"}
                        </button>
                      </div>
                    </td>
                  </tr>

                  {isOpen && (
                    <tr className="border-b border-line/50 bg-abyss/60">
                      <td colSpan={7} className="px-5 py-4">
                        <div className="grid gap-5 sm:grid-cols-3">
                          <div>
                            <p className="text-[11px] uppercase tracking-wider text-ink-mute">
                              Healthy version
                            </p>
                            <p className="mt-1">
                              <SequenceChars seq={t.wildtype} kind="protein" />
                            </p>
                            <p className="mt-1 font-mono tabular-nums text-xs text-ink-mute">scores {t.wtIc50} nM</p>
                          </div>
                          <div>
                            <p className="text-[11px] uppercase tracking-wider text-ink-mute">
                              Mutated version
                            </p>
                            <p className="mt-1">
                              <PeptideChars seq={t.peptide} mutPos={t.mutPos} />
                            </p>
                            <p className="mt-1 font-mono tabular-nums text-xs text-ink-mute">scores {t.ic50} nM</p>
                          </div>
                          <div>
                            <p className="text-[11px] uppercase tracking-wider text-ink-mute">
                              {weak ? "Why this one is flagged" : "Why it was kept"}
                            </p>
                            {weak ? (
                              <p className="mt-1 text-sm leading-relaxed text-ink-dim">
                                The healthy version binds{" "}
                                <span className="text-warn">
                                  {(t.ic50 / t.wtIc50).toFixed(1)}×
                                </span>{" "}
                                tighter than the mutated one, so the mutation did
                                not create this epitope. It is already displayed
                                on healthy cells, which means the T-cells that
                                would recognise it have probably been removed by
                                central tolerance — and targeting it carries an
                                autoimmunity risk. It keeps its rank because it
                                still binds well; the flag is the caveat.
                              </p>
                            ) : (
                              <p className="mt-1 text-sm leading-relaxed text-ink-dim">
                                The mutation improves binding{" "}
                                <span className="text-ink">
                                  {agreto === null ? "—" : `${agreto.toFixed(1)}×`}
                                </span>{" "}
                                over the healthy sequence, and this exact motif
                                does not occur anywhere in the human proteome.
                              </p>
                            )}
                          </div>
                        </div>

                        {(busy === t.rank || checks[t.rank]) && (
                          <div className="mt-5">
                            <p className="mb-2 text-[11px] uppercase tracking-wider text-ink-mute">
                              What the indexed corpus says about {t.gene}
                            </p>
                            <CrossCheckPanel
                              data={checks[t.rank]}
                              loading={busy === t.rank}
                              gene={t.gene}
                            />
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="px-5 pb-5 pt-1">
        <SequenceLegend />
      </div>
    </Panel>
  );
}
