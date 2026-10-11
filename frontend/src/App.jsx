import { useCallback, useEffect, useState } from "react";
import AppBackground from "./components/AppBackground";
import AuthScreen from "./components/AuthScreen";
import Landing from "./components/Landing";
import UploadStep from "./components/UploadStep";
import RunningStep from "./components/RunningStep";
import ResultsStep from "./components/ResultsStep";
import HistoryView from "./components/HistoryView";
import BackendStatus from "./components/BackendStatus";
import LogoMark from "./components/LogoMark";
import { openStoredRun, runPipelineReal } from "./lib/mockApi";
import { logout, me } from "./lib/auth";
import { SESSION_EXPIRED_EVENT } from "./lib/api";

const focusRing =
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-core/70 " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-void";

/** #/runs/42 -> 42. A saved run's address, so it can be reloaded or shared. */
function runIdFromHash() {
  const m = window.location.hash.match(/^#\/runs\/(\d+)$/);
  return m ? Number(m[1]) : null;
}

function setRunHash(runId) {
  const url = runId ? `#/runs/${runId}` : window.location.pathname + window.location.search;
  if (runId ? window.location.hash !== url : window.location.hash) {
    window.history.replaceState(null, "", url);
  }
}

function TopBar({ onHome, stage, user, onSignOut, onHistory, inHistory }) {
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-void/70 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3 sm:gap-4 sm:px-6">
        <button onClick={onHome} className={`flex shrink-0 items-center gap-3 rounded-lg ${focusRing}`}>
          <LogoMark size={30} />
          <span className="font-display text-lg font-semibold tracking-tight">
            <span className="text-ink">Cell</span>
            <span className="text-cyan-glow">Spark</span>
          </span>
        </button>
        {/* On a phone only the controls stay; status, stage and name are
            secondary and drop out rather than push the bar sideways. */}
        <div className="ml-auto flex min-w-0 items-center gap-3 sm:gap-5">
          <span className="hidden lg:contents"><BackendStatus /></span>
          <span className="hidden font-mono text-[11px] uppercase tracking-[0.18em] text-ink-mute md:inline">
            {stage}
          </span>
          {user && (
            <div className="flex min-w-0 items-center gap-2 sm:gap-3 md:border-l md:border-line md:pl-5">
              <button
                type="button"
                onClick={onHistory}
                aria-current={inHistory ? "page" : undefined}
                className={`rounded-lg px-3 py-1.5 text-[13px] transition-colors ${
                  inHistory ? "bg-cyan-core/14 text-cyan-glow" : "text-ink-dim hover:text-ink"
                } ${focusRing}`}
              >
                History
              </button>
              <span className="hidden max-w-[12rem] truncate text-sm text-ink-dim sm:inline" title={user.email}>
                {user.display_name}
              </span>
              <button
                type="button"
                onClick={onSignOut}
                className={`shrink-0 rounded-lg border border-line px-3 py-1.5 text-[13px] text-ink-dim transition-colors hover:border-cyan-core/60 hover:text-ink ${focusRing}`}
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
  // A #/runs/<id> link skips the landing page and opens that run once signed in.
  const [view, setView] = useState(() => (runIdFromHash() ? "history" : "hero"));
  const [routeRunId, setRouteRunId] = useState(runIdFromHash);
  const [historyNotice, setHistoryNotice] = useState(null);
  const [tier, setTier] = useState(0);
  const [frac, setFrac] = useState(0);
  const [result, setResult] = useState(null);
  // undefined = still asking the server, null = signed out, object = signed in
  const [user, setUser] = useState(undefined);
  // Set when the server rejected the session mid-use, so sign-in can say why.
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    let cancelled = false;
    me()
      .then((u) => { if (!cancelled) setUser(u); })
      // Server unreachable: show the sign-in form, which reports the
      // connection problem itself on submit.
      .catch(() => { if (!cancelled) setUser(null); });
    return () => { cancelled = true; };
  }, []);

  // Any 401 from the API means the session is gone (expired, or signed out
  // elsewhere). Clear everything the previous session could see and return
  // to sign-in; after signing in again the researcher starts from upload.
  useEffect(() => {
    function onExpired() {
      setResult(null);
      setUser(null);
      setExpired(true);
      setView((v) => (v === "hero" || v === "history" ? v : "upload"));
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, []);

  function signedIn(u) {
    setExpired(false);
    setUser(u);
  }

  useEffect(() => {
    const onHash = () => setRouteRunId(runIdFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  /** Load a saved run and show it in the results view. Throws on failure. */
  const openRun = useCallback(async (runId) => {
    const r = await openStoredRun(runId);
    setResult(r);
    setView("results");
    setRunHash(runId);
  }, []);

  // Follow a #/runs/<id> address once someone is signed in. Someone else's
  // run is a 404 from the server, same as one that doesn't exist.
  useEffect(() => {
    if (!user || !routeRunId) return;
    if (result?.apiRaw?.run_id === routeRunId) return;
    openRun(routeRunId).catch((err) => {
      if (err.status === 401) return;
      setRunHash(null);
      setHistoryNotice(
        err.status === 404
          ? `Run ${routeRunId} wasn't found in your history.`
          : `Couldn't open run ${routeRunId}: ${err.message}`
      );
      setView("history");
    });
    setRouteRunId(null);
  }, [user, routeRunId, result, openRun]);

  /** Change view; leaving a results page drops its #/runs/<id> address. */
  function go(next) {
    if (next !== "results") setRunHash(null);
    if (next !== "history") setHistoryNotice(null);
    setView(next);
  }

  async function signOut() {
    try {
      await logout();
    } catch {
      /* the cookie may be gone already; sign out locally regardless */
    }
    // Drop the previous researcher's result so the next one can't see it.
    setResult(null);
    setExpired(false);
    setUser(null);
    go("hero");
  }

  async function start(config) {
    setView("running");
    setTier(0);
    setFrac(0);
    const res = await runPipelineReal(config, (t, f) => { setTier(t); setFrac(f); });
    setResult(res);
    setView("results");
    // The run is saved now, so give it the address it can be reopened at.
    setRunHash(res.apiRaw?.run_id ?? null);
  }

  const stage = !user ? "Sign in" : {
    hero: "Research use only",
    upload: "Patient details",
    running: "Analysis running",
    results: result?.reopened ? "Saved run" : "Results ready",
    history: "History",
  }[view];

  // AppBackground sits at z-0; every screen is lifted to z-10 above it.
  if (view === "hero") {
    return (
      <>
        <AppBackground />
        <div className="relative z-10">
          <Landing onStart={() => go("upload")} />
        </div>
      </>
    );
  }

  return (
    <>
      <AppBackground />
      <div className="relative z-10 min-h-[100dvh]">
        <TopBar
          onHome={() => go("hero")}
          stage={stage}
          user={user}
          onSignOut={signOut}
          onHistory={() => go("history")}
          inHistory={view === "history"}
        />
        {/* The landing page is public; everything past it needs an account. */}
        {user === undefined && (
          <p role="status" className="py-24 text-center font-mono text-[11px] uppercase tracking-[0.18em] text-ink-mute cs-pulse">
            Checking your session…
          </p>
        )}
        {user === null && (
          <AuthScreen
            onAuthed={signedIn}
            notice={expired ? "Your session has expired. Sign in again to continue." : null}
          />
        )}
        {user && view === "history" && (
          <HistoryView onOpen={openRun} onStart={() => go("upload")} notice={historyNotice} />
        )}
        {user && view === "upload" && <UploadStep onRun={start} />}
        {user && view === "running" && <RunningStep tier={tier} frac={frac} />}
        {user && view === "results" && result && (
          // keyed by run, so moving between runs starts each Copilot afresh
          // from that run's own stored conversation
          <ResultsStep
            key={result.apiRaw?.run_id ?? "unsaved"}
            result={result}
            onRestart={() => go("upload")}
            onBack={result.reopened ? () => go("history") : undefined}
          />
        )}
      </div>
    </>
  );
}