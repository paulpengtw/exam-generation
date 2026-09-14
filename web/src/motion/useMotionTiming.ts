import { useSyncExternalStore } from 'react';
import { durations, easings } from './tokens';
import { usePrototypeSettings } from './prototypeSettings';

function subscribe(onChange: () => void) {
  const media = window.matchMedia?.('(prefers-reduced-motion: reduce)');
  media?.addEventListener('change', onChange);
  return () => media?.removeEventListener('change', onChange);
}

export function useMotionTiming() {
  const settings = usePrototypeSettings();
  const osReduced = useSyncExternalStore(subscribe,
    () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false, () => false);
  const reduced = settings.reduced || osReduced;
  return {
    ...settings, reduced,
    transition: (token: keyof typeof durations = 'standard', ease: keyof typeof easings = 'signature') => ({
      duration: reduced ? 0.001 : durations[token] * settings.scale / 1000,
      ease: [...easings[ease]] as [number, number, number, number],
    }),
  };
}
