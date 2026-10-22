import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Panel, Button, Badge, focusRing } from "./ui";
import { createFormulation, getFormulationOptions } from "../lib/api";

/**
 * Tier 5 — the formulation worksheet.
 *
 * THE RULE THIS PANEL IS BUILT AROUND
 * Every number carries where it came from, and the panel shows it. The
 * backend tags each value `computed`, `constant` or `assumption`; nothing
 * here decides a class for itself, because a UI that inferred provenance
 * would drift from the data the moment either side changed.
 *
 * The inputs sit in their own section, above the worksheet, rendered as the
 * form fields they are. The dose per kg is one of them: an editable field
 * with its basis printed under it, never a line on the sheet reading
 * "recommended dose". The sheet is titled a worksheet and carries the
 * not-for-clinical-use line in the panel, in the JSON and on the print view.
 *
 * Collapsed until opened — a researcher who never formulates should not have
 * to scroll past it, and nothing is fetched until it is.
 */

const fieldClass =
  "mt-1.5 w-full rounded-lg border border-line bg-void/80 px-3 py-2.5 text-sm " +
  `text-ink placeholder:text-ink-mute transition-colors hover:border-ink-mute/60 ` +
  `focus:border-cyan-core ${focusRing}`;

/** Provenance class -> badge tone. Three classes, three tones, no overlap. */
const PROVENANCE = {
  computed: { tone: "ok", label: "computed", title: "Derived from this run's own sequence. Reproducible from it." },
  constant: { tone: "info", label: "constant", title: "Taken from a published formulation. Cited." },
  assumption: { tone: "warn", label: "assumption", title: "Supplied by you. An input, not a result." },
};

function ProvenanceBadge({ provenance }) {
  const p = PROVENANCE[provenance];
  if (!p) return null;
  return (
    <span title={p.title}>
      <Badge tone={p.tone}>{p.label}</Badge>
    </span>
  );
}

/** The citation or basis behind a value, as a details disclosure. */
function Source({ node }) {
  const text = node?.citation || node?.basis;
  if (!text) return null;
  return (
    <details className="mt-1 group">
      <summary
        className={`cursor-pointer list-none text-[11px] text-ink-mute underline decoration-dotted underline-offset-2 hover:text-ink-dim ${focusRing} rounded`}
      >
        source
      </summary>
      <p className="mt-1 text-[11px] leading-relaxed text-ink-mute">{text}</p>
    </details>
  );
}

/**
 * A value out of the backend's provenance envelope, formatted.
 *
 * Most values are numbers or strings, but a constant may carry a small table
 * — the RNA residue masses arrive as {A: 329.21, U: 306.17, ...}. Rendering
 * that with String() gives "[object Object]", so a plain object is spread
 * into "A 329.21 · U 306.17 · ..." instead.
 */
function fmt(node, digits) {
  const v = node?.value;
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    return digits !== undefined
      ? v.toFixed(digits)
      : v.toLocaleString(undefined, { maximumFractionDigits: 6 });
  }
  if (typeof v === "object" && !Array.isArray(v)) {
    return Object.entries(v).map(([k, n]) => `${k} ${n}`).join(" · ");
  }
  if (Array.isArray(v)) return v.join(" · ");
  return String(v);
}

/** One labelled value on the worksheet, with its provenance and source. */
function Row({ node, digits, name }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1 border-b border-line-soft py-2 last:border-b-0">
      <div className="min-w-0">
        <p className="text-sm text-ink-dim">{name || node?.label}</p>
        {node?.note && (
          <p className="mt-0.5 text-[11px] leading-relaxed text-ink-mute">{node.note}</p>
        )}
        <Source node={node} />
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span className="font-mono text-sm text-ink">
          {fmt(node, digits)}
          {node?.unit && <span className="ml-1 text-ink-mute">{node.unit}</span>}
        </span>
        <ProvenanceBadge provenance={node?.provenance} />
      </div>
    </div>
  );
}

