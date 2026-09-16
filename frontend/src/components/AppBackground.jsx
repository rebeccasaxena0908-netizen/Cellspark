import BinaryRain from "./BinaryRain";

/**
 * AppBackground — a fixed ambient layer behind every screen.
 *
 * IMPORTANT: this sits at z-0, NOT -z-10. A negative z-index paints behind
 * the root element's background, so `body { background: ... }` would hide
 * the whole layer. Content is lifted to z-10 in App.jsx instead.
 */
export default function AppBackground() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-0 overflow-hidden bg-void"
    >
      {/* soft light pools — what stops the page reading as flat black */}
      <div
        className="absolute -left-[10%] top-[-15%] h-[70vh] w-[70vh] rounded-full opacity-70 blur-[120px]"
        style={{ background: "radial-gradient(circle, #0E4E6B 0%, transparent 70%)" }}
      />
      <div
        className="absolute -right-[15%] top-[25%] h-[80vh] w-[80vh] rounded-full opacity-65 blur-[130px]"
        style={{ background: "radial-gradient(circle, #3B2E6E 0%, transparent 70%)" }}
      />
      <div
        className="absolute bottom-[-25%] left-[25%] h-[60vh] w-[60vh] rounded-full opacity-50 blur-[120px]"
        style={{ background: "radial-gradient(circle, #12405C 0%, transparent 70%)" }}
      />

      {/* faint lab grid */}
      <div
        className="absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage:
            "linear-gradient(#7DD3FC 1px, transparent 1px), linear-gradient(90deg, #7DD3FC 1px, transparent 1px)",
          backgroundSize: "64px 64px",
        }}
      />

      <BinaryRain opacity={0.6} />

      {/* vignette — weak in the middle so the rain still reads */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at 50% 40%, transparent 45%, rgba(6,10,20,.3) 80%, rgba(6,10,20,.65) 100%)",
        }}
      />
    </div>
  );
}