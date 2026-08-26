export interface AdmittedParentEntry {
  admitted_by?: Record<string, readonly string[]>;
}

/** Return entries admitted by at least one resolved value for a parent key. */
export function filterEntriesByAdmittedParent<T extends AdmittedParentEntry>(
  entries: readonly T[],
  parentKey: string,
  resolvedParentValues: string | readonly string[] | undefined,
): T[] {
  const values = typeof resolvedParentValues === "string"
    ? [resolvedParentValues]
    : resolvedParentValues ?? [];
  if (values.length === 0) return [];

  return entries.filter((entry) => {
    const admittedValues = entry.admitted_by?.[parentKey];
    return Array.isArray(admittedValues) && values.some((value) => admittedValues.includes(value));
  });
}
