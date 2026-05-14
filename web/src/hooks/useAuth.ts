import { useAuthStore, type AuthUser } from "../store/authStore";
import { useLangStore } from "../store/langStore";

export interface AuthResult {
  success: boolean;
  error?: string;
}

interface VerifyResponse {
  access_token: string;
  token_type: string;
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") return body.detail;
  } catch {
    // fall through
  }
  return `Request failed with status ${res.status}`;
}

export function useAuth() {
  const token = useAuthStore((s) => s.token);
  const user = useAuthStore((s) => s.user);
  const login = useAuthStore((s) => s.login);
  const logout = useAuthStore((s) => s.logout);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const lang = useLangStore((s) => s.lang);

  async function sendMagicLink(email: string): Promise<AuthResult> {
    try {
      const res = await fetch("/auth/magic-link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, lang }),
      });
      if (!res.ok) {
        return { success: false, error: await parseError(res) };
      }
      return { success: true };
    } catch (err) {
      return { success: false, error: (err as Error).message };
    }
  }

  async function verifyToken(magicToken: string, email: string): Promise<AuthResult> {
    try {
      const params = new URLSearchParams({ token: magicToken, email });
      const res = await fetch(`/auth/verify?${params.toString()}`);
      if (!res.ok) {
        return { success: false, error: await parseError(res) };
      }
      const data = (await res.json()) as VerifyResponse;

      const meRes = await fetch("/auth/me", {
        headers: { Authorization: `Bearer ${data.access_token}` },
      });
      if (!meRes.ok) {
        return { success: false, error: await parseError(meRes) };
      }
      const userData = (await meRes.json()) as AuthUser;
      login(data.access_token, userData);
      return { success: true };
    } catch (err) {
      return { success: false, error: (err as Error).message };
    }
  }

  return {
    token,
    user,
    isAuthenticated,
    sendMagicLink,
    verifyToken,
    logout,
  };
}
