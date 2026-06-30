export default function AuroraBackground() {
  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      {/* Main Glow */}
      <div className="absolute left-1/2 top-32 h-[650px] w-[650px] -translate-x-1/2 rounded-full bg-blue-500/10 blur-[160px] animate-pulse" />

      {/* Left Glow */}
      <div
        className="absolute left-10 top-72 h-[420px] w-[420px] rounded-full bg-cyan-400/10 blur-[140px]"
        style={{
          animation: "floatLeft 12s ease-in-out infinite",
        }}
      />

      {/* Right Glow */}
      <div
        className="absolute right-10 top-60 h-[420px] w-[420px] rounded-full bg-violet-500/10 blur-[140px]"
        style={{
          animation: "floatRight 15s ease-in-out infinite",
        }}
      />

      {/* Small Accent */}
      <div
        className="absolute left-1/3 bottom-10 h-[220px] w-[220px] rounded-full bg-sky-400/10 blur-[100px]"
        style={{
          animation: "floatCenter 18s ease-in-out infinite",
        }}
      />

      {/* Dark Overlay */}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,transparent_0%,#000_80%)]" />
    </div>
  );
}