import { useState } from "react";
import AppBackground from "./components/AppBackground";
import Landing from "./components/Landing";
import UploadStep from "./components/UploadStep";
import RunningStep from "./components/RunningStep";
import ResultsStep from "./components/ResultsStep";
import BackendStatus from "./components/BackendStatus";
import LogoMark from "./components/LogoMark";
import { runPipelineReal } from "./lib/mockApi";

function TopBar({ onHome, stage }) {
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-void/70 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-6 py-3">
        <button onClick={onHome} className="flex items-center gap-3">
          <LogoMark size={30} />
          <span className="font-display text-lg font-semibold tracking-tight">
            <span className="text-ink">Cell</span>
            <span className="text-cyan-glow">Spark</span>
          </span>
        </button>
        <div className="ml-auto flex items-center gap-5">
          <BackendStatus />
          <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-mute">
            {stage}
          </span>
        </div>
      </div>
    </header>
  );
}

export default function App() {
  const [view, setView] = useState("hero");
  const [tier, setTier] = useState(0);
  const [frac, setFrac] = useState(0);
  const [result, setResult] = useState(null);

  async function start(config) {
    setView("running");
    setTier(0);
    setFrac(0);
    const res = await runPipelineReal(config, (t, f) => { setTier(t); setFrac(f); });
    setResult(res);
    setView("results");
  }

  const stage = {
    hero: "Research use only",
    upload: "Patient details",
    running: "Analysis running",
    results: "Results ready",
  }[view];

  // AppBackground sits at z-0; every screen is lifted to z-10 above it.
  if (view === "hero") {
    return (
      <>
        <AppBackground />
        <div className="relative z-10">
          <Landing onStart={() => setView("upload")} />
        </div>
      </>
    );
  }

  return (
    <>
      <AppBackground />
      <div className="relative z-10 min-h-[100dvh]">
        <TopBar onHome={() => setView("hero")} stage={stage} />
        {view === "upload" && <UploadStep onRun={start} />}
        {view === "running" && <RunningStep tier={tier} frac={frac} />}
        {view === "results" && result && (
          <ResultsStep result={result} onRestart={() => setView("upload")} />
        )}
      </div>
    </>
  );
}