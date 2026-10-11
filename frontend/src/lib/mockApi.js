/**
 * Pipeline client.
 *
 * runPipelineReal() and askCopilot() call the FastAPI backend. The *Mock
 * versions remain as fallbacks so the UI never dead-ends when the backend is
 * unreachable, and the mock generator still supplies the benchmark table.
 */
import {
  runPipelineApi,
  askCopilotApi,
  crossCheckApi,
  getRun,
  getRunMessages,
} from "./api";

const GENES = ["TP53", "KRAS", "BRAF", "PIK3CA", "PTEN", "EGFR", "NRAS", "APC", "IDH1", "CTNNB1"];
const AA = "ACDEFGHIKLMNPQRSTVWY".split("");

const rand = (n) => Math.floor(Math.random() * n);
const pick = (a) => a[rand(a.length)];
const peptide = (n = 9) => Array.from({ length: n }, () => pick(AA)).join("");

export function bandFor(ic50) {
  if (ic50 < 50) return { label: "Strong binder", tone: "ok" };
  if (ic50 < 500) return { label: "Weak binder", tone: "warn" };
  return { label: "Below threshold", tone: "alert" };
}

function makeTargets(alleles) {
  const rows = Array.from({ length: 10 }, () => {
    const ic50 = Math.round(Math.exp(Math.random() * 5.6 + 1.6));
    const wt = peptide();
    const pos = rand(9);
    return {
      peptide: wt.slice(0, pos) + pick(AA) + wt.slice(pos + 1),
      wildtype: wt,
      gene: pick(GENES),
      change: `p.${pick(AA)}${rand(600) + 20}${pick(AA)}`,
      allele: pick(alleles.length ? alleles : ["HLA-A*02:01"]),
      ic50,
      wtIc50: Math.round(ic50 * (1.8 + Math.random() * 12)),
      mutPos: pos,
    };
  }).sort((a, b) => a.ic50 - b.ic50);

  return rows.map((r, i) => ({ ...r, rank: i + 1 }));
}

function makeMrna(len = 372) {
  const cod = ["AUG","GCC","AAG","CUG","GAG","UCC","ACC","GGC","CAG","AUC","CCG","UAC","AAC","GUG"];
  let s = "AUG";
  while (s.length < len - 3) s += pick(cod);
  return s + "UGA";
}

/**
 * The simulated result body, built synchronously. runPipelineMock resolves
 * with it once its animation ends; reopening a stored run uses it directly
 * for the parts the backend doesn't produce (the benchmark table).
 */
function mockBody({ alleles = [], fileName = "sample.maf" }) {
  const seq = makeMrna();
  const u = (seq.match(/U/g) || []).length / seq.length;
  return {
    fileName,
    alleles: alleles.length ? alleles : ["HLA-A*02:01"],
    stats: {
      variantsRead: 4200 + rand(2600),
      missense: 780 + rand(420),
      candidates: 1900 + rand(900),
      selfRejected: 90 + rand(140),
      screened: 1500 + rand(700),
    },
    targets: makeTargets(alleles),
    mrna: {
      sequence: seq,
      length: seq.length,
      cai: +(0.78 + Math.random() * 0.16).toFixed(3),
      caiBefore: +(0.42 + Math.random() * 0.14).toFixed(3),
      uracil: +(u * 100).toFixed(1),
      uracilBefore: +(u * 100 + 6 + Math.random() * 5).toFixed(1),
      gc: +(52 + Math.random() * 8).toFixed(1),
    },
    benchmark: [
      { algo: "Boyer–Moore", ms: 14.09, note: "fastest of the two implemented" },
      { algo: "Knuth–Morris–Pratt", ms: 23.14, note: "worst-case guarantee" },
      { algo: "Naive baseline", ms: 26.70, note: "control" },
    ],
  };
}

/**
 * Simulated pipeline. Reports progress through onProgress(tierIndex, fraction)
 * and resolves with a full result object.
 */
