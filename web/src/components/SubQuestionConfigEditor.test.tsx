import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) =>
    key === "form.reporting_scale" ? "Reporting Scale" : key,
}));

import SubQuestionConfigEditor from "./SubQuestionConfigEditor";

const PISA_SCIENCE_TYPES = [
  { value: "Simple multiple-choice", instruction: "" },
  { value: "Complex multiple-choice", instruction: "" },
  { value: "Constructed response", instruction: "" },
];

const SOCIAL_STUDIES_TYPES = [
  { value: "選擇題", instruction: "" },
  { value: "開放式建構反應題", instruction: "" },
];

const CONTENT_TYPES = [
  { value: "純文字", instruction: "" },
  { value: "含圖片", instruction: "" },
];

function renderEditor(
  subject: string,
  questionTypes = SOCIAL_STUDIES_TYPES,
) {
  return render(
    <SubQuestionConfigEditor
      subject={subject}
      config={{}}
      questionTypes={questionTypes}
      contentTypes={CONTENT_TYPES}
      onChange={vi.fn()}
    />,
  );
}

function optionValues(select: HTMLElement): string[] {
  return Array.from(select.querySelectorAll("option"), (option) => option.value);
}

describe("SubQuestionConfigEditor subject gating", () => {
  it("renders Reporting Scale only for 自然科學", () => {
    renderEditor("social_studies");
    expect(
      screen.queryByText("Reporting Scale", { selector: "label" }),
    ).not.toBeInTheDocument();

    renderEditor("natural_sciences", PISA_SCIENCE_TYPES);
    expect(
      screen.getByText("Reporting Scale", { selector: "label" }),
    ).toBeInTheDocument();
  });

  it("uses the PISA-Science question-type pool for 自然科學 and the 社會領域 pool otherwise", () => {
    const { unmount } = renderEditor("natural_sciences", [
      ...PISA_SCIENCE_TYPES,
      ...SOCIAL_STUDIES_TYPES,
    ]);
    expect(optionValues(screen.getAllByRole("combobox")[0])).toEqual([
      "",
      "Simple multiple-choice",
      "Complex multiple-choice",
      "Constructed response",
    ]);

    unmount();
    renderEditor("social_studies");
    expect(optionValues(screen.getAllByRole("combobox")[0])).toEqual([
      "",
      "選擇題",
      "開放式建構反應題",
    ]);
  });

  it("reflects the surviving question types returned by the schemas API", () => {
    renderEditor("social_studies", [
      { value: "選擇題", instruction: "" },
      { value: "開放式建構反應題", instruction: "" },
    ]);

    expect(optionValues(screen.getAllByRole("combobox")[0])).toEqual([
      "",
      "選擇題",
      "開放式建構反應題",
    ]);
    expect(screen.queryByRole("option", { name: "封閉式建構反應題" })).not.toBeInTheDocument();
  });
});
