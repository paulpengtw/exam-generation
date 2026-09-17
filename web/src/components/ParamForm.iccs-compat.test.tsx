import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
const planCoreQuestionsMock = vi.hoisted(() => vi.fn());
const previewGenerateMock = vi.hoisted(() => vi.fn());
const resolveGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: planCoreQuestionsMock,
  previewGenerate: previewGenerateMock,
  resolveGenerate: resolveGenerateMock,
}));
vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";

function resolveConfirmationPayload(payload: Record<string, unknown>) {
  const sourceRows = typeof payload.per_question_params === "string"
    ? JSON.parse(payload.per_question_params) as Record<string, unknown>[]
    : [];
  const base = Object.fromEntries(
    Object.entries(payload).filter(([key]) => ![
      "subject", "count", "per_question_params", "drawn", "redraws",
    ].includes(key)),
  );
  const sourceConfigs = typeof payload.subquestion_configs === "string"
    ? JSON.parse(payload.subquestion_configs) as Record<string, unknown>[]
    : [];
  const isPublicSubject = Array.isArray(payload.subject_filter) &&
    payload.subject_filter.includes("公民與社會");
  const resolvedConfigs = sourceConfigs.map((config) => ({
    ...config,
    ...(isPublicSubject && !Array.isArray(config.learning_content)
      ? { learning_content: [ALLOWED_LC] }
      : {}),
    ...(isPublicSubject && !Array.isArray(config.learning_performance)
      ? { learning_performance: [ALLOWED_LP] }
      : {}),
  }));
  const drawn = isPublicSubject
    ? resolvedConfigs.flatMap((_, subquestionIndex) => [
        `per_question_params[0].subquestion_configs[${subquestionIndex}].learning_content`,
        `per_question_params[0].subquestion_configs[${subquestionIndex}].learning_performance`,
      ])
    : [];
  return {
    payload: {
      ...payload,
      per_question_params: JSON.stringify(sourceRows.map((row) => ({
        ...base,
        ...row,
        subquestion_configs: JSON.stringify(resolvedConfigs),
      }))),
    },
    drawn,
  };
}

const DOMAIN = "Civic Principles";
const ALLOWED_LC = "公Ad-Ⅳ-1";
const OUT_OF_DOMAIN_LC = "公Aa-Ⅳ-1";
const ALLOWED_LP = "社1a-Ⅳ-1";
const OUT_OF_DOMAIN_LP = "公1c-Ⅳ-1";

const SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  認知歷程: [{ value: "Knowing–Defining and Describing", instruction: "" }],
  內容領域: [
    { value: "Civic Institutions and Systems", instruction: "" },
    { value: DOMAIN, instruction: "" },
  ],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "公民與社會", instruction: "" }],
  核心素養: [{ value: "社-J-A2", instruction: "" }],
  學習表現: [
    { value: ALLOWED_LP, instruction: "共享社會領域表現", 科目: "社", admitted_by: { 科目: ["歷史", "地理", "公民與社會", "跨科"], "內容領域": [DOMAIN] } },
    { value: OUT_OF_DOMAIN_LP, instruction: "公民表現", 科目: "公", admitted_by: { 科目: ["公民與社會", "跨科"], "內容領域": ["Civic Roles and Identities"] } },
  ],
  學習內容: [
    {
      value: ALLOWED_LC,
      instruction: "人權普遍性保障原則",
      科目: "公",
      admitted_by: { 科目: ["公民與社會", "跨科"], 內容領域: [DOMAIN] },
    },
    {
      value: OUT_OF_DOMAIN_LC,
      instruction: "公民角色與認同",
      科目: "公",
      admitted_by: { 科目: ["公民與社會", "跨科"], 內容領域: ["Civic Roles and Identities"] },
    },
  ],
  內容領域_mapping: {
    [ALLOWED_LC]: [DOMAIN],
    [OUT_OF_DOMAIN_LC]: ["Civic Roles and Identities"],
  },
  digital_only_question_types: [],
};

function getFirstSubquestionCard() {
  const question = within(screen.getByRole("region", { name: "第1題" }));
  const heading = question.getByRole("heading", { name: "各小題配置", level: 4 });
  const section = within(heading.closest("section") as HTMLElement);
  return within(section.getAllByRole("listitem")[0]);
}

function readChipCodes(pickerRoot: HTMLElement): string[] {
  return Array.from(pickerRoot.querySelectorAll("span.inline-flex span.font-medium"))
    .map((element) => element.textContent ?? "");
}

