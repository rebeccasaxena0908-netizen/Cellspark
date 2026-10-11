import { useEffect, useRef, useState } from "react";
import { askCopilot } from "../lib/mockApi";
import { Panel } from "./ui";
import { Evidence } from "./Passages";

// Same keyboard focus treatment as the rest of the app.
const focusRing =
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-core/70 " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-void";

const SUGGESTIONS = [
  "What does IC50 mean here?",
  "Explain the codon changes",
  "Why was uracil reduced?",
  "How safe is the top target?",
];

export default function Copilot({ result }) {
  // A reopened run arrives with its stored conversation in result.history,
  // which continues from where it left off: the server appends new questions
  // to the same run.
  const [messages, setMessages] = useState(() => [
    {
      role: "assistant",
      text:
        "I can walk you through anything in these results — what the scores mean, why a target was kept, or what changed in the sequence. Ask in plain language.",
      sources: [],
    },
    ...(result.history ?? []),
  ]);
  // Answers are grounded in the full stored result; without it, the history
  // can be read but not continued.
  const readOnly = Boolean(result.copilotUnavailable);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, busy]);

  async function send(text) {
    const q = (text ?? input).trim();
    if (!q || busy || readOnly) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text: q }]);
    setBusy(true);
    try {
      const res = await askCopilot(q, result);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: res.answer,
          sources: res.sources,
          passages: res.passages,
          provider: res.provider,
        },
      ]);
    } catch {
      // Only a 401 reaches here, and the app is already returning to sign-in.
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel className="flex h-[680px] flex-col overflow-hidden lg:sticky lg:top-6">
      <div className="border-b border-line px-5 py-4">
        <h3 className="font-display text-lg font-semibold">Ask about these results</h3>
        <p className="mt-0.5 text-sm text-ink-dim">
          Answers are drawn from this run and the cited literature.
        </p>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
            <div
              className={`max-w-[92%] rounded-xl px-4 py-3 text-sm leading-relaxed ${
                m.role === "user"
                  ? "bg-cyan-core/14 text-ink"
                  : "border border-line bg-abyss/70 text-ink-dim"
              }`}
            >
              <p className="whitespace-pre-wrap">{m.text}</p>

              {/* The expandable passages supersede the flat citation list —
                  same sources, plus the text each one actually contributed.
                  The flat list stays for the offline path, which has
                  citations but no retrieved passages to expand. */}
              {m.passages?.length > 0 ? null : m.sources?.length > 0 && (
                <ul className="mt-3 space-y-1 border-t border-line pt-2">
                  {m.sources.map((s) => (
                    <li key={s} className="text-[11px] text-ink-mute">↳ {s}</li>
                  ))}
                </ul>
              )}

              <Evidence provider={m.provider} passages={m.passages} />
            </div>
          </div>
        ))}

        {busy && (
          <div className="flex gap-1.5 px-1" aria-label="Thinking">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="h-2 w-2 animate-bounce rounded-full bg-cyan-core/70"
                style={{ animationDelay: `${i * 120}ms` }}
              />
            ))}
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="border-t border-line px-5 py-4">
        {readOnly && (
          <p className="mb-3 text-xs text-ink-mute">
            This run's full result is no longer stored, so new questions can't be
            answered. The conversation above is kept as it was.
          </p>
        )}
        <div className="mb-3 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              disabled={busy || readOnly}
              className={`rounded-full border border-line px-3 py-1.5 text-xs text-ink-dim transition hover:border-cyan-core/55 hover:text-ink disabled:opacity-40 ${focusRing}`}
            >
              {s}
            </button>
          ))}
        </div>

        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Type a question"
            disabled={readOnly}
            aria-label="Ask a question about these results"
            className="min-w-0 flex-1 rounded-lg border border-line bg-void px-4 py-3 text-sm text-ink placeholder:text-ink-mute focus:border-cyan-core focus:outline-none"
          />
          <button
            onClick={() => send()}
            disabled={busy || readOnly || !input.trim()}
            className={`rounded-lg bg-cyan-core px-4 py-3 text-sm font-medium text-void transition hover:bg-cyan-glow disabled:opacity-35 ${focusRing}`}
          >
            Send
          </button>
        </div>
      </div>
    </Panel>
  );
}