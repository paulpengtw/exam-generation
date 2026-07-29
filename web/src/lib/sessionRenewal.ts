import { ApiError, apiFetch, getMe, type TokenResponse } from "../api/client";
import { useAuthStore } from "../store/authStore";
import { saveReturnDestination } from "./returnDestination";
import { saveSignoutReason } from "./signoutReason";

const MINUTE_MS = 60 * 1_000;

export function shouldRenew(me: {
  session_expires_at: string;
  renewal_threshold_minutes: number;
  server_time: string;
}): boolean {
  const remaining =
    Date.parse(me.session_expires_at) - Date.parse(me.server_time);
  return remaining < me.renewal_threshold_minutes * MINUTE_MS;
}

/**
 * Fetch /auth/me, evaluate the renewal threshold, and — if the session is
 * close to expiry — POST /auth/refresh and persist the new token.
 *
 * Designed for fire-and-forget use: always call with `.catch(() => undefined)`
 * at the call site so errors are silently swallowed.
 *
 * Sign-out behaviour (issue #243):
 *   • If /auth/me returns 401 (expired session), apiFetch already calls
 *     logout(); this function additionally saves the "session_expired" reason
 *     and the current 出題 path so LoginPage can show the cause banner and
 *     VerifyPage can navigate back after sign-in.
 *   • If /auth/refresh returns 401 (30-day hard cap), the same is done with
 *     the "30day_limit" reason.
 *   • Network errors and non-401 HTTP failures are still propagated to the
 *     caller's .catch(() => undefined) so they are silently swallowed without
 *     affecting the form.
 *
 * @param isCancelled  Optional guard for the mount-time use-case.  The store
 *                     update is skipped if this returns true at the time the
 *                     refresh response arrives, preventing a state update after
 *                     the component has unmounted.
 */
export async function renewSessionIfNeeded(
  isCancelled?: () => boolean,
): Promise<void> {
  const authState = useAuthStore.getState();
  if (!authState.token) return;

  // Capture userId and path BEFORE any async call that may trigger logout().
  // apiFetch calls logout() on 401 which clears user state, so we must read
  // it now while it is still available.
  const preLogoutUserId = authState.user?.id ?? null;
  const currentPath =
    typeof window !== "undefined" ? window.location.pathname : null;

  let me: Awaited<ReturnType<typeof getMe>> & Parameters<typeof shouldRenew>[0];

  try {
    me = (await getMe()) as typeof me;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      // apiFetch already called logout(). Save state for the LoginPage banner
      // and VerifyPage return-destination, then return quietly.
      if (preLogoutUserId !== null) {
        saveSignoutReason("session_expired", preLogoutUserId);
      }
      if (currentPath !== null) {
        saveReturnDestination(currentPath);
      }
      return;
    }
    // Non-401 errors (network failures, 5xx, …): propagate to the caller
    // who swallows them via .catch(() => undefined).
    throw err;
  }

  if (!shouldRenew(me)) return;

  try {
    const response = await apiFetch("/auth/refresh", { method: "POST" });
    const refreshed = (await response.json()) as TokenResponse;
    if (isCancelled?.()) return;
    useAuthStore.getState().login(refreshed.access_token, {
      id: me.id,
      email: me.email,
      created_at: me.created_at,
    });
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      // apiFetch already called logout(). Save the 30-day-cap reason and the
      // current 出題 path, then return quietly.
      saveSignoutReason("30day_limit", me.id);
      if (currentPath !== null) {
        saveReturnDestination(currentPath);
      }
      return;
    }
    // Non-401 errors: propagate so the caller can swallow them.
    throw err;
  }
}
