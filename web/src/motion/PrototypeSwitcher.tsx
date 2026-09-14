import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';

export default function PrototypeSwitcher() {
  const [params, setParams] = useSearchParams();
  const variant = params.get('variant') === 'B' ? 'B' : 'A';
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (target instanceof Element && target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])')) return;
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      setParams((current) => { const next = new URLSearchParams(current); next.set('variant', current.get('variant') === 'B' ? 'A' : 'B'); return next; }, { replace: true });
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [setParams]);
  const cycle = () => setParams((current) => { const next = new URLSearchParams(current); next.set('variant', variant === 'A' ? 'B' : 'A'); return next; }, { replace: true });
  const toggle = (key: string, value: string) => setParams((current) => {
    const next = new URLSearchParams(current);
    if (next.get(key) === value) next.delete(key); else next.set(key, value);
    return next;
  }, { replace: true });
  return <aside aria-label="Prototype 727 controls" className="fixed right-3 bottom-24 z-40 flex max-w-[calc(100vw-1.5rem)] flex-wrap items-center gap-2 rounded-2xl border-2 border-yellow-300 bg-gray-950 p-3 text-xs text-white shadow-lg">
    <strong className="text-yellow-300">727 · THROWAWAY</strong>
    <button type="button" onClick={cycle} aria-label="上一個變體" className="px-2 py-1">←</button>
    <span>{variant} · {variant === 'A' ? '文字與勾號' : '圖示與檔名'}</span>
    <button type="button" onClick={cycle} aria-label="下一個變體" className="px-2 py-1">→</button>
    {[
      ['motion', 'reduced', '減少動態'], ['fail', '1', '強制失敗'],
      ['batch', '3', '批次 3 題'], ['slow', '4', '慢速 4×'],
    ].map(([key, value, label]) => <label key={key} className="flex items-center gap-1 rounded border border-gray-600 px-2 py-1">
      <input type="checkbox" checked={params.get(key) === value} onChange={() => toggle(key, value)} />{label}
    </label>)}
  </aside>;
}
