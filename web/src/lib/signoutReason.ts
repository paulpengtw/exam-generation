const REASON_KEY = "exam_signout_reason";

export type SignoutReason = "session_expired" | "30day_limit";

export interface SignoutReasonData {
  /** Why the user was signed out. */
  reason: SignoutReason;
  /** The authenticated user's id at the time of sign-out. */
  userId: string;
}

function isSignoutReasonData(v: unknown): v is SignoutReasonData {
  if (typeof v !== "object" || v === null) return false;
  const r = v as Record<string, unknown>;
  return (
    (r.reason === "session_expired" || r.reason === "30day_limit") &&
    typeof r.userId === "string"
  );
}

/**
 * Write the sign-out cause and the affected user id to localStorage so that
 * LoginPage can surface the appropriate explanation banner.
 * Must be called BEFORE logout() clears the user state from the store.
 */
export function saveSignoutReason(reason: SignoutReason, userId: string): void {
  try {
    localStorage.setItem(REASON_KEY, JSON.stringify({ reason, userId }));
  } catch {
    // best-effort
  }
}

/**
 * Read and immediately clear the sign-out reason flag.
 * Returns the parsed data when valid, otherwise null.
 * Always clears the stored value — even a malformed one — on read.
 */
export function consumeSignoutReason(): SignoutReasonData | null {
  try {
    const raw = localStorage.getItem(REASON_KEY);
    localStorage.removeItem(REASON_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (isSignoutReasonData(parsed)) return parsed;
    return null;
  } catch {
    return null;
  }
}
