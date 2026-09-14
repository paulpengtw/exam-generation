import { getSchemas, type Schemas } from "../api/client";

export type PoolGrade = number | null;

export interface CurriculumPool extends Schemas {
  poolGrade: PoolGrade;
}

export async function fetchCurriculumPool(subject: string, grade?: number): Promise<CurriculumPool> {
  const schemas = grade === undefined
    ? await getSchemas(subject)
    : await getSchemas(subject, grade);
  return { ...schemas, poolGrade: grade ?? null };
}
