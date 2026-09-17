import { parseFormFields } from "../../formDraft";
import type { FormFields } from "../../../components/ParamForm";
import type { FormWorkspaceSnapshot } from "./types";

export function exportFormWorkspace(fields: FormFields): FormWorkspaceSnapshot {
  return { kind: "form", version: 1, fields: { ...fields } };
}

export function importFormWorkspace(raw: unknown): FormFields | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const snapshot = raw as Record<string, unknown>;
  if (snapshot.kind !== "form" || snapshot.version !== 1) return null;
  return parseFormFields(snapshot.fields);
}
