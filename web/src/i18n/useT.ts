import { useLangStore } from "../store/langStore";
import { MESSAGES } from "./messages";

export function useT(): (key: string) => string {
  const lang = useLangStore((s) => s.lang);
  return (key: string) => MESSAGES[lang][key] ?? key;
}
