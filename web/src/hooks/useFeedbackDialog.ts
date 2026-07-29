import { useRef } from "react";
import * as Sentry from "@sentry/react";
import { useT } from "../i18n/useT";
import { isSentryEnabled } from "../sentry";

export function useFeedbackDialog(): {
  enabled: boolean;
  open: () => Promise<void>;
} {
  const t = useT();
  const isOpeningRef = useRef(false);
  const enabled = isSentryEnabled();

  const open = async () => {
    if (!enabled) return;
    const feedback = Sentry.getFeedback();
    if (!feedback) return;
    if (isOpeningRef.current) return;
    isOpeningRef.current = true;
    try {
      const form = await feedback.createForm({
        formTitle: t("feedback.form_title"),
        showName: false,
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

  return { enabled, open };
}
