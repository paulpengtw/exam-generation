import { useEffect } from "react";
import { useT } from "../i18n/useT";

/**
 * Sets document.title based on the current locale and whether the app is
 * running on the staging environment (VITE_IS_STAGING).
 *
 * Reacts to locale switches automatically because useT() reads from
 * useLangStore, which is a Zustand store.
 */
export function useDocumentTitle(): void {
  const t = useT();

  useEffect(() => {
    document.title = import.meta.env.VITE_IS_STAGING
      ? t("app.title_staging")
      : t("app.title");
  });
}
