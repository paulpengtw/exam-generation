/* eslint-disable react-refresh/only-export-components */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentProps,
  type MouseEvent,
  type ReactNode,
} from "react";
import { useLocation } from "react-router-dom";

import { ApiError } from "../api/client";
import { useT } from "../i18n/useT";
import { Button } from "../components/ui/button";
import { Spinner } from "./Indicators";

// 待命 / 處理中 / 已完成 / 失敗. Local toggles do not use this model.
export type ActionState = "idle" | "pending" | "done" | "failed";

export class ActionFailure extends Error {
  readonly reason: string;

  constructor(reason: string) {
    super(reason);
    this.name = "ActionFailure";
    this.reason = reason;
  }
}

export interface UseActionFeedbackOptions<T> {
  action: (signal: AbortSignal) => Promise<T>;
  genericError: string;
  timeoutMs?: number;
  getFilename?: (result: T) => string | null | undefined;
  onSuccess?: (result: T) => void;
  successState?: "idle" | "done";
  failureState?: "idle" | "failed";
}

export interface ActionFeedback<T> {
  state: ActionState;
  reason: string | null;
  filename: string | null;
  run: () => Promise<T | undefined>;
  retry: () => void;
  dismiss: () => void;
  reset: () => void;
}

type FailureFeedback = Pick<ActionFeedback<unknown>, "reason" | "retry" | "dismiss">;

export function firstFailure(
  ...feedbacks: readonly FailureFeedback[]
): FailureFeedback | null {
  return feedbacks.find((feedback) => feedback.reason !== null) ?? null;
}

type ClearDoneRegistration = () => void;

interface ActionFeedbackContextValue {
  register: (clearDone: ClearDoneRegistration) => () => void;
  clearDone: () => void;
}

const ActionFeedbackContext = createContext<ActionFeedbackContextValue | null>(null);

const INTERACTIVE_SELECTOR = [
  "button",
  "a[href]",
  "input",
  "select",
  "textarea",
  "summary",
  '[role="button"]',
].join(",");

/**
 * Owns the page-wide dismissal rule for export-style completed actions.
 * Only a real press of an interactive control clears done state; inert clicks
 * and focus/scroll/hover events never enter this path.
 */
export function ActionFeedbackProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const registrationsRef = useRef(new Set<ClearDoneRegistration>());

  const register = useCallback((clearDone: ClearDoneRegistration) => {
    registrationsRef.current.add(clearDone);
    return () => registrationsRef.current.delete(clearDone);
  }, []);

  const clearDone = useCallback(() => {
    for (const clear of registrationsRef.current) clear();
  }, []);

  useEffect(() => {
    const handleClick = (event: globalThis.MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest(INTERACTIVE_SELECTOR) === null) return;
      clearDone();
    };
    document.addEventListener("click", handleClick, true);
    return () => document.removeEventListener("click", handleClick, true);
  }, [clearDone]);

  useEffect(() => {
    clearDone();
  }, [clearDone, location.pathname, location.search, location.hash, location.key]);

  return (
    <ActionFeedbackContext.Provider value={{ register, clearDone }}>
      {children}
    </ActionFeedbackContext.Provider>
  );
}

function getFailureReason(error: unknown, genericError: string): string {
  if (error instanceof ActionFailure && error.reason.trim().length > 0) {
    return error.reason;
  }
  if (error instanceof ApiError && error.detail.trim().length > 0) {
    return error.detail;
  }
  return genericError;
}

/**
 * Runs one non-reentrant action with an AbortSignal timeout and keeps its
 * control-local outcome available to ActionButton and InlineFailureNotice.
 */
export function useActionFeedback<T>({
  action,
  genericError,
  timeoutMs = 30_000,
  getFilename,
  onSuccess,
  successState,
  failureState,
}: UseActionFeedbackOptions<T>): ActionFeedback<T> {
  const context = useContext(ActionFeedbackContext);
  const [state, setState] = useState<ActionState>("idle");
  const [reason, setReason] = useState<string | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const stateRef = useRef<ActionState>("idle");
  const runningRef = useRef(false);
  const mountedRef = useRef(true);
  const controllerRef = useRef<AbortController | null>(null);
  const optionsRef = useRef<UseActionFeedbackOptions<T>>({
    action,
    genericError,
    timeoutMs,
    getFilename,
    onSuccess,
    successState,
    failureState,
  });
  useLayoutEffect(() => {
    optionsRef.current = {
      action,
      genericError,
      timeoutMs,
      getFilename,
      onSuccess,
      successState,
      failureState,
    };
  }, [action, genericError, timeoutMs, getFilename, onSuccess, successState, failureState]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, []);

  const setFeedbackState = useCallback((next: ActionState) => {
    stateRef.current = next;
    if (mountedRef.current) setState(next);
  }, []);

  const clearDone = useCallback(() => {
    if (runningRef.current || stateRef.current !== "done") return;
    setFeedbackState("idle");
    if (mountedRef.current) {
      setReason(null);
      setFilename(null);
    }
  }, [setFeedbackState]);

  useEffect(() => {
    if (!context) return;
    return context.register(clearDone);
  }, [clearDone, context]);

  const run = useCallback(async (): Promise<T | undefined> => {
    if (runningRef.current) return undefined;
    runningRef.current = true;
    const current = optionsRef.current;
    const controller = new AbortController();
    controllerRef.current = controller;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;

    setFeedbackState("pending");
    if (mountedRef.current) {
      setReason(null);
      setFilename(null);
    }

    let actionPromise: Promise<T>;
    try {
      actionPromise = Promise.resolve(current.action(controller.signal));
    } catch (error: unknown) {
      actionPromise = Promise.reject(error);
    }
    const timeoutPromise = new Promise<never>((_, reject) => {
      timeoutId = setTimeout(() => {
        controller.abort();
        reject(new Error("action timeout"));
      }, current.timeoutMs);
    });

    try {
      const result = await Promise.race([actionPromise, timeoutPromise]);
      if (mountedRef.current) {
        const producedFilename = current.getFilename?.(result) ?? null;
        setFilename(producedFilename);
        setReason(null);
        setFeedbackState(current.successState ?? "done");
        current.onSuccess?.(result);
      }
      return result;
    } catch (error: unknown) {
      if (mountedRef.current) {
        setFilename(null);
        setReason(getFailureReason(error, current.genericError));
        setFeedbackState(current.failureState ?? "failed");
      }
      return undefined;
    } finally {
      if (timeoutId !== undefined) clearTimeout(timeoutId);
      if (controllerRef.current === controller) controllerRef.current = null;
      runningRef.current = false;
    }
  }, [setFeedbackState]);

  const dismiss = useCallback(() => {
    if (runningRef.current) return;
    setFeedbackState("idle");
    if (mountedRef.current) {
      setReason(null);
      setFilename(null);
    }
  }, [setFeedbackState]);

  return {
    state,
    reason,
    filename,
    run,
    retry: () => {
      void run();
    },
    dismiss,
    reset: dismiss,
  };
}

