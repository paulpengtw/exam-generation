// One source of truth for CSS, Motion, and choreography timings. Durations are
// stored in milliseconds because CSS custom properties expose the same units.
export const durations = {
  quick: 150,
  standard: 320,
  loopShimmer: 2250,
  loopSpinner: 900,
} as const;

export const easings = {
  signature: [0.22, 1, 0.36, 1],
  exit: [0.64, 0, 0.78, 0],
  loop: [0.25, 0.1, 0.25, 1],
} as const satisfies Record<string, readonly [number, number, number, number]>;

export const choreography = {
  travel: 8,
  stagger: 40,
  staggerCap: 400,
  handoffDelay: 100,
} as const;

function cubicBezier(values: readonly number[]): string {
  return `cubic-bezier(${values.join(",")})`;
}

export const motionTokenValues = {
  "--motion-duration-quick": `${durations.quick}ms`,
  "--motion-duration-standard": `${durations.standard}ms`,
  "--motion-duration-loop-shimmer": `${durations.loopShimmer}ms`,
  "--motion-duration-loop-spinner": `${durations.loopSpinner}ms`,
  "--motion-ease-signature": cubicBezier(easings.signature),
  "--motion-ease-exit": cubicBezier(easings.exit),
  "--motion-ease-loop": cubicBezier(easings.loop),
  "--motion-travel": `${choreography.travel}px`,
  "--motion-stagger": `${choreography.stagger}ms`,
  "--motion-stagger-cap": `${choreography.staggerCap}ms`,
  "--motion-handoff-delay": `${choreography.handoffDelay}ms`,
} as const;

export function writeMotionTokens(
  root: HTMLElement = document.documentElement,
): void {
  for (const [property, value] of Object.entries(motionTokenValues)) {
    root.style.setProperty(property, value);
  }
}
