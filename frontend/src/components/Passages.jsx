import { useState } from "react";
import { Badge, focusRing } from "./ui";

/**
 * What produced the answer the user is reading.
 *
 * This matters more than it looks: a generated answer and a keyword-template
 * answer read almost identically, so without this the user cannot tell
 * whether retrieval actually fed the text. Anything that isn't a known
 * fallback is a model name reported by the backend.
 */
function providerBadge(provider, count) {
  if (provider === "templates") {
    return { tone: "warn", label: "Offline fallback — retrieval only, no generation" };
  }
  if (provider === "offline") {
    return { tone: "warn", label: "Backend unreachable — simulated answer" };
  }
  return {
    tone: "ok",
    label: `Generated from ${count} retrieved source${count === 1 ? "" : "s"}`,
  };
}

/**
 * One retrieved abstract, collapsed to a header and expandable to its snippet.
 *
 * The header is a real <button>, so Enter and Space work for free and the
 * focus ring lands on something that looks clickable. The PMID link sits
 * BESIDE the button rather than inside it — an <a> nested in a <button> is
 * invalid HTML and browsers disagree about which one a click belongs to.
 */
export function PassageRow({ passage }) {
  const [open, setOpen] = useState(false);
  const score = Number(passage.score);

  return (
    <li className="cs-inset overflow-hidden">
      <div className="flex items-start gap-2 px-3 py-2">
        <a
          href={`https://pubmed.ncbi.nlm.nih.gov/${passage.pmid}/`}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className={`shrink-0 rounded font-mono text-[11px] text-cyan-glow underline decoration-cyan-core/30 underline-offset-2 transition hover:decoration-cyan-core ${focusRing}`}
          title={`Open PMID ${passage.pmid} on PubMed`}
        >
          {passage.pmid}
        </a>

        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className={`min-w-0 flex-1 rounded text-left ${focusRing}`}
        >
          <span className="flex items-baseline gap-2">
            {/* line-clamp, not slice — the full title stays selectable and findable */}
            <span className="line-clamp-1 min-w-0 flex-1 text-[12px] text-ink-dim">
              {passage.title}
            </span>
            <span className="shrink-0 font-mono text-[11px] tabular-nums text-ink-mute">
              {Number.isFinite(score) ? score.toFixed(2) : "—"}
            </span>
            <span
              aria-hidden="true"
              className={`shrink-0 text-[10px] text-ink-mute transition-transform ${open ? "rotate-90" : ""}`}
            >
              ▶
            </span>
          </span>
          <span className="mt-0.5 block truncate text-[11px] text-ink-mute">
            {[passage.journal || "PubMed", passage.year].filter(Boolean).join(" · ")}
          </span>
        </button>
      </div>

      {open && (
        <p className="border-t border-line px-3 py-2.5 text-[13px] leading-relaxed text-ink-dim">
          {passage.snippet}
        </p>
      )}
    </li>
  );
}

/**
 * The evidence block under an answer: which path answered, and what it read.
 *
 * The badge renders whenever a provider is known — including the offline case,
 * where there are no passages but the user most needs telling. The list itself
 * is omitted entirely when empty rather than left as a bare container.
 */
export function Evidence({ provider, passages }) {
  if (!provider) return null;
  const list = passages ?? [];
  const { tone, label } = providerBadge(provider, list.length);

  return (
    <div className="mt-3 border-t border-line pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={tone}>{label}</Badge>
        {provider !== "offline" && provider !== "templates" && (
          <span className="cs-chip">{provider}</span>
        )}
      </div>

      {list.length > 0 && (
        <ul className="mt-2.5 space-y-1.5">
          {list.map((p, i) => (
            <PassageRow key={`${p.pmid}-${i}`} passage={p} />
          ))}
        </ul>
      )}
    </div>
  );
}
