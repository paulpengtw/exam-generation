import { describe, expect, it } from "vitest";

import { diffSnapshots } from "./snapshotDiff";

describe("diffSnapshots", () => {
  it("returns a changed scalar field with its old and new values", () => {
    expect(
      diffSnapshots(
        { 答案: "B", 題目: ["What is 2 + 2?"] },
        { 答案: "A", 題目: ["What is 2 + 2?"] },
      ),
    ).toEqual([
      { path: "答案", before: "B", after: "A" },
    ]);
  });

  it("reports a changed array item instead of the whole list", () => {
    expect(
      diffSnapshots(
        { 選項: ["甲", "乙", "丙"] },
        { 選項: ["甲", "改寫乙", "丙"] },
      ),
    ).toEqual([
      { path: "選項[1]", before: "乙", after: "改寫乙" },
    ]);
  });

  it("reports nested object fields and nested list items at their paths", () => {
    expect(
      diffSnapshots(
        {
          metadata: { grade: 8, note: "unchanged" },
          subquestions: [{ 題目: "第一小題", 答案解析: "原本的解析" }],
        },
        {
          metadata: { grade: 8, note: "unchanged" },
          subquestions: [{ 題目: "第一小題", 答案解析: "改寫後的解析" }],
        },
      ),
    ).toEqual([
      {
        path: "subquestions[0].答案解析",
        before: "原本的解析",
        after: "改寫後的解析",
      },
    ]);
  });
});
