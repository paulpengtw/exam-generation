import { useRef, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useT } from "../i18n/useT";
import LanguageSwitcher from "../components/LanguageSwitcher";
import { consumeSignoutReason, type SignoutReason } from "../lib/signoutReason";
import { loadDraft } from "../lib/formDraft";
import {
  ActionButton,
  ActionFailure,
  InlineFailureNotice,
  useActionFeedback,
} from "../motion/actionFeedback";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function LoginPage() {
  const { isAuthenticated, sendMagicLink } = useAuth();
  const t = useT();
  const [email, setEmail] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const emailToSendRef = useRef("");
  const [signoutInfo] = useState<{
    reason: SignoutReason;
    hasDraft: boolean;
  } | null>(() => {
    const data = consumeSignoutReason();
    if (!data) return null;
    return { reason: data.reason, hasDraft: loadDraft(data.userId) !== null };
  });

  const feedback = useActionFeedback({
    action: async (signal: AbortSignal) => {
      const result = await sendMagicLink(emailToSendRef.current, signal);
      if (!result.success) {
        throw new ActionFailure(result.error ?? t("login.error_default"));
      }
      return result;
    },
    genericError: t("login.error_default"),
    onSuccess: () => setSent(true),
  });

  function prepareSubmit(): boolean {
    setValidationError(null);

    const trimmed = email.trim();
    if (!EMAIL_RE.test(trimmed)) {
      setValidationError(t("login.validation_email"));
      return false;
    }

    emailToSendRef.current = trimmed;
    return true;
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (prepareSubmit()) void feedback.run();
  }

  if (isAuthenticated()) {
    return <Navigate to="/generate" replace />;
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">{t("login.title")}</h1>
          <LanguageSwitcher />
        </div>

        {signoutInfo !== null && (
          <div
            data-testid="signout-banner"
            className="rounded border border-amber-300 bg-amber-50 p-3 text-amber-800 text-sm"
          >
            {t(
              signoutInfo.reason === "session_expired"
                ? "login.signout.reason_expired"
                : "login.signout.reason_30day_limit",
            )}{" "}
            {t(
              signoutInfo.hasDraft
                ? "login.signout.draft_notice"
                : "login.signout.next_step",
            )}
          </div>
        )}

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
                disabled={feedback.state === "pending"}
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

            <div>
              <ActionButton
                feedback={feedback}
                type="button"
                label={t("login.btn_send")}
                pendingLabel={t("login.btn_sending")}
                className="w-full bg-blue-600 px-4 py-2 text-white hover:bg-blue-700"
                onPress={(event) => {
                  if (!prepareSubmit()) event.preventDefault();
                }}
              />
              <InlineFailureNotice
                reason={feedback.reason}
                onRetry={feedback.retry}
                onDismiss={feedback.dismiss}
              />
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
