export function rebuildSubquestionSlots<T extends object>(
  configs: readonly T[],
  count: number | "",
): T[] {
  if (typeof count !== "number" || count <= 0) return [];
  if (configs.length >= count) return configs.slice(0, count);
  return [
    ...configs,
    ...Array.from({ length: count - configs.length }, () => ({} as T)),
  ];
}

/**
 * Remove carried slot provenance for the question whose structural count was
 * redrawn. The resolver response supplies provenance for the current slots;
 * other questions' badges remain carried through unchanged.
 */
export function filterDrawnAfterSubquestionCountRedraw(
  paths: readonly string[],
  redraws: Readonly<Record<string, number>>,
): string[] {
  const affectedPrefixes = Object.entries(redraws)
    .filter(([path, counter]) => counter > 0 && (
      path === "sub_question_count" || path.endsWith(".sub_question_count")
    ))
    .map(([path]) => path === "sub_question_count"
      ? { countPath: path, slotPrefix: "subquestion_configs[" }
      : {
          countPath: path,
          slotPrefix: `${path.slice(0, -".sub_question_count".length)}.subquestion_configs[`,
        });

  if (affectedPrefixes.length === 0) return [...paths];
  return paths.filter((path) => !affectedPrefixes.some(({ countPath, slotPrefix }) =>
    path === countPath || path.startsWith(slotPrefix)));
}
