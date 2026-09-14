// One source for CSS, Motion, and the prototype's timing inspector. Values in ms.
export const durations = { quick: 150, standard: 320, slow: 560, loop: 2250 } as const;
export const easings = {
  signature: [0.22, 1, 0.36, 1],
  exit: [0.64, 0, 0.78, 0],
  loop: [0.25, 0.1, 0.25, 1],
} as const;
export const choreography = { travel: 8, stagger: 40, staggerCap: 400, handoffDelay: 100 } as const;

export function writeMotionTokens(scale = 1): void {
  const root = document.documentElement;
  for (const [name, value] of Object.entries(durations)) {
    root.style.setProperty(`--motion-duration-${name}`, `${value * scale}ms`);
  }
  for (const [name, value] of Object.entries(easings)) {
    root.style.setProperty(`--motion-ease-${name}`, `cubic-bezier(${value.join(',')})`);
  }
  root.style.setProperty('--motion-handoff-delay', `${choreography.handoffDelay * scale}ms`);
}

export function canViewTransition(): boolean {
  return typeof document !== 'undefined' && 'startViewTransition' in document
    && document.documentElement.dataset.motion !== 'reduced'
    && !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}
