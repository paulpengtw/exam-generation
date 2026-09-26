import { useLocation } from "react-router-dom";
import { useT } from "../i18n/useT";
import { useFeedbackDialog } from "../hooks/useFeedbackDialog";

const GENERATION_PAGE_PATHS = [
  "/generate/math",
  "/generate/social_studies",
  "/generate/natural_sciences",
];

/**
 * Floating bottom-right "?" button that opens Sentry's user-feedback
 * dialog. Its per-click form follows the currently selected language.
 * Hidden when no Sentry DSN is set or on the three generation-page routes,
 * where the generation progress bar carries feedback instead.
 */
export default function FeedbackButton() {
  const t = useT();
  const { pathname } = useLocation();
  const { enabled, open } = useFeedbackDialog();
  if (!enabled || GENERATION_PAGE_PATHS.includes(pathname)) return null;

  return (
    <button
      type="button"
      aria-label={t("feedback.button_aria")}
      title={t("feedback.button_aria")}
      onClick={open}
      className="sentry-unmask fixed bottom-4 right-4 z-50 flex h-11 w-11 items-center justify-center rounded-full bg-blue-600 text-lg font-bold text-white shadow-lg transition duration-quick ease-signature hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-400"
    >
      ?
    </button>
  );
}
