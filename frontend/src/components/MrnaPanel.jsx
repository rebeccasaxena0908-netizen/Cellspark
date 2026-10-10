import { useState } from "react";
import { Panel, Button } from "./ui";
import { SequenceChars, SequenceLegend } from "./SequenceLegend";

function Stat({ label, value, unit, tone }) {
  const tones = { ok: "text-ok", warn: "text-warn", alert: "text-alert" };
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wider text-ink-mute">{label}</p>
      <p className={`mt-1 font-display text-2xl font-semibold ${tones[tone] || "text-ink"}`}>
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-ink-dim">{unit}</span>}
      </p>
    </div>
  );
}

export default function MrnaPanel({ mrna }) {
  const [copied, setCopied] = useState(false);
  const rows = mrna.sequence.match(/.{1,60}/g) || [];

  const copy = async () => {
    await navigator.clipboard?.writeText(mrna.sequence);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const download = () => {
    const blob = new Blob(
      [`>CellSpark_optimised_mRNA len=${mrna.length} CAI=${mrna.cai}\n${rows.join("\n")}\n`],
      { type: "text/plain" }
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "cellspark_mrna.fasta";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Panel className="overflow-hidden">
      <div className="border-b border-line px-5 py-4">
        <h3 className="font-display text-lg font-semibold">Optimised mRNA</h3>
        <p className="mt-0.5 text-sm text-ink-dim">
          Built from the top-ranked target. The protein it encodes is unchanged
          — only the codons differ.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-5 px-5 py-5 sm:grid-cols-4">
        <Stat label="Length" value={mrna.length} unit="nt" />
        <Stat label="CAI" value={mrna.cai} tone="ok" />
        <Stat label="Uracil" value={mrna.uracil} unit="%" tone="ok" />
        <Stat label="GC" value={mrna.gc} unit="%" />
      </div>

      {/* before → after, so the optimisation is visible rather than asserted */}
      <div className="mx-5 mb-5 grid gap-2 rounded-lg border border-line bg-abyss/70 p-4 text-sm sm:grid-cols-2">
        <p className="text-ink-dim">
          Translation efficiency{" "}
          <span className="font-mono text-ink-mute line-through">{mrna.caiBefore}</span>{" "}
          <span className="text-ok">→ {mrna.cai}</span>
        </p>
        <p className="text-ink-dim">
          Uracil content{" "}
          <span className="font-mono text-ink-mute line-through">{mrna.uracilBefore}%</span>{" "}
          <span className="text-ok">→ {mrna.uracil}%</span>
        </p>
      </div>

      <div className="mx-5 mb-5 max-h-52 overflow-y-auto rounded-lg border border-line bg-void p-4">
        <pre className="font-mono text-[12.5px] leading-6 text-cyan-glow/85">
          {rows.map((r, i) => (
            <div key={i}>
              <span className="mr-3 select-none text-ink-mute">
                {String(i * 60 + 1).padStart(4, "0")}
              </span>
              <SequenceChars seq={r} kind="rna" className="text-cyan-glow/85" />
            </div>
          ))}
        </pre>
      </div>

      {mrna.protein && (
        <div className="mx-5 mb-5">
          <p className="text-[11px] uppercase tracking-wider text-ink-mute">
            Protein it encodes
          </p>
          <p className="mt-1.5 break-all text-[13px]">
            <SequenceChars seq={mrna.protein} kind="protein" />
          </p>
          <p className="mt-1.5 text-xs text-ink-mute">
            Every three bases above spell one of these letters. Hover any letter
            for its name.
          </p>
        </div>
      )}

      <div className="mx-5 mb-5">
        <SequenceLegend />
      </div>

      <div className="flex flex-wrap gap-3 border-t border-line px-5 py-4">
        <Button variant="ghost" onClick={copy}>
          {copied ? "Copied" : "Copy sequence"}
        </Button>
        <Button variant="ghost" onClick={download}>Download FASTA</Button>
      </div>
    </Panel>
  );
}