import { apiFetch, getMe, type TokenResponse } from "../api/client";
import { useAuthStore } from "../store/authStore";

const DAY_MS = 24 * 60 * 60 * 1_000;

export function shouldRenew(me: {
  session_expires_at: string;
  renewal_threshold_days: number;
  server_time: string;
}): boolean {
  const remaining =
    Date.parse(me.session_expires_at) - Date.parse(me.server_time);
  return remaining < me.renewal_threshold_days * DAY_MS;
}

/**
 * Fetch /auth/me, evaluate the renewal threshold, and — if the session is
 * close to expiry — POST /auth/refresh and persist the new token.
 *
 * Designed for fire-and-forget use: always call with `.catch(() => undefined)`
 * at the call site so errors are silently swallowed.
 *
 * @param isCancelled  Optional guard for the mount-time use-case.  The store
 *                     update is skipped if this returns true at the time the
 *                     refresh response arrives, preventing a state update after
 *                     the component has unmounted.
 */
export async function renewSessionIfNeeded(
  isCancelled?: () => boolean,
): Promise<void> {
  if (!useAuthStore.getState().token) return;

  const me = (await getMe()) as Awaited<ReturnType<typeof getMe>> &
    Parameters<typeof shouldRenew>[0];
  if (!shouldRenew(me)) return;

  const response = await apiFetch("/auth/refresh", { method: "POST" });
  const refreshed = (await response.json()) as TokenResponse;
  if (isCancelled?.()) return;
  useAuthStore.getState().login(refreshed.access_token, {
    id: me.id,
    email: me.email,
    created_at: me.created_at,
  });
}
