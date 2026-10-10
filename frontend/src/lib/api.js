/**
 * Backend client.
 *
 * Requests go to /api/... and Vite's proxy forwards them to FastAPI on
 * port 8000 (see vite.config.js). That keeps the browser thinking
 * everything is same-origin.
 */

const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText} — ${body.slice(0, 200)}`);
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

export function askCopilotApi(question, result) {
  return request("/copilot/ask", {
    method: "POST",
    body: JSON.stringify({ question, result }),
  });
}

export function crossCheckApi(gene, change, result) {
  return request("/copilot/cross-check", {
    method: "POST",
    body: JSON.stringify({ gene, change, result }),
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
  const res = await fetch(`${BASE}/upload`, { method: "POST", body: form });

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json();
}