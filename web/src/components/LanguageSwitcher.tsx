import { useTranslation } from "react-i18next";

import {
  SUPPORTED_LANGUAGES,
  type SupportedLanguage,
} from "../i18n/config";
import { useLanguageStore } from "../store/languageStore";

interface LanguageSwitcherProps {
  className?: string;
}

const LABEL_KEYS: Record<SupportedLanguage, string> = {
  "zh-TW": "language.zh_tw",
  "en-US": "language.en_us",
};

export default function LanguageSwitcher({ className }: LanguageSwitcherProps) {
  const { t } = useTranslation();
  const language = useLanguageStore((s) => s.language);
  const setLanguage = useLanguageStore((s) => s.setLanguage);

  return (
    <select
      aria-label={t("language.label")}
      value={language}
      onChange={(e) => setLanguage(e.target.value as SupportedLanguage)}
      className={
        className ??
        "rounded border border-gray-300 bg-white px-2 py-1 text-sm font-medium text-gray-700 hover:bg-gray-50"
      }
    >
      {SUPPORTED_LANGUAGES.map((lang) => (
        <option key={lang} value={lang}>
          {t(LABEL_KEYS[lang])}
        </option>
      ))}
    </select>
  );
}