export function runPipelineMock({ alleles = [], fileName = "sample.maf" }, onProgress) {
  const durations = [2200, 2600, 1500, 1800];

  return new Promise((resolve) => {
    let tier = 0;
    const started = performance.now();

    function step() {
      const elapsed = performance.now() - started;
      const before = durations.slice(0, tier).reduce((a, b) => a + b, 0);
      const frac = Math.min(1, (elapsed - before) / durations[tier]);

      onProgress?.(tier, frac);

      if (frac >= 1) {
        tier++;
        if (tier >= durations.length) {
          resolve(mockBody({ alleles, fileName }));
          return;
        }
      }
      requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  });
}

/**
 * Keyword-matched answer text. The branches below are the offline fallback's
 * whole brain — see askCopilotMock, which wraps this.
 */
function keywordAnswer(question, result) {
  const top = result?.targets?.[0];
  const q = question.toLowerCase();

  if (q.includes("ic50") || q.includes("binding") || q.includes("affinity")) {
    return {
      answer:
        `IC50 is a predicted binding strength in nanomolar, and it runs backwards to intuition — a lower number means tighter binding. Under 50 nM is treated as a strong binder, under 500 nM as weak but plausible. The top candidate here, ${top?.peptide}, scores ${top?.ic50} nM against ${top?.allele}.`,
      sources: ["MHCflurry 2.0 (Cell Systems, 2020)", "IEDB reference thresholds"],
    };
  }
  if (q.includes("codon") || q.includes("cai")) {
    return {
      answer:
        `Codon optimisation swapped rare codons for common ones without touching a single amino acid, so the protein is unchanged. CAI moved from ${result?.mrna?.caiBefore} to ${result?.mrna?.cai}, where 1.0 would mean every codon is the most frequent choice in human cells. Higher CAI generally means the ribosome stalls less often.`,
      sources: ["Kazusa human codon usage", "CoCoPUTs codon pair tables"],
    };
  }
  if (q.includes("uridine") || q.includes("uracil") || q.includes("inflam")) {
    return {
      answer:
        `Uracil content came down from ${result?.mrna?.uracilBefore}% to ${result?.mrna?.uracil}%. Innate immune sensors read uridine-rich single-stranded RNA as a viral signature, so lowering it reduces the chance the construct itself provokes inflammation. This is the sequence-level half of the problem; manufactured vaccines usually pair it with chemical modification such as N1-methylpseudouridine.`,
      sources: ["Karikó et al., Immunity (2005)", "VaxPress documentation"],
    };
  }
  if (q.includes("safe") || q.includes("risk") || q.includes("self")) {
    return {
      answer:
        `Every candidate was checked against the human reference proteome by exact match, and ${result?.stats?.selfRejected} were discarded because the same motif appears in a healthy protein — those carry an autoimmunity risk. The ${result?.targets?.length} shown here are the survivors. Worth flagging that exact matching won't catch peptides merely similar to self, which is a known gap.`,
      sources: ["UniProtKB/Swiss-Prot human reference proteome"],
    };
  }
  return {
    answer:
      `Across ${result?.stats?.missense} missense variants the pipeline built ${result?.stats?.candidates} candidate peptides and kept the ten with the tightest predicted binding. ${top?.gene} ${top?.change} leads at ${top?.ic50} nM. This is a design and prioritisation output — it needs wet-lab confirmation before it means anything clinically.`,
    sources: ["Pipeline run output", "PubMed Central Open Access corpus"],
  };
}

/**
 * Keyword-matched copilot. Fallback only — used when the backend is
 * unreachable or no raw API response is attached to the result.
 *
 * Returns the same shape as askCopilot, with passages always an array and
 * provider always a string, so the UI renders one shape and never guards
 * against undefined. provider "offline" is what tells the user the text they
 * are reading was simulated in the browser, not generated from retrieval.
 */
export async function askCopilotMock(question, result) {
  await new Promise((r) => setTimeout(r, 700 + Math.random() * 700));
  return {
    ...keywordAnswer(question, result),
    passages: [],
    provider: "offline",
  };
}

/**
 * Real copilot — grounded in the run's own numbers plus retrieved PubMed
 * abstracts. Falls back to the keyword version if the backend is unreachable,
 * so the UI never dead-ends.
 *
 * sources stays flattened to display strings for backwards compatibility.
 * passages and provider pass through untouched: the UI uses them to show which
 * abstract each citation came from, and which path produced the answer.
 */
export async function askCopilot(question, result) {
  if (!result?.apiRaw) return askCopilotMock(question, result);

  try {
    const r = await askCopilotApi(question, result.apiRaw);
    return {
      answer: r.answer,
      sources: r.sources.map(
        (s) => `${s.title} — ${s.journal || "PubMed"} ${s.year} (PMID ${s.pmid})`
      ),
      grounded: r.grounded_in,
      passages: r.passages ?? [],
      provider: r.provider ?? "templates",
    };
  } catch (err) {
    // An expired session is not "backend unreachable": let it through so the
    // app returns to sign-in instead of answering with simulated text.
    if (err.status === 401) throw err;
    return askCopilotMock(question, result);
  }
}

/**
 * Cross-check one target against the indexed corpus.
 *
 * Backend-only: there is no offline version, because a simulated literature
 * lookup would be a fabricated one. With the backend unreachable this reports
 * that it could not search, which is the truthful answer — and still says
 * nothing about the gene.
 */
export async function crossCheck(gene, change, result) {
  try {
    return await crossCheckApi(gene, change, result?.apiRaw ?? {});
  } catch (err) {
    if (err.status === 401) throw err;
    return {
      gene,
      change,
      coverage: "unavailable",
      summary:
        "The backend is unreachable, so the indexed corpus could not be " +
        "searched. This says nothing about " + gene + " — the lookup did not run.",
      passages: [],
      provider: "offline",
      caveat:
        "A cross-check reports only what CellSpark's own small abstract index " +
        "contains. It is not a literature review and not clinical validation.",
    };
  }
}

/**
 * Real pipeline run.
 *
 * All four tiers are genuine Python: custom string matching, MHCflurry
 * inference, codon optimisation, and RAG retrieval (Tier 4 answers on demand
 * through askCopilot rather than as part of the run). Progress is animated
 * client-side because the endpoint returns in one shot.
 *
 * Pass uploadId to run against a clinician's own file; omit it for the demo
 * dataset.
 */
export async function runPipelineReal(
  {
    alleles = [],
    fileName = "sample.maf",
    algorithm = "kmp",
    uploadId = null,
    sampleBarcode = null,
  },
  onProgress
) {
  // Animate tier 1 while the request is genuinely in flight
  let done = false;
  const started = performance.now();

  (function animate() {
    if (done) return;
    const elapsed = performance.now() - started;
    // ease towards 0.9 so it never completes before the response lands
    onProgress?.(0, Math.min(0.9, elapsed / 3000));
    requestAnimationFrame(animate);
  })();

  const api = await runPipelineApi({
    alleles,
    fileName,
    algorithm,
    uploadId,
    sampleBarcode,
  });
  done = true;
  onProgress?.(0, 1);

  // The endpoint returns all tiers at once, so step the remaining stages
  // through quickly to keep the UI coherent.
  for (let tier = 1; tier <= 3; tier++) {
    await new Promise((resolve) => {
      const t0 = performance.now();
      (function run() {
        const f = Math.min(1, (performance.now() - t0) / 600);
        onProgress?.(tier, f);
        if (f >= 1) resolve();
        else requestAnimationFrame(run);
      })();
    });
  }

  // Mock generator still supplies the benchmark table
  // Built directly, not via runPipelineMock: that one animates through its
  // simulated tier durations (~8 s) before resolving, which held the real
  // results back long after the backend had answered.
  const filler = mockBody({ alleles, fileName });

  return shapeResult(api, fileName, filler);
}

/**
 * Backend response -> the object ResultsStep renders.
 *
 * Shared by a fresh run and a reopened one, so a past run re-renders through
 * exactly the same code as when it first appeared.
 */
function shapeResult(api, fileName, filler) {
  const t1 = api.tier1;
  const t2 = api.tier2 || {};
  const t3 = api.tier3 || {};
  const hasRealTargets = t2.implemented && t2.targets?.length;
  const hasRealMrna = t3.implemented && t3.coding_sequence;

  return {
    ...filler,
    fileName,
    alleles: api.alleles,
    // "upload" or "demo" — the UI says which the numbers came from
    source: api.source,
    warning: t1.warning || null,
    // kept so the copilot can send the untouched backend response
    apiRaw: api,
    real: {
      tier1: true,
      tier2: Boolean(hasRealTargets),
      tier3: Boolean(hasRealMrna),
      tier4: true,
    },
    stats: {
      variantsRead: t1.stats.mutations,
      missense: t1.stats.mutations,
      candidates: t1.stats.candidates,
      selfRejected: t1.stats.rejected_self,
      screened: t2.stats?.scored ?? t1.stats.tumour_specific,
    },
    unmappedGenes: t1.stats.unmapped_genes ?? 0,
    proteome: t1.proteome,
    algorithm: t1.algorithm,
    peptidesPerMutation: t1.stats.peptides_per_mutation,
    predictor: t2.predictor,
    bindingStats: t2.stats,
    // real MHCflurry scores when available, otherwise the simulated set
    targets: hasRealTargets ? t2.targets : filler.targets,
    mrna: hasRealMrna
      ? {
          sequence: t3.coding_sequence,
          fullConstruct: t3.full_construct,
          components: t3.components,
          protein: t3.protein,
          proteinUnchanged: t3.protein_unchanged,
          length: t3.after.length,
          cai: t3.after.cai,
          caiBefore: t3.before.cai,
          uracil: t3.after.uracil,
          uracilBefore: t3.before.uracil,
          gc: t3.after.gc,
          notes: t3.notes,
        }
      : filler.mrna,
  };
}

/** Index of the first residue that differs from wild type, or -1. */
function mutationOffset(peptide = "", wildtype = "") {
  if (!wildtype) return -1;
  for (let i = 0; i < peptide.length; i++) {
    if (peptide[i] !== wildtype[i]) return i;
  }
  return -1;
}

/** A stored copilot message -> the shape Copilot renders. */
function toChatMessage(m) {
  if (m.role === "user") return { role: "user", text: m.content };
  return {
    role: "assistant",
    text: m.content,
    sources: [],
    provider: m.provider || "templates",
    passages: (m.citations || []).map((c) => ({
      pmid: c.pmid,
      title: c.title || "",
      journal: c.journal || "",
      year: c.year != null ? String(c.year) : "",
      snippet: c.snippet || "",
      score: c.similarity ?? 0,
    })),
  };
}

/**
 * Reopen a past run from the server.
 *
 * With the stored result file present, this is the exact response the run
 * first returned, shaped by the same shapeResult as a fresh run. Without it,
 * only the database rows remain: ranked targets and headline figures. That
 * case is rendered as-is, with nothing simulated standing in for what's lost
 * — no mRNA panel, and a copilot that shows its history but can't answer,
 * since answers are grounded in the full result.
 */
export async function openStoredRun(runId) {
  const [run, chat] = await Promise.all([getRun(runId), getRunMessages(runId)]);
  const history = (chat.messages || []).map(toChatMessage);
  const reopened = { runId: run.run_id, startedAt: run.started_at };

  if (run.result_available) {
    const api = run.result;
    const shaped = shapeResult(
      api,
      api.file_name || run.file_name,
      mockBody({ alleles: api.alleles || run.alleles, fileName: api.file_name })
    );
    return { ...shaped, reopened, history };
  }

  const dash = (v) => (v == null ? "—" : v);
  return {
    fileName: run.file_name,
    alleles: run.alleles,
    algorithm: run.algorithm,
    source: null,
    warning: null,
    apiRaw: { run_id: run.run_id },
    real: null,
    stats: {
      variantsRead: dash(run.mutations_parsed),
      missense: dash(run.mutations_parsed),
      candidates: dash(run.candidates_built),
      selfRejected: "—",
      screened: "—",
    },
    targets: run.targets.map((t) => ({
      rank: t.rank_position,
      peptide: t.peptide,
      wildtype: t.wildtype,
      gene: t.gene_symbol,
      change: t.protein_change,
      allele: t.allele,
      ic50: t.ic50_nm,
      wtIc50: t.wt_ic50_nm,
      agretopicity: t.agretopicity,
      mutPos: mutationOffset(t.peptide, t.wildtype),
    })),
    mrna: null,
    benchmark: mockBody({ alleles: run.alleles }).benchmark,
    unavailableNote:
      "The full result file for this run is no longer on the server. Shown " +
      "here are the ranked targets and figures stored in the database; the " +
      "mRNA design and the copilot need the full result.",
    copilotUnavailable: true,
    reopened,
    history,
  };
}
