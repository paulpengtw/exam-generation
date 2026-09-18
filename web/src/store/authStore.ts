import { create } from "zustand";
import { deleteAllSnapshotsForAccount, clearTabPointer } from "../lib/recovery/storage";

export interface AuthUser {
  id: string;
  email: string;
  created_at: string;
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  login: (token: string, user: AuthUser) => void;
  /**
   * Credential-clearing logout — for 401 / session-expiry paths.
   * Preserves any recovery snapshot so the teacher can restore after
   * re-authenticating.  See issue #776.
   */
  logout: () => void;
  /**
   * Explicit user-initiated logout — clears recovery snapshots and tab
   * pointer for the current account before clearing credentials.
   * A different account signing in after this call will not see the previous
   * teacher's snapshot.  See issue #776.
   */
  logoutExplicit: () => void;
  isAuthenticated: () => boolean;
}

const TOKEN_KEY = "auth_token";
const USER_KEY = "auth_user";

function readPersistedToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function readPersistedUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: readPersistedToken(),
  user: readPersistedUser(),
  login: (token, user) => {
    try {
      localStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(USER_KEY, JSON.stringify(user));
    } catch {
      // Ignore storage failures (private mode, quota, etc.)
    }
    set({ token, user });
  },
  logout: () => {
    // Credential-clearing only — recovery snapshot is preserved for
    // same-tab sign-in restore.  Explicit logout uses logoutExplicit().
    try {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    } catch {
      // Ignore
    }
    set({ token: null, user: null });
  },
  logoutExplicit: () => {
    // Delete recovery snapshots and pointer BEFORE clearing credentials so
    // a different account signing in next cannot see this teacher's work.
    const { user } = get();
    if (user) {
      deleteAllSnapshotsForAccount(user.id);
      clearTabPointer();
    }
    try {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    } catch {
      // Ignore
    }
    set({ token: null, user: null });
  },
  isAuthenticated: () => get().token !== null,
}));
