import { useT } from "../i18n/useT";

export default function StagingBanner() {
  const t = useT();
  if (!import.meta.env.VITE_IS_STAGING) return null;
  return (
    <div className="sentry-unmask sticky top-0 z-50 bg-yellow-400 px-3 py-1.5 text-center text-sm font-medium text-yellow-950">
      {t("staging.banner")}
    </div>
  );
}
