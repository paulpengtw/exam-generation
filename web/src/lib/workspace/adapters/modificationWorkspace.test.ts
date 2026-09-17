import { describe, expect, it } from "vitest";
import type { ExamQuestion } from "../../../hooks/useGenerate";
import type { ModificationSegmentRequest } from "../../../api/client";
import type { ModificationWorkspaceSnapshot } from "./types";
import { exportModificationWorkspace, importModificationWorkspace } from "./modificationWorkspace";

const verifiedHistoryQuestion: ExamQuestion = {
  id: "history-question",
  情境: ["公共"],
  題型種類: "題組題",
  題型: "選擇題",
  閱讀歷程: ["Legacy reading process"],
  文本形式: "Legacy text form",
  核心問題: "A verified core question",
  文本: "A passage that can be selected",
  subquestions: [
    {
      id: "sub-1",
      序號: 1,
      年級: 8,
      科目: ["地理"],
      核心素養: ["社-J-A2"],
      學習內容: [],
      學習表現: [],
      出題概念: "",
      題型: "選擇題",
      題目: "A subquestion",
      答案: "B",
      答案解析: "Because B.",
      評分規準: [],
    },
  ],
  題目: ["A passage that can be selected", "A subquestion"],
  正確解題分析: ["B is correct."],
  verification: { passed: true },
};

const segment: ModificationSegmentRequest = {
  field_path: "文本", start: 2, end: 9, quoted_text: "passage",
};
const live: Omit<ModificationWorkspaceSnapshot, "kind" | "version"> = {
  recordId: "history-record", questionId: "history-question",
  annotations: [{ segments: [segment], instruction: "Clarify this passage" }],
  replacement: {
    record_id: "replacement-record", question: verifiedHistoryQuestion,
    ripple_report: ["Updated the passage"], verified: true,
    verification: { passed: true }, failure_details: null,
  },
};

describe("modification workspace adapter", () => {
  it("round-trips annotations and a received replacement question", () => {
    const snapshot = exportModificationWorkspace(live);
    expect(snapshot).toEqual({ ...live, kind: "modification", version: 1 });
    expect(importModificationWorkspace(JSON.parse(JSON.stringify(snapshot)))).toEqual(live);
  });

  it("accepts empty annotations and no replacement", () => {
    const state = { ...live, annotations: [], replacement: null };
    expect(importModificationWorkspace(exportModificationWorkspace(state))).toEqual(state);
  });

  it("preserves multiple selected segments and an unfinished instruction", () => {
    const state = { ...live, annotations: [{ segments: [segment,
      { field_path: "subquestions[0].題目", start: 0, end: 1, quoted_text: "A" }], instruction: "" }] };
    expect(importModificationWorkspace(exportModificationWorkspace(state))).toEqual(state);
  });

  it.each([null, 42, "modification", [], {}])("rejects a malformed envelope %#", (raw) => {
    expect(importModificationWorkspace(raw)).toBeNull();
  });

  it.each([
    { kind: "confirmation" }, { version: 2 }, { version: "1" },
    { recordId: "" }, { recordId: 42 }, { questionId: "" }, { questionId: null },
    { annotations: {} }, { annotations: [null] }, { annotations: [[]] },
    { annotations: [{ segments: null, instruction: "edit" }] },
    { annotations: [{ segments: [null], instruction: "edit" }] },
    { annotations: [{ segments: [[]], instruction: "edit" }] },
    { annotations: [{ segments: [segment], instruction: 42 }] },
    { annotations: [{ segments: [{ path: "文本", start: 2, end: 9, text: "passage" }], instruction: "edit" }] },
    { replacement: [] }, { replacement: {} }, { replacement: { question: null } },
    { replacement: { question: [] } },
  ])("rejects invalid modification fields %#", (patch) => {
    expect(importModificationWorkspace({ ...live, kind: "modification", version: 1, ...patch })).toBeNull();
  });

  it.each([
    { field_path: 42 }, { quoted_text: null }, { start: 0.5 }, { end: "9" },
    { start: Number.NaN }, { end: Number.POSITIVE_INFINITY },
  ])("validates the real ModificationSegmentRequest fields %#", (patch) => {
    expect(importModificationWorkspace({ ...live, kind: "modification", version: 1,
      annotations: [{ segments: [{ ...segment, ...patch }], instruction: "edit" }],
    })).toBeNull();
  });
});
