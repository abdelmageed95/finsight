export function AnimatedGrid() {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 -z-10 bg-grid bg-hero-vignette opacity-40"
      style={{
        maskImage:
          "radial-gradient(ellipse 70% 60% at 50% 40%, black 30%, transparent 80%)",
        WebkitMaskImage:
          "radial-gradient(ellipse 70% 60% at 50% 40%, black 30%, transparent 80%)",
      }}
    />
  );
}
