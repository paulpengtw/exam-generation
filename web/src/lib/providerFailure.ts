/** Safe, display-only context for a failed upstream provider call. */
export interface ProviderFailureContext {
  provider?: string;
  model?: string;
  httpStatus?: number;
  retryAfterSeconds?: number;
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function integer(value: unknown): number | undefined {
  return typeof value === "number" && Number.isInteger(value) ? value : undefined;
}

/** Parse only the fields that are safe to show in the UI. */
export function parseProviderFailureContext(raw: unknown): ProviderFailureContext | null {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return null;
  const value = raw as Record<string, unknown>;
  const context: ProviderFailureContext = {
    provider: nonEmptyString(value.provider),
    model: nonEmptyString(value.model),
    httpStatus: integer(value.http_status ?? value.httpStatus),
    retryAfterSeconds: integer(value.retry_after_seconds ?? value.retryAfterSeconds),
  };
  return Object.values(context).some((item) => item !== undefined) ? context : null;
}

/** Format a short, non-sensitive context line for an error message. */
export function formatProviderFailureContext(
  context: ProviderFailureContext | null | undefined,
): string | null {
  if (context == null) return null;
  const parts = [context.provider, context.model].filter(
    (value): value is string => value !== undefined,
  );
  if (context.httpStatus !== undefined) parts.push(`HTTP ${context.httpStatus}`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

export function appendProviderFailureContext(
  message: string,
  context: ProviderFailureContext | null | undefined,
): string {
  const line = formatProviderFailureContext(context);
  return line == null ? message : `${message}\n${line}`;
}