export interface ActionButtonProps
  extends Omit<ComponentProps<typeof Button>, "children" | "onClick" | "disabled"> {
  feedback: Pick<ActionFeedback<unknown>, "state" | "filename" | "run">;
  label: ReactNode;
  pendingLabel?: ReactNode;
  doneLabel?: ReactNode;
  disabled?: boolean;
  onPress?: (event: MouseEvent<HTMLButtonElement>) => void;
}

export function ActionButton({
  feedback,
  label,
  pendingLabel,
  doneLabel,
  disabled,
  onPress,
  className,
  ...props
}: ActionButtonProps) {
  const t = useT();
  const isPending = feedback.state === "pending";
  const isDone = feedback.state === "done";
  const isFailed = feedback.state === "failed";
  const text = isPending
    ? pendingLabel ?? t("action.pending")
    : isDone
      ? doneLabel ?? t("action.done")
      : label;
  const stateClassName = isDone
    ? "border-green-600 bg-green-50 text-green-700 hover:bg-green-100"
    : isFailed
      ? "border-red-600 bg-red-50 text-red-700 hover:bg-red-100"
      : "";

  return (
    <Button
      {...props}
      type={props.type ?? "button"}
      disabled={disabled || isPending}
      aria-busy={isPending || undefined}
      data-action-state={feedback.state}
      className={[
        "gap-2",
        stateClassName,
        className,
      ].filter(Boolean).join(" ")}
      onClick={(event) => {
        onPress?.(event);
        if (event.defaultPrevented) return;
        void feedback.run();
      }}
    >
      {isPending ? (
        <span
          key={feedback.state}
          aria-hidden="true"
          className="inline-flex animate-in fade-in duration-quick ease-signature"
        >
          <Spinner />
        </span>
      ) : (
        <span
          key={feedback.state}
          aria-hidden="true"
          className="inline-flex w-4 justify-center animate-in fade-in duration-quick ease-signature"
        >
          {isDone ? "✓" : isFailed ? "!" : ""}
        </span>
      )}
      {(isPending || isDone) ? (
        <span
          key={`text-${feedback.state}`}
          role="status"
          aria-live="polite"
          className="inline-flex animate-in fade-in items-center gap-2 duration-quick ease-signature sentry-unmask"
        >
          {text}
        </span>
      ) : (
        <span
          key={`text-${feedback.state}`}
          className="animate-in fade-in duration-quick ease-signature sentry-unmask"
        >
          {label}
        </span>
      )}
      {isDone && feedback.filename && (
        <span
          data-testid="action-filename"
          title={feedback.filename}
          className="max-w-48 truncate text-xs font-normal text-green-700"
        >
          {feedback.filename}
        </span>
      )}
    </Button>
  );
}

export interface InlineFailureNoticeProps {
  reason: string | null;
  onRetry: () => void;
  onDismiss: () => void;
  retryLabel?: ReactNode;
  retryDisabled?: boolean;
  dismissLabel?: string;
  failedLabel?: ReactNode;
}

export function InlineFailureNotice({
  reason,
  onRetry,
  onDismiss,
  retryLabel,
  retryDisabled = false,
  dismissLabel,
  failedLabel,
}: InlineFailureNoticeProps) {
  const t = useT();
  if (reason === null) return null;

  return (
    <div
      role="alert"
      className="mt-2 flex w-full min-w-0 items-center gap-2 rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700"
    >
      <span className="shrink-0 font-medium sentry-unmask">
        {failedLabel ?? t("action.failed")}
      </span>
      <span data-testid="action-reason" className="min-w-0 flex-1 truncate">
        {reason}
      </span>
      <button
        type="button"
        onClick={onRetry}
        disabled={retryDisabled}
        className="shrink-0 rounded border border-red-300 bg-white px-2 py-1 font-medium hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {retryLabel ?? t("action.retry")}
      </button>
      <button
        type="button"
        onClick={onDismiss}
        aria-label={dismissLabel ?? t("action.dismiss")}
        className="shrink-0 rounded px-2 py-1 text-base leading-none hover:bg-red-100"
      >
        ×
      </button>
    </div>
  );
}