function Section({ title, hint, children, badge }) {
  return (
    <section className="mx-5 mb-5 rounded-lg border border-line bg-abyss/60 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="cs-label-mono">{title}</h4>
        {badge}
      </div>
      {hint && <p className="mt-1.5 text-xs leading-relaxed text-ink-mute">{hint}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

function NumberField({ id, label, basis, value, onChange, step, min, max, unit }) {
  return (
    <div>
      <label htmlFor={id} className="flex items-baseline justify-between text-sm text-ink-dim">
        <span>{label}</span>
        {unit && <span className="text-[11px] text-ink-mute">{unit}</span>}
      </label>
      <input
        id={id}
        type="number"
        inputMode="decimal"
        step={step}
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-describedby={`${id}-basis`}
        className={fieldClass}
      />
      <p id={`${id}-basis`} className="mt-1 text-[11px] leading-relaxed text-ink-mute">
        {basis}
      </p>
    </div>
  );
}

function SelectField({ id, label, basis, value, onChange, options }) {
  return (
    <div>
      <label htmlFor={id} className="text-sm text-ink-dim">{label}</label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-describedby={`${id}-basis`}
        className={fieldClass}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      <p id={`${id}-basis`} className="mt-1 text-[11px] leading-relaxed text-ink-mute">
        {basis}
      </p>
    </div>
  );
}

export default function FormulationPanel({ runId }) {
  const uid = useId();
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState(null);
  const [inputs, setInputs] = useState(null);
  const [sheet, setSheet] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Each recalculation POSTs and saves. A later response from an earlier
  // keystroke must not overwrite a newer one, so responses are stamped and
  // stale ones dropped.
  const latest = useRef(0);

  // Nothing is fetched until the panel is opened.
  useEffect(() => {
    if (!open || options) return;
    let live = true;
    getFormulationOptions()
      .then((o) => {
        if (!live) return;
        setOptions(o);
        setInputs({ ...o.defaults });
      })
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [open, options]);

  const compute = useCallback(async (payload) => {
    const stamp = ++latest.current;
    setBusy(true);
    try {
      const body = await createFormulation(runId, payload);
      if (stamp === latest.current) {
        setSheet(body);
        setError("");
      }
    } catch (e) {
      if (stamp === latest.current) {
        setSheet(null);
        setError(e.message);
      }
    } finally {
      if (stamp === latest.current) setBusy(false);
    }
  }, [runId]);

  // Recalculate on change, debounced so typing a weight does not send a
  // request per digit — each one writes a row.
  useEffect(() => {
    if (!inputs || !runId) return;
    const t = setTimeout(() => compute(inputs), 350);
    return () => clearTimeout(t);
  }, [inputs, runId, compute]);

  // Open every citation before printing, and put them back afterwards.
  //
  // The print stylesheet sets `display: block` on each <details> body, which
  // used to be enough. It is not: Chrome hides a closed disclosure's content
  // through ::details-content, which an inherited display cannot override, so
  // the sheet printed with every "source" line empty — the exact failure the
  // stylesheet exists to prevent. Forcing the open attribute works in every
  // browser, and beforeprint covers the browser's own Ctrl+P as well as the
  // panel's Print button.
  useEffect(() => {
    if (!open) return;
    let restore = [];

    const expand = () => {
      const panel = document.querySelector(".cs-formulation");
      if (!panel) return;
      restore = [...panel.querySelectorAll("details")].filter((d) => !d.open);
      restore.forEach((d) => { d.open = true; });
    };
    const collapse = () => {
      restore.forEach((d) => { d.open = false; });
      restore = [];
    };

    window.addEventListener("beforeprint", expand);
    window.addEventListener("afterprint", collapse);
    return () => {
      window.removeEventListener("beforeprint", expand);
      window.removeEventListener("afterprint", collapse);
    };
  }, [open]);

  const set = (key) => (v) => setInputs((prev) => ({ ...prev, [key]: v }));

  const preset = useMemo(
    () => options?.presets.find((p) => p.key === inputs?.preset_key) || null,
    [options, inputs]
  );

  const downloadJson = () => {
    if (!sheet) return;
    const blob = new Blob([JSON.stringify(sheet, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cellspark_formulation_${sheet.formulation_id || "draft"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!runId) return null;

  return (
    <Panel className="overflow-hidden cs-formulation">
      <div className="border-b border-line px-5 py-4">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={`${uid}-body`}
          className={`flex w-full items-start justify-between gap-3 text-left ${focusRing} rounded`}
        >
          <span className="min-w-0">
            <span className="block font-display text-lg font-semibold">
              Formulation Worksheet
            </span>
            <span className="mt-0.5 block text-sm text-ink-dim">
              What it would take to formulate this construct as a lipid
              nanoparticle. Arithmetic on the sequence and on inputs you supply.
            </span>
          </span>
          <span className="mt-1 shrink-0 font-mono text-xs text-ink-mute" aria-hidden="true">
            {open ? "collapse" : "open"}
          </span>
        </button>
      </div>

      {open && (
        <div id={`${uid}-body`}>
          {/* The standing line, first thing inside the panel and repeated in
              every export. */}
          <p
            role="note"
            className="mx-5 mt-5 rounded-lg border border-warn/40 bg-warn/8 p-3.5 text-[13px] leading-relaxed text-ink-dim cs-print-note"
          >
            {options?.not_for_clinical_use ||
              "Computational worksheet for research and manufacturing planning. " +
              "Not a clinical protocol and not validated for human use."}
          </p>

          {error && (
            <p role="alert" className="mx-5 mt-4 rounded-lg border border-alert/50 bg-alert/8 p-3.5 text-sm text-ink-dim">
              {error}
            </p>
          )}

          {!options && !error && (
            <p className="px-5 py-6 text-sm text-ink-mute">Loading presets…</p>
          )}

          {options && inputs && (
            <>
              {/* ---------------- inputs ---------------- */}
              <Section
                title="Inputs — supplied by you"
                badge={<ProvenanceBadge provenance="assumption" />}
                hint={
                  "These are not results and none of them is a recommendation. " +
                  "Each field says what its default rests on; change any of them " +
                  "and the worksheet below recalculates."
                }
              >
                <div className="grid gap-4 sm:grid-cols-2">
                  <NumberField
                    id={`${uid}-weight`}
                    label="Body weight"
                    unit="kg"
                    step="0.5"
                    min="0.1"
                    max="999"
                    value={inputs.patient_weight_kg}
                    onChange={set("patient_weight_kg")}
                    basis={options.bases.patient_weight_kg}
                  />
                  <NumberField
                    id={`${uid}-dose`}
                    label="Dose per kg"
                    unit="µg/kg"
                    step="0.1"
                    min="0.001"
                    max="999"
                    value={inputs.dose_per_kg_mcg}
                    onChange={set("dose_per_kg_mcg")}
                    basis={options.bases.dose_per_kg_mcg}
                  />
                  <NumberField
                    id={`${uid}-conc`}
                    label="Formulated concentration"
                    unit="µg/mL"
                    step="10"
                    min="0.01"
                    value={inputs.concentration_mcg_ml}
                    onChange={set("concentration_mcg_ml")}
                    basis={options.bases.concentration_mcg_ml}
                  />
                  <NumberField
                    id={`${uid}-np`}
                    label="N/P ratio"
                    step="0.5"
                    min="0.1"
                    max="999"
                    value={inputs.np_ratio}
                    onChange={set("np_ratio")}
                    basis={options.bases.np_ratio}
                  />
                  <SelectField
                    id={`${uid}-preset`}
                    label="Lipid system"
                    value={inputs.preset_key}
                    onChange={set("preset_key")}
                    options={options.presets.map((p) => ({ value: p.key, label: p.label }))}
                    basis={
                      preset?.citation ||
                      "A published lipid system. The ratios and citation change with it."
                    }
                  />
                  <SelectField
                    id={`${uid}-route`}
                    label="Route"
                    value={inputs.route}
                    onChange={set("route")}
                    options={options.routes.map((r) => ({ value: r, label: r }))}
                    basis={options.bases.route}
                  />
                  <div className="sm:col-span-2">
                    <SelectField
                      id={`${uid}-schedule`}
                      label="Schedule"
                      value={inputs.schedule}
                      onChange={set("schedule")}
                      options={options.schedules.map((s) => ({ value: s, label: s }))}
                      basis={options.bases.schedule}
                    />
                  </div>
                </div>
              </Section>

              {busy && !sheet && (
                <p className="px-5 pb-5 text-sm text-ink-mute">Working…</p>
              )}

              {/* ---------------- worksheet ---------------- */}
              {sheet && (
                <div aria-busy={busy || undefined} className={busy ? "opacity-60 transition-opacity" : ""}>
                  <Section
                    title="Sequence"
                    badge={<ProvenanceBadge provenance="computed" />}
                    hint="Counted from the construct this run produced."
                  >
                    <Row node={sheet.sequence.nucleotide_length} />
                    <Row node={sheet.sequence.count_a} />
                    <Row node={sheet.sequence.count_u} />
                    <Row node={sheet.sequence.count_g} />
                    <Row node={sheet.sequence.count_c} />
                    <Row node={sheet.sequence.molecular_weight_da} digits={2} />
                    <Row node={sheet.sequence.residue_masses} name="Residue masses used" />
                  </Section>

                  <Section
                    title="Dose and volume"
                    hint={
                      "Computed, but from the inputs above rather than from any " +
                      "evidence. The dose is your body weight multiplied by your " +
                      "µg/kg figure and nothing more."
                    }
                  >
                    <Row node={sheet.amounts.dose_mcg} digits={3} />
                    <Row node={sheet.amounts.injection_volume_ml} digits={3} />
                    <Row node={sheet.amounts.mrna_nanomoles} digits={4} />
                    <Row node={sheet.amounts.phosphate_micromoles} digits={4} />
                    <Row node={sheet.amounts.ionizable_micromoles} digits={4} />
                    <Row node={sheet.amounts.total_lipid_micromoles} digits={4} />
                  </Section>

                  {/* The lipid table: computed amounts from published ratios. */}
                  <Section
                    title="Lipids"
                    hint={sheet.preset.label}
                  >
                    <p className="mb-3 text-[11px] leading-relaxed text-ink-mute">
                      {sheet.preset.citation}
                    </p>

                    {/* overflow-x-auto on the table alone, so a wide table
                        scrolls inside the panel instead of the whole page
                        scrolling sideways on a phone. */}
                    <div className="-mx-1 overflow-x-auto px-1">
                      <table className="w-full min-w-[30rem] border-collapse text-sm">
                        <caption className="sr-only">
                          Lipid amounts for one dose. Molar percentages and
                          molecular weights are published constants; amounts and
                          masses are computed.
                        </caption>
                        <thead>
                          <tr className="border-b border-line text-left">
                            <th scope="col" className="py-2 pr-3 font-normal text-ink-mute">Lipid</th>
                            <th scope="col" className="py-2 pr-3 text-right font-normal text-ink-mute">mol %</th>
                            <th scope="col" className="py-2 pr-3 text-right font-normal text-ink-mute">MW</th>
                            <th scope="col" className="py-2 pr-3 text-right font-normal text-ink-mute">µmol</th>
                            <th scope="col" className="py-2 text-right font-normal text-ink-mute">mg</th>
                          </tr>
                        </thead>
                        <tbody>
                          {sheet.lipids.map((l) => (
                            <tr key={l.role} className="border-b border-line-soft">
                              <th scope="row" className="py-2 pr-3 text-left font-normal text-ink">
                                {l.name}
                                <span className="ml-1.5 text-[11px] text-ink-mute">{l.role}</span>
                              </th>
                              <td className="py-2 pr-3 text-right font-mono text-ink-dim">
                                {fmt(l.molar_pct, 1)}
                              </td>
                              <td className="py-2 pr-3 text-right font-mono text-ink-dim">
                                {fmt(l.molecular_weight_da, 2)}
                                {/* A polydisperse PEG average is not an exact
                                    formula weight, and the table says which. */}
                                {l.mw_is_nominal && (
                                  <span
                                    title="Polydisperse PEG: a nominal average, not an exact formula weight."
                                    className="ml-1 cursor-help text-warn"
                                    aria-label="nominal average"
                                  >
                                    ≈
                                  </span>
                                )}
                              </td>
                              <td className="py-2 pr-3 text-right font-mono text-ink">
                                {fmt(l.micromoles, 4)}
                              </td>
                              <td className="py-2 text-right font-mono text-ink">
                                {fmt(l.mass_mg, 4)}
                              </td>
                            </tr>
                          ))}
                          <tr>
                            <th scope="row" className="py-2 pr-3 text-left font-medium text-ink">Total</th>
                            <td className="py-2 pr-3 text-right font-mono text-ink-mute">100.0</td>
                            <td />
                            <td className="py-2 pr-3 text-right font-mono text-ink-dim">
                              {fmt(sheet.amounts.total_lipid_micromoles, 4)}
                            </td>
                            <td className="py-2 text-right font-mono text-ink">
                              {fmt(sheet.amounts.total_lipid_mass_mg, 4)}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>

                    <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-ink-mute">
                      <ProvenanceBadge provenance="constant" />
                      <span>mol % and MW</span>
                      <span aria-hidden="true">·</span>
                      <ProvenanceBadge provenance="computed" />
                      <span>µmol and mg</span>
                    </div>

                    <div className="mt-3 space-y-2 border-t border-line-soft pt-3">
                      {sheet.lipids.map((l) => (
                        <details key={`${l.role}-src`}>
                          <summary
                            className={`cursor-pointer list-none text-[11px] text-ink-mute underline decoration-dotted underline-offset-2 hover:text-ink-dim ${focusRing} rounded`}
                          >
                            {l.name} — source
                          </summary>
                          <p className="mt-1 text-[11px] leading-relaxed text-ink-mute">
                            {l.molecular_weight_da.citation}
                            {l.molecular_weight_da.note ? ` ${l.molecular_weight_da.note}` : ""}
                          </p>
                        </details>
                      ))}
                    </div>
                  </Section>

                  <Section
                    title="Mixing and particle size"
                    badge={<ProvenanceBadge provenance="constant" />}
                    hint="Published process parameters, not derived from this run."
                  >
                    {Object.entries(sheet.process).map(([key, node]) => (
                      <Row key={key} node={node} />
                    ))}
                    <Row
                      node={sheet.particle_size.target_size_nm_min}
                      name="Typical diameter, low"
                    />
                    <Row
                      node={sheet.particle_size.target_size_nm_max}
                      name="Typical diameter, high"
                    />
                  </Section>

                  {sheet.notes?.length > 0 && (
                    <Section title="What this does and does not tell you">
                      <ul className="space-y-1.5">
                        {sheet.notes.map((n, i) => (
                          <li key={i} className="text-[13px] leading-relaxed text-ink-mute">
                            {n}
                          </li>
                        ))}
                      </ul>
                    </Section>
                  )}
                </div>
              )}

              <div className="flex flex-wrap gap-3 border-t border-line px-5 py-4 cs-no-print">
                <Button variant="ghost" onClick={downloadJson} disabled={!sheet}>
                  Export JSON
                </Button>
                <Button variant="ghost" onClick={() => window.print()} disabled={!sheet}>
                  Print worksheet
                </Button>
              </div>
            </>
          )}
        </div>
      )}
    </Panel>
  );
}
