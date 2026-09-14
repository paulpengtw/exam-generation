/* eslint-disable react-refresh/only-export-components -- small throwaway kit exports its hook with the controls */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { useT } from '../i18n/useT';
import { Spinner } from './Indicators';
import { routeEvent, usePrototypeSettings } from './prototypeSettings';

// 待命 / 處理中 / 已完成 / 失敗. Local toggles do not use this model.
export type ActionState = 'idle' | 'pending' | 'done' | 'failed';

export function useActionFeedback(run: () => Promise<string | void>, fallbackReason = '無法完成操作') {
  const [state, setState] = useState<ActionState>('idle');
  const [reason, setReason] = useState<string | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const running = useRef(false);
  const mounted = useRef(true);
  const action = useRef({ run, fallbackReason });
  useLayoutEffect(() => { action.current = { run, fallbackReason }; }, [run, fallbackReason]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const reset = useCallback(() => {
    if (running.current) return;
    setState('idle'); setReason(null); setFilename(null);
  }, []);
  const execute = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    setState('pending'); setReason(null); setFilename(null);
    try {
      const produced = await action.current.run();
      if (mounted.current) { setFilename(produced || null); setState('done'); }
    } catch (error) {
      const detail = error && typeof error === 'object' && 'detail' in error && typeof error.detail === 'string'
        ? error.detail : action.current.fallbackReason;
      if (mounted.current) { setReason(detail); setState('failed'); }
    } finally { running.current = false; }
  }, []);
  useEffect(() => {
    if (state !== 'done') return;
    document.addEventListener('pointerdown', reset, true);
    document.addEventListener('keydown', reset, true);
    window.addEventListener(routeEvent, reset);
    return () => {
      document.removeEventListener('pointerdown', reset, true);
      document.removeEventListener('keydown', reset, true);
      window.removeEventListener(routeEvent, reset);
    };
  }, [state, reset]);
  return { state, reason, filename, execute, retry: execute, reset };
}

type ActionButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  state: ActionState; label: ReactNode; pendingLabel?: ReactNode; doneLabel?: ReactNode; exportAction?: boolean;
};
export function ActionButton({ state, label, pendingLabel, doneLabel, exportAction = false, disabled, className = '', ...props }: ActionButtonProps) {
  const t = useT();
  const { variant } = usePrototypeSettings();
  const iconOnly = exportAction && variant === 'B';
  const text = state === 'pending' && !iconOnly ? pendingLabel ?? t('action.pending')
    : state === 'done' && !iconOnly ? doneLabel ?? t('action.downloaded')
    : state === 'failed' ? t('action.failed') : label;
  return <button {...props} disabled={disabled || state === 'pending'} data-action-state={state}
    className={`action-button inline-flex items-center justify-center gap-2 transition-colors duration-standard ease-signature ${className} ${state === 'done' && !iconOnly ? 'action-done' : ''}`}>
    <span key={state} role={state === 'pending' || state === 'done' ? 'status' : undefined}
      className="inline-flex items-center justify-center gap-2 animate-in fade-in duration-standard ease-signature">
      {state === 'pending' ? <Spinner /> : <span aria-hidden="true" className="inline-block w-4">{state === 'done' ? '✓' : state === 'failed' ? '!' : exportAction ? '↓' : ''}</span>}
      <span className="sentry-unmask">{text}</span>
      {iconOnly && (state === 'pending' || state === 'done') && <span className="sr-only sentry-unmask">{state === 'pending' ? t('action.downloading') : t('action.downloaded')}</span>}
    </span>
  </button>;
}

export function InlineFailureNotice({ reason, onRetry, onDismiss, retryLabel }: { reason: string | null; onRetry: () => void; onDismiss: () => void; retryLabel?: ReactNode }) {
  const t = useT();
  if (!reason) return null;
  return <div role="alert" className="mt-2 flex w-full flex-wrap items-start gap-2 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
    <div className="min-w-0 flex-1"><span className="font-medium sentry-unmask">{t('action.failed')}</span><p className="mt-1 break-words">{reason}</p></div>
    <button type="button" onClick={onRetry} className="rounded border border-red-300 bg-white px-2 py-1">{retryLabel ?? t('action.retry')}</button>
    <button type="button" onClick={onDismiss} aria-label={t('action.dismiss')} className="rounded px-2 py-1">×</button>
  </div>;
}

export function ExportConfirmation({ feedback }: { feedback: { state: ActionState; filename: string | null } }) {
  const t = useT();
  const { variant } = usePrototypeSettings();
  if (variant !== 'B' || feedback.state !== 'done' || !feedback.filename) return null;
  return <p role="status" className="mt-1 w-full text-xs text-gray-500"><span className="sentry-unmask">{t('action.downloaded')}</span> {feedback.filename}</p>;
}
