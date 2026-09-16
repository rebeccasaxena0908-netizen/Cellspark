import { useRef, useState } from "react";
import { HLA_OPTIONS } from "../lib/constants";
import { uploadFile } from "../lib/api";
import { Panel, Button, Eyebrow, Badge } from "./ui";

export default function UploadStep({ onRun }) {
  const [file, setFile] = useState(null);
  const [alleles, setAlleles] = useState(["HLA-A*02:01"]);
  const [drag, setDrag] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadInfo, setUploadInfo] = useState(null);
  const [uploadError, setUploadError] = useState(null);
  const inputRef = useRef(null);

  const toggle = (a) =>
    setAlleles((prev) =>
      prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a]
    );

  /** Upload immediately so problems surface before the run, not during it. */
  async function accept(f) {
    if (!f) return;
    setFile(f);
    setUploadInfo(null);
    setUploadError(null);
    setUploading(true);
    try {
      setUploadInfo(await uploadFile(f));
    } catch (err) {
      setUploadError(err.message);
      setFile(null);
    } finally {
      setUploading(false);
    }
  }

  function clearFile(e) {
    e.stopPropagation();
    setFile(null);
    setUploadInfo(null);
    setUploadError(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-14 cs-fade-up">
      <Eyebrow>Step 1 of 3</Eyebrow>
      <h2 className="mt-3 font-display text-3xl font-semibold">Patient details</h2>
      <p className="mt-2 text-ink-dim">
        Two things are needed: the mutation file from sequencing, and the
        patient's HLA type.
      </p>

      {/* ---------- file ---------- */}
      <Panel className="mt-8 p-6">
        <h3 className="font-display text-lg font-semibold">Mutation file</h3>
        <p className="mt-1 text-sm text-ink-dim">
          Accepts MAF, VCF or FASTA. This is the file your sequencing provider
          returns after variant calling.
        </p>

        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault(); setDrag(false);
            accept(e.dataTransfer.files?.[0]);
          }}
          onClick={() => !uploading && inputRef.current?.click()}
          onKeyDown={(e) =>
            (e.key === "Enter" || e.key === " ") && inputRef.current?.click()
          }
          role="button"
          tabIndex={0}
          className={`mt-5 rounded-xl border-2 border-dashed p-10 text-center transition ${
            uploading ? "cursor-wait" : "cursor-pointer"
          } ${
            uploadError
              ? "border-alert/60 bg-alert/5"
              : drag
              ? "border-cyan-core bg-cyan-core/8"
              : uploadInfo
              ? "border-ok/50 bg-ok/5"
              : "border-line hover:border-cyan-core/55 hover:bg-raised/30"
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".maf,.vcf,.fasta,.fa,.txt,.tsv"
            className="hidden"
            onChange={(e) => accept(e.target.files?.[0])}
          />

          {uploading && (
            <p className="text-ink-dim">Reading {file?.name}…</p>
          )}

          {!uploading && uploadInfo && (
            <>
              <p className="font-mono text-ok">{uploadInfo.filename}</p>
              <p className="mt-2 text-sm text-ink-dim">
                {uploadInfo.missense_mutations.toLocaleString()} missense
                mutations across {uploadInfo.distinct_genes} genes
              </p>
              <button
                onClick={clearFile}
                className="mt-3 text-xs text-ink-mute underline hover:text-ink"
              >
                Choose a different file
              </button>
            </>
          )}

          {!uploading && !uploadInfo && (
            <>
              <p className="text-ink">Drop the file here, or click to browse</p>
              <p className="mt-2 text-sm text-ink-mute">
                No file to hand? Continue without one to use the sample patient.
              </p>
            </>
          )}
        </div>

        {/* Validation failed — say what went wrong and how to fix it */}
        {uploadError && (
          <div className="mt-4 rounded-lg border border-alert/40 bg-alert/8 p-4">
            <p className="text-sm font-medium text-alert">
              That file couldn't be read
            </p>
            <p className="mt-1 whitespace-pre-line text-sm text-ink-dim">
              {uploadError}
            </p>
          </div>
        )}

        {/* Validation passed — show what we found so they can confirm it */}
        {uploadInfo && (
          <div className="mt-4 grid gap-3 rounded-lg border border-line bg-abyss/60 p-4 text-sm sm:grid-cols-2">
            <div>
              <p className="text-[11px] uppercase tracking-wider text-ink-mute">
                Patients in file
              </p>
              <p className="mt-1 font-mono text-ink">
                {uploadInfo.sample_count === 1
                  ? uploadInfo.samples[0]
                  : `${uploadInfo.sample_count} samples`}
              </p>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wider text-ink-mute">
                Genes affected
              </p>
              <p className="mt-1 text-ink-dim">
                {uploadInfo.example_genes.join(", ")}
                {uploadInfo.distinct_genes > uploadInfo.example_genes.length &&
                  ` +${uploadInfo.distinct_genes - uploadInfo.example_genes.length} more`}
              </p>
            </div>
          </div>
        )}
      </Panel>

      {/* ---------- HLA ---------- */}
      <Panel className="mt-6 p-6">
        <h3 className="font-display text-lg font-semibold">HLA type</h3>
        <p className="mt-1 text-sm text-ink-dim">
          HLA genes decide which mutated fragments a patient's cells can
          display to the immune system, so scoring depends on them. Select
          every allele reported for this patient.
        </p>

        <div className="mt-5 flex flex-wrap gap-2">
          {HLA_OPTIONS.map((a) => {
            const on = alleles.includes(a);
            return (
              <button
                key={a}
                onClick={() => toggle(a)}
                aria-pressed={on}
                className={`rounded-lg border px-3.5 py-2 font-mono text-[13px] transition ${
                  on
                    ? "border-cyan-core bg-cyan-core/14 text-cyan-glow"
                    : "border-line text-ink-dim hover:border-ink-mute hover:text-ink"
                }`}
              >
                {a}
              </button>
            );
          })}
        </div>

        {alleles.length === 0 && (
          <p className="mt-4 text-sm text-warn">
            Select at least one allele to continue.
          </p>
        )}
      </Panel>

      <div className="mt-8 flex flex-wrap items-center gap-4">
        <Button
          disabled={alleles.length === 0 || uploading}
          onClick={() =>
            onRun({
              alleles,
              fileName: uploadInfo?.filename || "sample_patient.maf",
              uploadId: uploadInfo?.upload_id || null,
              sampleBarcode:
                uploadInfo?.sample_count === 1 ? uploadInfo.samples[0] : null,
            })
          }
        >
          Run analysis
        </Button>
        {uploadInfo ? (
          <Badge tone="ok">Using your file</Badge>
        ) : (
          <Badge tone="info">Using sample patient</Badge>
        )}
      </div>
    </div>
  );
}