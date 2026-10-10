/**
 * Shared sequence rendering and legend.
 *
 * Peptides and mRNA are shown as bare letter strings — KMVWSAWGI, AUGGCC.
 * That is unreadable to anyone who has not done biochemistry, which is most
 * people who will ever look at this. So every letter carries its name, and
 * one collapsed legend explains the whole alphabet in plain language.
 *
 * Grouped by chemical property rather than listed A to Z on purpose: the
 * groups are the part that is actually teachable. Whether a residue repels
 * water or carries a charge is what decides how a peptide sits in the MHC
 * groove, so the grouping carries real information that an alphabetical
 * lookup table does not.
 */
import { AMINO_GROUPS, RNA_BASES, describe } from "../lib/sequence";

/**
 * A sequence rendered one letter at a time, each naming itself on hover.
 *
 * Letters are spaced with letter-spacing rather than inserted characters, so
 * selecting the sequence and copying it yields exactly "KMVWSAWGI" — no
 * stray spaces to strip before pasting it into another tool.
 */
export function SequenceChars({ seq = "", mutPos = -1, kind = "protein", className = "" }) {
  const letters = String(seq).split("");
  const mutated = letters[mutPos];

  return (
    <span
      className={`font-mono tracking-[0.12em] ${className}`}
      // The per-letter titles are mouse-only, so the whole sequence also
      // states the substitution once, for anyone not using a pointer.
      aria-label={
        mutated
          ? `${seq}, mutated residue ${describe(mutated, kind)} at position ${mutPos + 1}`
          : seq
      }
    >
      {letters.map((c, i) => (
        <span
          key={i}
          title={
            i === mutPos
              ? `${describe(c, kind)} — the substituted residue`
              : describe(c, kind)
          }
          className={
            i === mutPos
              ? "rounded bg-cyan-core/25 font-semibold text-cyan-glow"
              : "text-ink-dim"
          }
        >
          {c}
        </span>
      ))}
    </span>
  );
}

function ResidueCell({ letter, code, name }) {
  return (
    <li className="flex items-baseline gap-2">
      <span className="w-4 shrink-0 font-mono text-cyan-glow">{letter}</span>
      <span className="w-8 shrink-0 font-mono text-[11px] text-ink-mute">{code}</span>
      <span className="min-w-0 text-ink-dim">{name}</span>
    </li>
  );
}

/**
 * Collapsed-by-default reference for both alphabets.
 *
 * <details> rather than React state: it is keyboard-operable natively, and
 * being closed on load means it cannot push the results down the page.
 */
export function SequenceLegend({ className = "" }) {
  return (
    <details className={`cs-inset group ${className}`}>
      <summary className="cursor-pointer list-none rounded-xl px-4 py-3 text-sm text-ink-dim transition hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-core">
        <span className="inline-flex items-center gap-2">
          <span
            aria-hidden="true"
            className="text-[10px] text-ink-mute transition-transform group-open:rotate-90"
          >
            ▶
          </span>
          What do these letters mean?
        </span>
      </summary>

      <div className="space-y-5 border-t border-line px-4 py-4 text-[13px] leading-relaxed">
        <p className="text-ink-dim">
          A protein is a chain of building blocks called amino acids. There are
          20 of them, and each is abbreviated to a single letter — so a peptide
          reads as a run of letters like{" "}
          <span className="font-mono text-ink">KMVWSAWGI</span>. The groups
          below sort them by the property that decides how a peptide behaves.
        </p>

        <div className="grid gap-5 sm:grid-cols-2">
          {AMINO_GROUPS.map((g) => (
            <div key={g.name}>
              <p className="cs-label-mono">{g.name}</p>
              <p className="mt-1 text-[12px] text-ink-mute">{g.gloss}</p>
              <ul className="mt-2 space-y-1">
                {g.residues.map(([letter, code, name]) => (
                  <ResidueCell key={letter} letter={letter} code={code} name={name} />
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="border-t border-line pt-4">
          <p className="cs-label-mono">RNA bases</p>
          <ul className="mt-2 grid gap-1 sm:grid-cols-2">
            {Object.entries(RNA_BASES).map(([letter, b]) => (
              <ResidueCell key={letter} letter={letter} code={b.code} name={b.name} />
            ))}
          </ul>

          <p className="mt-3 text-ink-dim">
            These are the letters of the mRNA sequence. Every three bases in a
            row make one <span className="text-ink">codon</span>, and each codon
            spells out a single amino acid — which is how the two halves of this
            legend connect: the mRNA below is the recipe, and the peptide above
            is what it builds.
          </p>
          <p className="mt-2 text-ink-dim">
            <span className="font-mono text-ink">AUG</span> is the codon that
            starts translation, and{" "}
            <span className="font-mono text-ink">UAA</span>,{" "}
            <span className="font-mono text-ink">UAG</span> or{" "}
            <span className="font-mono text-ink">UGA</span> stop it.
          </p>
        </div>
      </div>
    </details>
  );
}
