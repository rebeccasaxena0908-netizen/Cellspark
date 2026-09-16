import DnaHelix from "./DnaHelix";
import { Button, Eyebrow } from "./ui";

export default function Hero({ onStart }) {
  return (
    <section className="relative min-h-[100dvh] overflow-hidden">
      {/* Helix confined to the right 62% so it doesn't run under the copy */}
      <div className="absolute inset-y-0 right-[-12%] w-[62%] opacity-95">
        <DnaHelix speed={1} progress={1} />
      </div>

      {/* Scrim covers only the text column. Full-width scrims kill the
          binary rain on the right, which is where it should be visible. */}
      <div className="absolute inset-y-0 left-0 w-[62%] bg-gradient-to-r from-void via-void/80 to-transparent" />
      <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-void/80 to-transparent" />

      <div className="relative mx-auto flex min-h-[100dvh] max-w-6xl flex-col justify-center px-6 py-20">
        <div className="max-w-xl cs-fade-up">
          <Eyebrow>Neoantigen vaccine design · research use only</Eyebrow>

          <h1 className="mt-5 font-display text-5xl leading-[1.05] font-bold tracking-tight sm:text-6xl md:text-7xl">
            <span className="text-ink">Cell</span>
            <span className="bg-gradient-to-r from-cyan-glow to-violet-glow bg-clip-text text-transparent">
              Spark
            </span>
          </h1>

          <p className="mt-6 text-xl leading-relaxed text-ink-dim sm:text-2xl">
            Upload a patient's tumour mutation file. Get back a ranked set of
            vaccine targets and a synthesis-ready mRNA sequence, with the
            reasoning written out in plain language.
          </p>

          <p className="mt-4 text-[15px] leading-relaxed text-ink-mute">
            Four steps run automatically: find the mutations, work out which
            ones the patient's immune system can actually see, engineer a
            stable mRNA sequence, then summarise what came out and why.
          </p>

          <div className="mt-10 flex flex-wrap items-center gap-4">
            <Button onClick={onStart}>Start a new analysis</Button>
            <Button variant="ghost" onClick={onStart}>
              Try the sample patient
            </Button>
          </div>

          <p className="mt-10 max-w-lg border-l-2 border-warn/45 pl-4 text-[13px] leading-relaxed text-ink-mute">
            CellSpark supports research and design decisions. Outputs are
            predictions and require laboratory validation before any clinical
            use.
          </p>
        </div>
      </div>
    </section>
  );
}