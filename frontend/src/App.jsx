import { useEffect, useState } from "react";
import AppBackground from "./components/AppBackground";
import AuthScreen from "./components/AuthScreen";
import Landing from "./components/Landing";
import UploadStep from "./components/UploadStep";
import RunningStep from "./components/RunningStep";
import ResultsStep from "./components/ResultsStep";
import BackendStatus from "./components/BackendStatus";
import LogoMark from "./components/LogoMark";
import { runPipelineReal } from "./lib/mockApi";
import { logout, me } from "./lib/auth";

function TopBar({ onHome, stage, user, onSignOut }) {
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
          {user && (
            <div className="flex items-center gap-3 border-l border-line pl-5">
              <span className="max-w-[12rem] truncate text-sm text-ink-dim" title={user.email}>
                {user.display_name}
              </span>
              <button
                type="button"
                onClick={onSignOut}
                className="rounded-lg border border-line px-3 py-1.5 text-[13px] text-ink-dim transition-colors hover:border-cyan-core/60 hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-core/70 focus-visible:ring-offset-2 focus-visible:ring-offset-void"
              >
                Sign out
              </button>
            </div>
          )}
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
  // undefined = still asking the server, null = signed out, object = signed in
  const [user, setUser] = useState(undefined);

  useEffect(() => {
    let cancelled = false;
    me()
      .then((u) => { if (!cancelled) setUser(u); })
      // Server unreachable: show the sign-in form, which reports the
      // connection problem itself on submit.
      .catch(() => { if (!cancelled) setUser(null); });
    return () => { cancelled = true; };
  }, []);

  async function signOut() {
    try {
      await logout();
    } catch {
      /* the cookie may be gone already; sign out locally regardless */
    }
    // Drop the previous researcher's result so the next one can't see it.
    setResult(null);
    setUser(null);
    setView("hero");
  }

  async function start(config) {
    setView("running");
    setTier(0);
    setFrac(0);
    const res = await runPipelineReal(config, (t, f) => { setTier(t); setFrac(f); });
    setResult(res);
    setView("results");
  }

  const stage = !user ? "Sign in" : {
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
        <TopBar onHome={() => setView("hero")} stage={stage} user={user} onSignOut={signOut} />
        {/* The landing page is public; everything past it needs an account. */}
        {user === undefined && (
          <p role="status" className="py-24 text-center font-mono text-[11px] uppercase tracking-[0.18em] text-ink-mute cs-pulse">
            Checking your session…
          </p>
        )}
        {user === null && <AuthScreen onAuthed={setUser} />}
        {user && view === "upload" && <UploadStep onRun={start} />}
        {user && view === "running" && <RunningStep tier={tier} frac={frac} />}
        {user && view === "results" && result && (
          <ResultsStep result={result} onRestart={() => setView("upload")} />
        )}
      </div>
    </>
  );
}