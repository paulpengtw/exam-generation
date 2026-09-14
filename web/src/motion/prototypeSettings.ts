import { useSyncExternalStore } from 'react';

export const prototypeEnabled = import.meta.env.DEV && import.meta.env.VITE_PROTO_720 === '1';
export const settingsEvent = 'prototype-720-settings';
export const routeEvent = 'action-feedback-route';

function subscribe(onChange: () => void) {
  window.addEventListener(settingsEvent, onChange);
  window.addEventListener('popstate', onChange);
  return () => {
    window.removeEventListener(settingsEvent, onChange);
    window.removeEventListener('popstate', onChange);
  };
}

export function usePrototypeSettings() {
  const search = useSyncExternalStore(subscribe, () => window.location.search, () => '');
  const params = new URLSearchParams(prototypeEnabled ? search : '');
  return {
    variant: params.get('variant') === 'B' ? 'B' as const : 'A' as const,
    reduced: params.get('motion') === 'reduced',
    failed: params.get('fail') === '1',
    batch: params.get('batch') === '3',
    scale: params.get('slow') === '4' ? 4 : 1,
  };
}

export function prototypeFailure(): boolean {
  return prototypeEnabled && new URLSearchParams(window.location.search).get('fail') === '1';
}

export function prototypeApiPath(path: string): string {
  if (!prototypeFailure()) return path;
  const url = new URL(path, window.location.origin);
  const failure = url.pathname.endsWith('/resolve') ? 'resolve'
    : url.pathname.endsWith('/download') ? 'download'
    : url.pathname === '/api/history' ? 'history'
    : url.pathname === '/api/generate' || url.pathname.includes('/modifications') ? 'run' : null;
  if (failure) url.searchParams.set('fail', failure);
  return `${url.pathname}${url.search}`;
}
