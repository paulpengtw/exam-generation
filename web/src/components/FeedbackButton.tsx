import { useRef } from "react";
import * as Sentry from "@sentry/react";
import { useT } from "../i18n/useT";
import { isSentryEnabled } from "../sentry";

/**
 * Floating bottom-right "?" button that opens Sentry's user-feedback
 * dialog. The form is created per-click so its labels follow the
 * currently selected language. Hidden entirely when no DSN is set.
 */
export default function FeedbackButton() {
  const t = useT();
  const isOpeningRef = useRef(false);
  if (!isSentryEnabled()) return null;

  const openFeedback = async () => {
    const feedback = Sentry.getFeedback();
    if (!feedback) return;
    if (isOpeningRef.current) return;
    isOpeningRef.current = true;
    try {
      const form = await feedback.createForm({
        formTitle: t("feedback.form_title"),
        nameLabel: t("feedback.name_label"),
        emailLabel: t("feedback.email_label"),
        messageLabel: t("feedback.message_label"),
        messagePlaceholder: t("feedback.message_placeholder"),
        submitButtonLabel: t("feedback.submit_label"),
        cancelButtonLabel: t("feedback.cancel_label"),
        successMessageText: t("feedback.success_message"),
        onFormClose: () => {
          isOpeningRef.current = false;
          form.removeFromDom();
        },
        onFormSubmitted: () => {
          isOpeningRef.current = false;
          form.removeFromDom();
        },
      });
      form.appendToDom();
      form.open();
    } catch (err) {
      isOpeningRef.current = false;
      throw err;
    }
  };

  return (
    <button
      type="button"
      aria-label={t("feedback.button_aria")}
      title={t("feedback.button_aria")}
      onClick={openFeedback}
      className="fixed bottom-4 right-4 z-50 flex h-11 w-11 items-center justify-center rounded-full bg-blue-600 text-lg font-bold text-white shadow-lg transition hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-400"
    >
      ?
    </button>
  );
}
