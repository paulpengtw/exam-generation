const RETURN_TO_KEY = "exam_return_to";

const ALLOWED_DESTINATIONS = [
  "/generate/math",
  "/generate/social_studies",
  "/generate/natural_sciences",
] as const;

export type AllowedDestination = (typeof ALLOWED_DESTINATIONS)[number];

/**
 * Returns true only for the three 出題 subject routes that are safe to redirect
 * to after sign-in.  Anything else — /history, external URLs, bare /generate —
 * is rejected so a stored value can never be used for an open-redirect attack.
 */
export function isAllowedDestination(path: string): path is AllowedDestination {
  return (ALLOWED_DESTINATIONS as readonly string[]).includes(path);
}

/**
 * Persist the current 出題 route as the post-sign-in return destination.
 * No-op when path is not in the allowlist (e.g. /history, external URL).
 */
export function saveReturnDestination(path: string): void {
  if (!isAllowedDestination(path)) return;
  try {
    localStorage.setItem(RETURN_TO_KEY, path);
  } catch {
    // best-effort; ignore storage failures (private mode, quota)
  }
}

/**
 * Read and immediately clear the stored return destination.
 * Returns the stored path when it passes the allowlist check, otherwise null.
 * Always clears the stored value — even an invalid one — to avoid leaving
 * stale data.
 */
export function consumeReturnDestination(): string | null {
  try {
    const stored = localStorage.getItem(RETURN_TO_KEY);
    localStorage.removeItem(RETURN_TO_KEY);
    if (stored !== null && isAllowedDestination(stored)) return stored;
    return null;
  } catch {
    return null;
  }
}