describe("#506 confirmation ICCS compatibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "", verify: "", correct: "" },
    });
    planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) =>
      resolveConfirmationPayload(payload));
  });

  it("公民 confirmation card limits LC SearchPicker/重抽 to the drawn domain pool but leaves 學習表現 unfiltered (#833)", async () => {
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{
          subject_filter: "公民與社會",
          content_domain: DOMAIN,
          sub_question_count: 3,
          // #841: OUT_OF_DOMAIN_LC does not admit DOMAIN, so pinning it here
          // too would make the restored 內容領域 a genuine conflict (marked
          // invalid, 產生 disabled) — this test is about the confirmation
          // card's own domain-scoped pool, not that restore-conflict path,
          // so only the DOMAIN-admitting code is pinned at the top level.
          learning_content: [ALLOWED_LC],
          subquestion_configs: [{}, {}, {}],
        }}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await screen.findByRole("heading", { name: "發送前確認設定" });

    const card = getFirstSubquestionCard();
    const lcInput = card.getByLabelText("學習內容");
    const lpInput = card.getByLabelText("學習表現");

    fireEvent.change(lcInput, { target: { value: "公Aa" } });
    expect(card.queryByText(OUT_OF_DOMAIN_LC)).not.toBeInTheDocument();

    // #833: 學習表現 has no 內容領域 parent — the out-of-domain code (公1c-Ⅳ-1,
    // the only stage-4 公 學習表現 code) is still offered and selectable here.
    fireEvent.change(lpInput, { target: { value: "公1c" } });
    expect(await card.findByText(OUT_OF_DOMAIN_LP)).toBeInTheDocument();

    const lpPickerRoot = lpInput.parentElement as HTMLElement;
    const lpOption = within(lpPickerRoot).getByText(OUT_OF_DOMAIN_LP);
    act(() => {
      fireEvent.mouseDown(lpOption);
    });
    await waitFor(() =>
      expect(readChipCodes(lpPickerRoot)).toEqual([ALLOWED_LP, OUT_OF_DOMAIN_LP]),
    );

    const lcPickerRoot = lcInput.parentElement as HTMLElement;
    await waitFor(() => expect(readChipCodes(lcPickerRoot)).toEqual([ALLOWED_LC]));

    const chip = within(lcPickerRoot).getByText(ALLOWED_LC).closest("span.inline-flex") as HTMLElement;
    act(() => {
      fireEvent.click(within(chip).getByRole("button", { name: "×" }));
    });

    await waitFor(() => expect(readChipCodes(lcPickerRoot)).toEqual([ALLOWED_LC]));
  });

  it("歷史與地理 keep their LC/LP pickers unfiltered by an ICCS domain", async () => {
    const cases = [
      {
        subjectFilter: "歷史",
        prefix: "歷",
        lc: "歷Aa-Ⅳ-1",
        lp: "歷1a-Ⅳ-1",
      },
      {
        subjectFilter: "地理",
        prefix: "地",
        lc: "地Aa-Ⅳ-1",
        lp: "地1a-Ⅳ-1",
      },
    ];

    for (const current of cases) {
      getSchemasMock.mockResolvedValue({
        ...SOCIAL_SCHEMA,
        科目: [{ value: current.subjectFilter, instruction: "" }],
        學習表現: [{ value: current.lp, instruction: "非公民學習表現", 科目: current.prefix, admitted_by: { 科目: [current.subjectFilter, "跨科"] } }],
        學習內容: [{ value: current.lc, instruction: "非公民學習內容", 科目: current.prefix, admitted_by: { 科目: [current.subjectFilter, "跨科"] } }],
      });
      const view = render(
        <ParamForm
          subject="social_studies"
          onSubmit={vi.fn()}
          disabled={false}
          initialParams={{
            subject_filter: current.subjectFilter,
            content_domain: DOMAIN,
            sub_question_count: 3,
            subquestion_configs: [{ learning_content: [current.lc], learning_performance: [current.lp] }, {}, {}],
          }}
        />,
      );

      fireEvent.click(await screen.findByRole("button", { name: "產生" }));
      await screen.findByRole("heading", { name: "發送前確認設定" });
      const card = getFirstSubquestionCard();
      expect(card.getByText(current.lc)).toBeInTheDocument();
      expect(card.getByText(current.lp)).toBeInTheDocument();
      view.unmount();
    }
  });
});
