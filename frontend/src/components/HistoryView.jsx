import { useCallback, useEffect, useId, useRef, useState } from "react";
import { deleteRun, getMyStats, listRuns } from "../lib/api";
import { Badge, Button, Eyebrow, Panel, focusRing } from "./ui";

/**
 * The signed-in researcher's past runs.
 *
 * A completed run opens in the existing ResultsStep, rendered from what was
 * stored. A failed run shows why it failed instead of opening. Deleting asks
 * first, because it is permanent.
 */

const PAGE = 20;

function formatDate(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function formatDuration(ms) {
  if (ms == null) return "—";
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

function formatIc50(v) {
  return v == null ? "—" : `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} nM`;
}

const STATUS = {
  completed: { tone: "ok", label: "Completed" },
  failed: { tone: "alert", label: "Failed" },
  running: { tone: "warn", label: "Not finished" },
};

/* ------------------------------------------------------------------ stats */

function StatsRow({ stats }) {
  const tiles = [
    ["Runs", stats ? stats.total_runs.toLocaleString() : null],
    ["Files", stats ? stats.distinct_files.toLocaleString() : null],
    ["Targets", stats ? stats.total_targets.toLocaleString() : null],
    ["Best IC50", stats ? formatIc50(stats.best_ic50_nm) : null],
    ["Copilot messages", stats ? stats.copilot_messages.toLocaleString() : null],
  ];
  return (
    <dl className="mt-8 grid grid-cols-2 gap-3 min-[480px]:grid-cols-3 sm:grid-cols-5">
      {tiles.map(([label, value]) => (
        <div key={label} className="cs-panel min-w-0 px-4 py-3">
          <dt className="truncate text-[11px] uppercase tracking-wider text-ink-mute">{label}</dt>
          <dd className="mt-1 truncate font-display text-xl font-semibold text-ink">
            {value ?? <span className="inline-block h-6 w-12 animate-pulse rounded bg-raised" />}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/* ------------------------------------------------------------------ a run */

function Figure({ label, children }) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] uppercase tracking-wider text-ink-mute">{label}</p>
      <p className="mt-0.5 truncate text-sm text-ink">{children}</p>
    </div>
  );
}

function RunRow({ run, opening, onOpen, onDeleted, onError }) {
  const id = useId();
  const [showError, setShowError] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const cancelRef = useRef(null);
  const deleteRef = useRef(null);

  const status = STATUS[run.status] ?? STATUS.running;
  const openable = run.status === "completed";

  useEffect(() => {
    if (confirming) cancelRef.current?.focus();
  }, [confirming]);

  function cancel() {
    setConfirming(false);
    // put focus back on the control that opened the confirmation
    requestAnimationFrame(() => deleteRef.current?.focus());
  }

  async function confirmDelete() {
    setDeleting(true);
    try {
      await deleteRun(run.run_id);
      onDeleted(run.run_id);
    } catch (err) {
      setDeleting(false);
      setConfirming(false);
      if (err.status !== 401) onError(`Couldn't delete that run: ${err.message}`);
    }
  }

  function activate() {
    if (openable) onOpen(run.run_id);
    else if (run.status === "failed") setShowError((v) => !v);
  }

  return (
    <li className="cs-panel overflow-hidden">
      <div className="flex items-stretch">
        <button
          type="button"
          onClick={activate}
          disabled={run.status === "running" || opening}
          aria-expanded={run.status === "failed" ? showError : undefined}
          aria-controls={run.status === "failed" ? `${id}-error` : undefined}
          className={`min-w-0 flex-1 rounded-l-2xl px-5 py-4 text-left transition-colors enabled:hover:bg-raised/30 disabled:cursor-default ${focusRing}`}
        >
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span className="min-w-0 max-w-full truncate font-mono text-sm text-ink">
              {run.file_name}
            </span>
            <Badge tone={status.tone}>{status.label}</Badge>
            {!run.file_available && (
              <span className="text-[11px] text-ink-mute">File no longer available</span>
            )}
            {opening && <span className="text-[11px] text-cyan-glow">Opening…</span>}
          </span>

          <span className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-5">
            <Figure label="Ran">{formatDate(run.started_at)}</Figure>
            <Figure label="Duration">{formatDuration(run.duration_ms)}</Figure>
            <Figure label="Targets">{run.targets_returned ?? "—"}</Figure>
            <Figure label="Best IC50">{formatIc50(run.best_ic50_nm)}</Figure>
            <Figure label="Top target">
              {run.top_gene ? (
                <>
                  {run.top_gene}{" "}
                  <span className="font-mono text-[12px] text-ink-dim">{run.top_peptide}</span>
                </>
              ) : (
                "—"
              )}
            </Figure>
          </span>

          {run.status === "running" && (
            <span className="mt-3 block text-xs text-ink-mute">
              This run never recorded a finish. It may still be in progress, or the
              server may have stopped part-way.
            </span>
          )}
        </button>

        <div className="flex shrink-0 items-start border-l border-line p-2">
          <button
            ref={deleteRef}
            type="button"
            onClick={() => setConfirming(true)}
            disabled={confirming || deleting}
            aria-label={`Delete run on ${run.file_name} from ${formatDate(run.started_at)}`}
            className={`rounded-lg px-3 py-2 text-[13px] text-ink-mute transition-colors hover:bg-alert/10 hover:text-alert disabled:opacity-40 ${focusRing}`}
          >
            Delete
          </button>
        </div>
      </div>

      {run.status === "failed" && showError && (
        <div id={`${id}-error`} className="border-t border-line bg-alert/5 px-5 py-4">
          <p className="text-sm font-medium text-alert">Why this run failed</p>
          <p className="mt-1 whitespace-pre-wrap break-words font-mono text-[12px] text-ink-dim">
            {run.error_message || "No error was recorded."}
          </p>
        </div>
      )}

      {confirming && (
        <div
          role="alertdialog"
          aria-labelledby={`${id}-confirm`}
          aria-describedby={`${id}-confirm-detail`}
          onKeyDown={(e) => e.key === "Escape" && !deleting && cancel()}
          className="border-t border-alert/30 bg-alert/8 px-5 py-4"
        >
          <p id={`${id}-confirm`} className="text-sm font-medium text-alert">
            Delete this run permanently?
          </p>
          <p id={`${id}-confirm-detail`} className="mt-1 text-sm text-ink-dim">
            Its ranked targets, copilot conversation and cross-checks will be
            removed. This cannot be undone. The uploaded file is kept.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={confirmDelete}
              disabled={deleting}
              className={`rounded-lg bg-alert px-4 py-2 text-sm font-medium text-void transition-opacity hover:opacity-90 disabled:opacity-50 ${focusRing}`}
            >
              {deleting ? "Deleting…" : "Delete permanently"}
            </button>
            <button
              ref={cancelRef}
              type="button"
              onClick={cancel}
              disabled={deleting}
              className={`rounded-lg border border-line px-4 py-2 text-sm text-ink-dim transition-colors hover:text-ink disabled:opacity-40 ${focusRing}`}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

/* ------------------------------------------------------------------ page */

export default function HistoryView({ onOpen, onStart, notice = null }) {
  const [runs, setRuns] = useState(null);           // null until the first page lands
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(notice);
  // Only a failed load hides the empty state; a notice (e.g. a run link that
  // wasn't found) sits above it.
  const [loadFailed, setLoadFailed] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [opening, setOpening] = useState(null);
  const headingRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const [page, s] = await Promise.all([listRuns({ limit: PAGE, offset: 0 }), getMyStats()]);
      setRuns(page.runs);
      setTotal(page.total);
      setStats(s);
      setLoadFailed(false);
    } catch (err) {
      if (err.status !== 401) {
        setLoadFailed(true);
        setError(`Couldn't load your runs: ${err.message}`);
        setRuns((r) => r ?? []);
      }
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (notice) setError(notice); }, [notice]);

  async function more() {
    setLoadingMore(true);
    try {
      const page = await listRuns({ limit: PAGE, offset: runs.length });
      setRuns((r) => [...r, ...page.runs]);
      setTotal(page.total);
    } catch (err) {
      if (err.status !== 401) setError(`Couldn't load more runs: ${err.message}`);
    } finally {
      setLoadingMore(false);
    }
  }

  async function open(runId) {
    setError(null);
    setOpening(runId);
    try {
      await onOpen(runId);
    } catch (err) {
      if (err.status !== 401) setError(`Couldn't open that run: ${err.message}`);
      setOpening(null);
    }
  }

  function deleted(runId) {
    setRuns((r) => r.filter((x) => x.run_id !== runId));
    setTotal((t) => Math.max(0, t - 1));
    headingRef.current?.focus();
    getMyStats().then(setStats).catch(() => {});
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-12 cs-fade-up">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Eyebrow>Your work</Eyebrow>
          <h2
            ref={headingRef}
            tabIndex={-1}
            className="mt-3 font-display text-3xl font-semibold focus:outline-none"
          >
            History
          </h2>
          <p className="mt-2 text-ink-dim">Every analysis you've run, newest first.</p>
        </div>
        <Button variant="ghost" onClick={onStart} className={focusRing}>New analysis</Button>
      </div>

      <StatsRow stats={stats} />

      {error && (
        <div role="alert" className="mt-6 rounded-lg border border-alert/40 bg-alert/8 p-4">
          <p className="text-sm text-ink-dim">{error}</p>
        </div>
      )}

      {runs === null ? (
        <div role="status" aria-label="Loading your runs" className="mt-8 space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="cs-panel h-28 animate-pulse" />
          ))}
        </div>
      ) : runs.length === 0 && !loadFailed ? (
        <Panel className="mt-8 flex flex-col items-start gap-4 p-6 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-ink-dim">
            Your runs will appear here after your first analysis.
          </p>
          <Button onClick={onStart} className={focusRing}>Start an analysis</Button>
        </Panel>
      ) : (
        <>
          <ul className="mt-8 space-y-3" aria-label="Past runs">
            {runs.map((run) => (
              <RunRow
                key={run.run_id}
                run={run}
                opening={opening === run.run_id}
                onOpen={open}
                onDeleted={deleted}
                onError={setError}
              />
            ))}
          </ul>
          {runs.length < total && (
            <div className="mt-6 flex justify-center">
              <Button variant="ghost" onClick={more} disabled={loadingMore} className={focusRing}>
                {loadingMore ? "Loading…" : `Show more (${total - runs.length} older)`}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
