import { useEffect, useState } from "react";
import { checkHealth } from "../lib/api";

/**
 * Live backend indicator.
 *
 * Worth having in a clinical tool: if the analysis server is unreachable,
 * the user should know before they upload a file, not after they've waited.
 */
export default function BackendStatus() {
  const [state, setState] = useState("checking");   // checking | online | offline
  const [version, setVersion] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function ping() {
      try {
        const data = await checkHealth();
        if (!cancelled) {
          setState("online");
          setVersion(data.version);
        }
      } catch {
        if (!cancelled) setState("offline");
      }
    }

    ping();
    const id = setInterval(ping, 15000);   // re-check every 15s
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const config = {
    checking: { dot: "bg-ink-mute", text: "Checking analysis server" },
    online:   { dot: "bg-ok",       text: `Analysis server ready${version ? ` · v${version}` : ""}` },
    offline:  { dot: "bg-alert",    text: "Analysis server unreachable" },
  }[state];

  return (
    <span
      className="flex items-center gap-2 text-[11px] text-ink-mute"
      title={state === "offline" ? "Start the backend: uvicorn app.main:app --reload --reload-dir app" : ""}
    >
      <span className={`h-2 w-2 rounded-full ${config.dot} ${state === "online" ? "cs-pulse" : ""}`} />
      {config.text}
    </span>
  );
}
