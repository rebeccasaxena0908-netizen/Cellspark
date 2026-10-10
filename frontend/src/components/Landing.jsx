import { useEffect, useRef, useState } from "react";

/**
 * Landing page.
 *
 * One screen, nothing below it: nav, hero, and the measured-figures bar sitting
 * flush on the bottom edge.
 *
 * Layout note — the page is a flex column pinned to the viewport height. The
 * hero takes `flex-1` so it absorbs whatever space is left over, and the stat
 * bar is `shrink-0`, so the bar always lands on the bottom edge at any window
 * size with no gap under it and no scroll. On a phone, where the stacked copy
 * can be taller than the screen, `min-h` lets it scroll rather than clip.
 *
 * Self-contained by design: imports nothing from ./ui or ./DnaHelix, so it can
 * be dropped in without touching any other component. The only prop is
 * onStart(), which App.jsx uses to switch from "hero" to "upload".
 */

/* Measured results from a real run against the UniProt Swiss-Prot human
   proteome — not synopsis estimates. */
const HERO_STATS = [
  ["20,431", "Reference proteins screened"],
  ["4", "Tiers, end to end"],
  ["618", "PubMed abstracts indexed"],
  ["1.00", "Codon adaptation index"],
];

/* ========================================================================== */
/*  Building blocks                                                           */
/* ========================================================================== */

