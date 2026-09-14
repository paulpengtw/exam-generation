import { beforeEach, describe, expect, it, vi } from "vitest";
import { getSchemas, type Schemas } from "../api/client";
import { fetchCurriculumPool } from "./curriculumPool";

vi.mock("../api/client", () => ({
  getSchemas: vi.fn(),
}));

const mockGetSchemas = vi.mocked(getSchemas);

const schemas: Schemas = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9, 10, 11, 12],
  情境: [{ value: "Personal", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "Simple-multiple-choice", instruction: "" }],
  數學思考: [],
  科目: [{ value: "自然科學", instruction: "" }],
  學習表現: [{ value: "tr-IV-1", instruction: "學習表現說明", 科目: "" }],
  學習內容: [{ value: "INc-IV-1", instruction: "學習內容說明", 科目: "" }],
};

describe("fetchCurriculumPool", () => {
  beforeEach(() => {
    mockGetSchemas.mockReset();
  });

  it("preserves schema fields and tags a grade-less request with null", async () => {
    mockGetSchemas.mockResolvedValue(schemas);

    await expect(fetchCurriculumPool("natural_sciences")).resolves.toEqual({
      ...schemas,
      poolGrade: null,
    });
    expect(mockGetSchemas).toHaveBeenCalledWith("natural_sciences");
    expect(mockGetSchemas.mock.calls[0].length).toBe(1);
  });

  it("passes the requested grade and tags the returned pool with it", async () => {
    const gradeSchemas = { ...schemas, 學習階段: "第五學習階段" };
    mockGetSchemas.mockResolvedValue(gradeSchemas);

    await expect(fetchCurriculumPool("natural_sciences", 10)).resolves.toEqual({
      ...gradeSchemas,
      poolGrade: 10,
    });
    expect(mockGetSchemas).toHaveBeenCalledWith("natural_sciences", 10);
  });

  it("tags the pool from the requested grade even when the response has a different 學習階段", async () => {
    mockGetSchemas.mockResolvedValue(schemas);

    const pool = await fetchCurriculumPool("natural_sciences", 10);

    expect(pool.學習階段).toBe("第四學習階段");
    expect(pool.poolGrade).toBe(10);
  });

  it("rejects with the same error when the schema request fails", async () => {
    const error = new Error("Schema request failed");
    mockGetSchemas.mockRejectedValue(error);

    await expect(fetchCurriculumPool("natural_sciences", 10)).rejects.toBe(error);
  });
});
