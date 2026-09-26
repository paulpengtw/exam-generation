import { useLangStore } from "../store/langStore";
import type { Lang } from "../i18n/messages";

const LANGS: { value: Lang; label: string }[] = [
  { value: "en-US", label: "English" },
  { value: "zh-TW", label: "中文" },
];

export default function LanguageSwitcher() {
  const lang = useLangStore((s) => s.lang);
  const setLang = useLangStore((s) => s.setLang);

  return (
    <div className="sentry-unmask inline-flex rounded border border-gray-300 overflow-hidden text-sm">
      {LANGS.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          onClick={() => setLang(value)}
          className={
            lang === value
              ? "px-3 py-1 bg-blue-600 text-white font-medium transition-colors duration-quick ease-signature"
              : "px-3 py-1 bg-white text-gray-700 hover:bg-gray-50 transition-colors duration-quick ease-signature"
          }
        >
          {label}
        </button>
      ))}
    </div>
  );
}