/** Reveals children on mount / when scrolled into view. */
function Reveal({ children, delay = 0, className = "" }) {
  const ref = useRef(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true);
          io.disconnect();
        }
      },
      { rootMargin: "0px 0px -12% 0px", threshold: 0.12 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={`cs-reveal ${className}`}
      data-shown={shown ? "true" : "false"}
      style={{ animationDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}

function CTA({ children, onClick, variant = "solid" }) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-xl px-6 py-3 text-sm font-semibold " +
    "transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-core/70 " +
    "focus-visible:ring-offset-2 focus-visible:ring-offset-void";

  const styles =
    variant === "solid"
      ? "bg-cyan-core text-void shadow-[0_10px_34px_-12px_rgba(56,189,248,0.85)] hover:bg-cyan-glow hover:shadow-[0_14px_42px_-12px_rgba(56,189,248,1)] hover:-translate-y-0.5"
      : "border border-line text-ink hover:border-cyan-core/60 hover:text-cyan-glow hover:-translate-y-0.5";

  return (
    <button type="button" onClick={onClick} className={`${base} ${styles}`}>
      {children}
    </button>
  );
}

/* ========================================================================== */
/*  Page                                                                      */
/* ========================================================================== */

export default function Landing({ onStart }) {
  return (
    <div className="relative flex min-h-[100dvh] flex-col text-ink">
      {/* Fixed ambient light behind everything */}
      <div className="cs-aurora" aria-hidden="true" />

      {/* ------------------------------------------------------------ Nav */}
      {/* Sits over the video rather than above it, so the helix runs the full
          height of the screen. Nothing scrolls, so no scroll state is needed. */}
      <header className="absolute inset-x-0 top-0 z-50">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
          <div className="flex items-center gap-3">
            <span className="cs-glow-ring inline-block size-2.5 rotate-45 bg-cyan-core" />
            <span className="font-display text-[17px] font-semibold tracking-tight">
              CellSpark
            </span>
          </div>

          <button
            type="button"
            onClick={onStart}
            className="rounded-lg border border-cyan-core/45 px-4 py-2 text-[13px] font-medium text-cyan-glow transition-colors hover:bg-cyan-core/10"
          >
            Open the studio
          </button>
        </div>
      </header>

      {/* ----------------------------------------------------------- Hero */}
      {/*
        Composition note: in the source video the DNA helix sits in the
        BOTTOM-LEFT of the frame. So the video is pinned to its bottom-left
        corner (object-position 0% 100%) — the helix survives any crop at any
        window width — and the copy is placed in the RIGHT half with the scrim
        weighted to that side. Text and helix never overlap.
      */}
      <section className="relative isolate z-10 flex flex-1 flex-col overflow-hidden">
        <video
          className="absolute inset-0 -z-20 h-full w-full object-cover"
          style={{
            objectPosition: "0% 100%",
            // Anchored at the bottom-left and zoomed slightly, so the helix is
            // larger and lifted clear of the stat bar.
            transform: "scale(1.22) translateY(-7%)",
            transformOrigin: "0% 100%",
            filter: "brightness(1.18) saturate(1.12)",
          }}
          src="/dna-loop.mp4"
          poster="/dna-poster.jpg"
          autoPlay
          muted
          loop
          playsInline
          preload="auto"
          aria-hidden="true"
        />

        {/* Scrim: dense on the right under the copy, clear on the left so the
            helix reads. On small screens the columns stack, so a flat scrim
            takes over instead (see the second layer). */}
        <div
          className="absolute inset-0 -z-10 hidden lg:block"
          style={{
            background:
              "linear-gradient(to left, rgba(4,7,14,0.97) 0%, rgba(4,7,14,0.95) 38%, rgba(4,7,14,0.78) 55%, rgba(4,7,14,0.34) 76%, rgba(4,7,14,0.12) 100%)",
          }}
        />
        <div className="absolute inset-0 -z-10 bg-void/82 lg:hidden" aria-hidden="true" />
        {/* Top and bottom fades so the nav and the stat bar both sit on solid
            ground rather than on moving video. */}
        <div
          className="absolute inset-0 -z-10"
          style={{
            background:
              "linear-gradient(to bottom, rgba(4,7,14,0.92) 0%, transparent 20%, transparent 70%, rgba(4,7,14,0.45) 90%, rgba(4,7,14,0.95) 100%)",
          }}
        />
        <div className="cs-grid-fade absolute inset-0 -z-10" aria-hidden="true" />

        {/* flex-1 — this block absorbs all leftover height, which is what keeps
            the stat bar welded to the bottom edge. */}
        <div className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 items-center gap-8 px-6 pb-10 pt-24 lg:grid-cols-12 lg:pb-12 lg:pt-20">
          {/* Left column is deliberately empty on desktop — it is the window
              the helix shows through. */}
          <div className="hidden lg:col-span-5 lg:block" aria-hidden="true" />

          <div className="lg:col-span-7">
            <Reveal>
              <div className="inline-flex items-center gap-2.5 rounded-full border border-line bg-panel/70 px-3.5 py-1.5 backdrop-blur-sm">
                <span className="cs-pulse size-1.5 rounded-full bg-ok" />
                <span className="font-mono text-[11px] tracking-[0.18em] text-ink-dim">
                  ALL FOUR TIERS RUNNING ON REAL DATA
                </span>
              </div>
            </Reveal>

            <Reveal delay={90}>
              <h1 className="mt-6 font-display text-[2.4rem] font-semibold leading-[1.06] md:text-[3.4rem] xl:text-[3.9rem]">
                A compiler for personalised{" "}
                <span className="cs-gradient-text">mRNA cancer vaccines</span>
              </h1>
            </Reveal>

            <Reveal delay={170}>
              <p className="mt-6 max-w-xl text-[15px] leading-relaxed text-ink-dim md:text-lg">
                Upload a tumour mutation file. CellSpark finds the mutations the
                immune system can see, ranks them, and writes the optimised mRNA
                sequence that would teach T-cells to attack that specific tumour —
                in one pass.
              </p>
            </Reveal>

            <Reveal delay={250}>
              <div className="mt-8 flex flex-wrap items-center gap-4">
                <CTA onClick={onStart}>
                  Start a new analysis
                  <span aria-hidden="true">→</span>
                </CTA>
                <CTA variant="ghost" onClick={onStart}>
                  Run the sample patient
                </CTA>
              </div>
            </Reveal>

            <Reveal delay={330}>
              <p className="mt-6 font-mono text-[11px] leading-relaxed text-ink-mute">
                MAF in · ranked neoantigens and a synthesis-ready construct out
              </p>
            </Reveal>
          </div>
        </div>

        {/* Stat floor — shrink-0 so it keeps its natural height and stays
            welded to the bottom edge of the screen. */}
        <div className="relative shrink-0 border-t border-line/70 bg-void/70 backdrop-blur-xl">
          <dl className="mx-auto grid max-w-7xl grid-cols-2 divide-line/70 px-6 md:grid-cols-4 md:divide-x">
            {HERO_STATS.map(([v, k]) => (
              <div key={k} className="px-1 py-5 md:px-8">
                <dt className="font-display text-[1.6rem] font-semibold text-cyan-glow md:text-[1.75rem]">
                  {v}
                </dt>
                <dd className="mt-1.5 text-[11px] uppercase tracking-[0.13em] text-ink-mute">
                  {k}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </section>
    </div>
  );
}