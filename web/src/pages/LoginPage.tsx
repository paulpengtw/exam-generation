import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useT } from "../i18n/useT";
import LanguageSwitcher from "../components/LanguageSwitcher";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function LoginPage() {
  const { isAuthenticated, sendMagicLink } = useAuth();
  const t = useT();
  const [email, setEmail] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  if (isAuthenticated()) {
    return <Navigate to="/generate" replace />;
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setApiError(null);
    setValidationError(null);

    const trimmed = email.trim();
    if (!EMAIL_RE.test(trimmed)) {
      setValidationError(t("login.validation_email"));
      return;
    }

    setLoading(true);
    const result = await sendMagicLink(trimmed);
    setLoading(false);

    if (result.success) {
      setSent(true);
    } else {
      setApiError(result.error ?? t("login.error_default"));
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">{t("login.title")}</h1>
          <LanguageSwitcher />
        </div>

        {sent ? (
          <div
            role="status"
            className="rounded border border-green-300 bg-green-50 p-4 text-green-800 text-sm text-center"
          >
            {t("login.sent")}
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3" noValidate>
            <div className="space-y-1">
              <label htmlFor="email" className="block text-sm font-medium">
                {t("login.email_label")}
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={loading}
                autoComplete="email"
                className="w-full rounded border border-gray-300 px-3 py-2 focus:outline-none focus:ring focus:ring-blue-200"
                placeholder={t("login.email_placeholder")}
              />
              {validationError && (
                <p role="alert" className="text-sm text-red-600">
                  {validationError}
                </p>
              )}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full rounded bg-blue-600 px-4 py-2 text-white font-medium hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? (
                <span className="inline-flex items-center justify-center gap-2">
                  <span
                    aria-hidden="true"
                    className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent"
                  />
                  {t("login.btn_sending")}
                </span>
              ) : (
                t("login.btn_send")
              )}
            </button>

            {apiError && (
              <p role="alert" className="text-sm text-red-600 text-center">
                {apiError}
              </p>
            )}
          </form>
        )}
      </div>
    </div>
  );
}
