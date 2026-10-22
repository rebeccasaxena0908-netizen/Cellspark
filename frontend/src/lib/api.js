/**
 * Backend client.
 *
 * Requests go to /api/... and Vite's proxy forwards them to FastAPI on
 * port 8000 (see vite.config.js). That keeps the browser thinking
 * everything is same-origin.
 */

const BASE = "/api";

/**
 * Fired on any 401 from a route that needs a session. App.jsx listens and
 * drops back to the sign-in screen, so an expired session shows up as
 * "sign in again" rather than as a page that quietly stops working.
 */
export const SESSION_EXPIRED_EVENT = "cellspark:session-expired";

/** Error carrying the HTTP status, so callers can tell 401 from other failures. */
export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

/**
 * fetch with the session cookie attached, and 401 reported globally.
 *
 * credentials: "include" sends the httpOnly session cookie. Every route here
 * except /health needs it.
 */
async function send(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, { credentials: "include", ...options });
  if (res.status === 401) {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    throw new ApiError("Your session has expired. Sign in again.", 401);
  }
  return res;
}

async function request(path, options = {}) {
  const res = await send(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(`${res.status} ${res.statusText} — ${body.slice(0, 200)}`, res.status);
  }
  return res.json();
}

export function checkHealth() {
  return request("/health");
}

export function runTier1({ algorithm = "kmp", maxMutations = 30 } = {}) {
  return request(`/tier1/run?algorithm=${algorithm}&max_mutations=${maxMutations}`);
}

export function runPipelineApi({ alleles, fileName, algorithm = "kmp", uploadId = null, sampleBarcode = null }) {
  return request("/pipeline/run", {
    method: "POST",
    body: JSON.stringify({
      alleles,
      file_name: fileName,
      algorithm,
      upload_id: uploadId,
      sample_barcode: sampleBarcode,
    }),
  });
}

/**
 * The copilot and cross-check name the run by id. The server loads that
 * run's stored result and conversation itself, so neither is sent from here.
 */
export function askCopilotApi(question, result) {
  return request("/copilot/ask", {
    method: "POST",
    body: JSON.stringify({ question, run_id: result?.run_id }),
  });
}

export function crossCheckApi(gene, change, result) {
  return request("/copilot/cross-check", {
    method: "POST",
    body: JSON.stringify({ gene, change, run_id: result?.run_id }),
  });
}

export function getCorpusInfo() {
  return request("/corpus/info");
}

export async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);

  // No Content-Type header — the browser must set it with the multipart
  // boundary itself. Setting it manually breaks the upload.
  const res = await send("/upload", { method: "POST", body: form });

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status);
  }
  return res.json();
}

// ------------------------------------------------------------- history

export function listRuns({ limit = 20, offset = 0 } = {}) {
  return request(`/runs?limit=${limit}&offset=${offset}`);
}

/** A stored run. result is null (result_available false) if its file is gone. */
export function getRun(runId) {
  return request(`/runs/${encodeURIComponent(runId)}`);
}

export function getRunMessages(runId) {
  return request(`/runs/${encodeURIComponent(runId)}/messages`);
}

export function deleteRun(runId) {
  return request(`/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
}

export function getMyStats() {
  return request("/me/stats");
}

// ------------------------------------------------------------- formulation

/** The presets, routes, schedules and defaults the formulation panel offers. */
export function getFormulationOptions() {
  return request("/formulation/options");
}

/**
 * Compute and save one formulation worksheet for a run.
 *
 * The sequence is not sent: the server formulates the Tier 3 construct it
 * stored for this run. Everything here is an input the researcher chose, and
 * the response labels each one as such.
 */
export function createFormulation(runId, inputs) {
  return request(`/runs/${encodeURIComponent(runId)}/formulation`, {
    method: "POST",
    body: JSON.stringify(inputs),
  });
}

export function listFormulations(runId) {
  return request(`/runs/${encodeURIComponent(runId)}/formulations`);
}

/** The saved worksheet as a machine-readable protocol, from its snapshot. */
export function exportFormulation(formulationId) {
  return request(`/formulations/${encodeURIComponent(formulationId)}/export.json`);
}
