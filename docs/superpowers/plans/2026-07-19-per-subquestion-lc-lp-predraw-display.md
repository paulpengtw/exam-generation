# Per-子題 Learning Content/Performance Pre-Draw + Confirmation Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the web Generate confirmation screen, show each 子題's randomly-drawn 學習內容 and 學習表現 codes the same way the global 學習內容/學習表現 pre-draw is shown today — pre-drawing them on the frontend when the user left the per-小題 selection empty, and sending the pre-drawn codes to the backend as part of `subquestion_configs`.

**Architecture:** All work happens inside a single React component (`web/src/components/ParamForm.tsx`). Extract the existing global pre-draw shuffle into a small utility, reuse it in `handleSubmit` to fill each 子題's empty `learning_content` / `learning_performance` from the same pool the global draw uses, stash the resolved (pre-`JSON.stringify`) 子題 configs in a new piece of state, and render a structured per-子題 block inside the confirmation view. Applies to `social_studies` and `natural_sciences` only (math has no 子題設定 panel).

**Tech Stack:** React 19.2.5, TypeScript, Vitest 4 + `@testing-library/react`, existing `useT()` i18n hook + `langStore`. No new dependencies.

## Global Constraints

- Randomness stays on the frontend and is `Math.random`-based, matching the existing global pre-draw at `web/src/components/ParamForm.tsx:546-576`. No seeded RNG.
- What the confirmation screen shows must equal what is sent to the backend, per the "Web confirmation dialog pre-draw" invariant in `CLAUDE.md`.
- Backend contract does not change. `server/generate/models.py` `GenerateParams.subquestion_configs` already accepts `learning_content: list[str]` and `learning_performance: list[str]` per-row.
- Subjects covered: `social_studies` and `natural_sciences`. `math` is out of scope (no 子題設定 panel).
- No parallel copies of the shuffle logic — the extracted utility is the single source of truth for both global and per-小題 pre-draws.
- Empty availability pool ⇒ no pre-draw for that field on that 小題, matching the existing global behavior at `ParamForm.tsx:549-550` (gates on `availableLearningPerformance.length`).
- Per-小題 configs with an explicit user selection are preserved verbatim — the auto-draw never overwrites them.
- The auto-drawn arrays travel inside `subquestion_configs[*].learning_content` / `learning_performance`. Do NOT invent new backend fields; internal flags like `_lcWasAutoDrawn` / `_lpWasAutoDrawn` are stripped before `JSON.stringify`.
- Draw counts: 學習內容 → 1–3 items; 學習表現 → 1–2 items (matches the existing SS/NS global-pre-draw bounds).

---

### Task 1: Extract shared `drawRandomSubset` utility

**Files:**
- Create: `web/src/utils/drawRandomSubset.ts`
- Create: `web/src/utils/drawRandomSubset.test.ts`
- Modify: `web/src/components/ParamForm.tsx:546-576` (replace the two inline shuffle blocks with calls to the new util)

**Interfaces:**
- Produces:
  ```ts
  export function drawRandomSubset<T>(pool: readonly T[], min: number, max: number): T[]
  ```
  Returns a fresh array of `n` randomly-selected items from `pool`, where `n` is a uniformly random integer in `[min, min(max, pool.length)]`. Returns `[]` when `pool.length === 0` or `min <= 0`. RNG source: `Math.random()`; no seeding.

- [ ] **Step 1: Write the failing tests**

Create `web/src/utils/drawRandomSubset.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import { drawRandomSubset } from "./drawRandomSubset";

describe("drawRandomSubset", () => {
  it("returns empty array for empty pool", () => {
    expect(drawRandomSubset([], 1, 3)).toEqual([]);
  });

  it("returns empty array when min <= 0", () => {
    expect(drawRandomSubset(["a", "b"], 0, 3)).toEqual([]);
  });

  it("returns exactly min items when Math.random returns 0", () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    expect(drawRandomSubset(["a", "b", "c", "d"], 1, 3)).toHaveLength(1);
    vi.restoreAllMocks();
  });

  it("returns exactly max items when Math.random returns near 1", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.9999);
    expect(drawRandomSubset(["a", "b", "c", "d", "e"], 1, 3)).toHaveLength(3);
    vi.restoreAllMocks();
  });

  it("clamps max to pool length", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.9999);
    expect(drawRandomSubset(["a", "b"], 1, 5)).toHaveLength(2);
    vi.restoreAllMocks();
  });

  it("returns unique items from the pool", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    const result = drawRandomSubset(["a", "b", "c", "d"], 2, 3);
    const pool = new Set(["a", "b", "c", "d"]);
    for (const item of result) expect(pool.has(item)).toBe(true);
    expect(new Set(result).size).toBe(result.length);
    vi.restoreAllMocks();
  });
});
```

- [ ] **Step 2: Verify tests fail**

Run: `cd web && pnpm vitest run src/utils/drawRandomSubset.test.ts`
Expected: FAIL — "Cannot find module './drawRandomSubset'".

- [ ] **Step 3: Implement the utility**

Create `web/src/utils/drawRandomSubset.ts`:

```ts
export function drawRandomSubset<T>(pool: readonly T[], min: number, max: number): T[] {
  if (pool.length === 0 || min <= 0) return [];
  const upper = Math.min(max, pool.length);
  const lower = Math.min(min, upper);
  const range = Math.max(1, upper - lower + 1);
  const count = Math.floor(Math.random() * range) + lower;
  const shuffled = [...pool].sort(() => Math.random() - 0.5);
  return shuffled.slice(0, count);
}
```

- [ ] **Step 4: Verify util tests pass**

Run: `cd web && pnpm vitest run src/utils/drawRandomSubset.test.ts`
Expected: PASS — all 6 tests.

- [ ] **Step 5: Swap the util into `ParamForm.handleSubmit`**

Add the import to `web/src/components/ParamForm.tsx` (top of file, with the other `../utils` imports if any, otherwise after the `../hooks` imports):

```ts
import { drawRandomSubset } from "../utils/drawRandomSubset";
```

Replace the inline 學習表現 shuffle block at `ParamForm.tsx:546-557` with:

```ts
if (
  isCurriculumSubject &&
  (!p.learning_performance || p.learning_performance.length === 0) &&
  availableLearningPerformance.length > 0
) {
  const maxDraw = subject === "math" ? 3 : 2;
  finalLp = drawRandomSubset(
    availableLearningPerformance.map((e) => e.value),
    1,
    maxDraw,
  );
  setLpWasAutoDrawn(true);
}
```

Replace the inline 學習內容 shuffle block at `ParamForm.tsx:562-576` with:

```ts
if (
  (subject === "social_studies" || subject === "natural_sciences") &&
  (!p.learning_content || p.learning_content.length === 0) &&
  availableLearningContent.length > 0
) {
  finalLc = drawRandomSubset(
    availableLearningContent.map((e) => e.value),
    1,
    3,
  );
  setLcWasAutoDrawn(true);
}
```

- [ ] **Step 6: Confirm the existing ParamForm suite still passes**

Run: `cd web && pnpm vitest run src/components/ParamForm`
Expected: PASS on `ParamForm.test.tsx`, `ParamForm.coverage.test.tsx`, `ParamForm.model-selection.test.tsx`.

- [ ] **Step 7: Commit**

```bash
git add web/src/utils/drawRandomSubset.ts web/src/utils/drawRandomSubset.test.ts web/src/components/ParamForm.tsx
git commit -m "refactor(web): extract drawRandomSubset util for confirmation pre-draw"
```

---

### Task 2: Pre-draw per-子題 LC/LP into the outbound payload

**Files:**
- Modify: `web/src/components/ParamForm.tsx:523-540` (extend `effectiveSubquestionConfigs` construction)
- Modify: `web/src/components/ParamForm.tsx:579-616` (`setPendingParams` + parallel resolved state)
- Modify: `web/src/components/ParamForm.tsx:195-196` (new state hook)
- Create: `web/src/components/ParamForm.subquestion-predraw.test.tsx`

**Interfaces:**
- Consumes: `drawRandomSubset` from Task 1; `availableLearningContent` / `availableLearningPerformance` (existing derived arrays, `ParamForm.tsx:439-467`); `subquestionConfigs`, `subQuestionCount`, `subQuestionCountNumber` (existing state).
- Produces:
  - Each row of the JSON-serialized `subquestion_configs` now carries pre-drawn `learning_content` / `learning_performance` when the per-小題 row was empty AND the corresponding availability pool was non-empty AND `subQuestionCount` is set. The pre-drawn arrays flow through the existing `JSON.stringify` at `ParamForm.tsx:610-613` unchanged.
  - Component-local state:
    ```ts
    const [pendingResolvedSubquestionConfigs, setPendingResolvedSubquestionConfigs] =
      useState<(SubQuestionConfig & { _lcWasAutoDrawn?: boolean; _lpWasAutoDrawn?: boolean })[]>([]);
    ```
    Task 3 renders from it. The `_lc/lpWasAutoDrawn` flags are NEVER included in the outbound JSON.

- [ ] **Step 1: Write the failing payload test**

Create `web/src/components/ParamForm.subquestion-predraw.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (k: string, opts?: Record<string, unknown>) => {
    if (opts && "n" in opts) return `${k}:${String(opts.n)}`;
    return k;
  },
}));

import ParamForm from "./ParamForm";

const NS_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "Personal", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "Simple-multiple-choice", instruction: "" }],
  科學能力: [{ value: "能力一", instruction: "" }],
  question_style: [{ value: "standard", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "自然科學", instruction: "" }],
  學習表現: [
    { value: "tr-IV-1", instruction: "", 科目: "自然科學" },
    { value: "tr-IV-2", instruction: "", 科目: "自然科學" },
    { value: "tr-IV-3", instruction: "", 科目: "自然科學" },
  ],
  學習內容: [
    { value: "INc-IV-1", instruction: "", 科目: "自然科學" },
    { value: "INc-IV-2", instruction: "", 科目: "自然科學" },
    { value: "INc-IV-3", instruction: "", 科目: "自然科學" },
    { value: "INc-IV-4", instruction: "", 科目: "自然科學" },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  getSchemasMock.mockResolvedValue(NS_SCHEMA);
  getAvailableModelsMock.mockResolvedValue({ allowed: [], defaults: { plan: "", execute: "" } });
});

describe("per-子題 pre-draw (natural_sciences)", () => {
  it("fills empty per-小題 learning_content/performance with a random subset before submit", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="natural_sciences" onSubmit={onSubmit} />);
    await waitFor(() => screen.getByText(/小題數量|sub_question_count/i));

    await screen.findByPlaceholderText("自動 3-7");
    fireEvent.change(screen.getByPlaceholderText("自動 3-7"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /form\.btn_generate/i }));

    const confirmBtn = await screen.findByRole("button", { name: /form\.btn_confirm_send/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const payload = onSubmit.mock.calls[0][0];
    const rows = JSON.parse(payload.subquestion_configs);
    expect(rows).toHaveLength(3);
    for (const row of rows) {
      expect(Array.isArray(row.learning_content)).toBe(true);
      expect(row.learning_content.length).toBeGreaterThanOrEqual(1);
      expect(row.learning_content.length).toBeLessThanOrEqual(3);
      expect(Array.isArray(row.learning_performance)).toBe(true);
      expect(row.learning_performance.length).toBeGreaterThanOrEqual(1);
      expect(row.learning_performance.length).toBeLessThanOrEqual(2);
      for (const code of row.learning_content) {
        expect(["INc-IV-1", "INc-IV-2", "INc-IV-3", "INc-IV-4"]).toContain(code);
      }
      for (const code of row.learning_performance) {
        expect(["tr-IV-1", "tr-IV-2", "tr-IV-3"]).toContain(code);
      }
      expect(row).not.toHaveProperty("_lcWasAutoDrawn");
      expect(row).not.toHaveProperty("_lpWasAutoDrawn");
    }
  });
});
```

- [ ] **Step 2: Verify the payload test fails**

Run: `cd web && pnpm vitest run src/components/ParamForm.subquestion-predraw.test.tsx`
Expected: FAIL — rows have no `learning_content` / `learning_performance` (today they are dropped when empty per-小題, per `ParamForm.tsx:534-535`).

- [ ] **Step 3: Add the new state hook**

At `web/src/components/ParamForm.tsx:195-196` (immediately after the existing `lpWasAutoDrawn` / `lcWasAutoDrawn` state), add:

```ts
const [pendingResolvedSubquestionConfigs, setPendingResolvedSubquestionConfigs] = useState<
  (SubQuestionConfig & { _lcWasAutoDrawn?: boolean; _lpWasAutoDrawn?: boolean })[]
>([]);
```

- [ ] **Step 4: Replace the `effectiveSubquestionConfigs` construction with a resolving+stripping build**

In `web/src/components/ParamForm.tsx`, replace the block at lines 523-540 with:

```ts
const lcPool = availableLearningContent.map((e) => e.value);
const lpPool = availableLearningPerformance.map((e) => e.value);
const shouldDrawPerSubq =
  (subject === "social_studies" || subject === "natural_sciences") &&
  subQuestionCount !== "";

const effectiveSubquestionConfigsInternal: (SubQuestionConfig & {
  _lcWasAutoDrawn?: boolean;
  _lpWasAutoDrawn?: boolean;
})[] = shouldDrawPerSubq
  ? subquestionConfigs
      .slice(0, subQuestionCountNumber)
      .map((cfg) => {
        const hasExplicitLc = (cfg.learning_content?.length ?? 0) > 0;
        const hasExplicitLp = (cfg.learning_performance?.length ?? 0) > 0;
        const resolvedLc = hasExplicitLc
          ? cfg.learning_content
          : lcPool.length > 0
            ? drawRandomSubset(lcPool, 1, 3)
            : undefined;
        const resolvedLp = hasExplicitLp
          ? cfg.learning_performance
          : lpPool.length > 0
            ? drawRandomSubset(lpPool, 1, 2)
            : undefined;
        return {
          ...cfg,
          learning_content: resolvedLc?.length ? resolvedLc : undefined,
          learning_performance: resolvedLp?.length ? resolvedLp : undefined,
          _lcWasAutoDrawn: !hasExplicitLc && !!resolvedLc?.length,
          _lpWasAutoDrawn: !hasExplicitLp && !!resolvedLp?.length,
        };
      })
  : [];

const effectiveSubquestionConfigs: SubQuestionConfig[] = effectiveSubquestionConfigsInternal.map(
  ({ _lcWasAutoDrawn: _lc, _lpWasAutoDrawn: _lp, ...rest }) => rest,
);

const hasSubquestionConfig = effectiveSubquestionConfigs.some(
  (c) =>
    c.question_type ||
    c.instruction ||
    c.content_type ||
    c.image_generation_mode ||
    c.question_word_limit !== undefined ||
    c.option_word_limit !== undefined ||
    c.text_word_limit !== undefined ||
    c.reporting_scale !== undefined ||
    (c.learning_content?.length ?? 0) > 0 ||
    (c.learning_performance?.length ?? 0) > 0,
);
```

Verify the `shouldSendSubquestionConfigs` gate at line ~540 still evaluates to `hasSubquestionConfig`. Do not change the `JSON.stringify` line at `ParamForm.tsx:610-613`.

- [ ] **Step 5: Populate the resolved state alongside `pendingParams`**

Inside the `setPendingParams({...})` block starting at `ParamForm.tsx:579`, add — immediately before the `setPendingParams(` call — the line:

```ts
setPendingResolvedSubquestionConfigs(effectiveSubquestionConfigsInternal);
```

- [ ] **Step 6: Verify the payload test passes**

Run: `cd web && pnpm vitest run src/components/ParamForm.subquestion-predraw.test.tsx`
Expected: PASS.

- [ ] **Step 7: Regression check on the rest of the ParamForm suite**

Run: `cd web && pnpm vitest run src/components/ParamForm`
Expected: PASS on `ParamForm.test.tsx`, `ParamForm.coverage.test.tsx`, `ParamForm.model-selection.test.tsx`, and the new file.

- [ ] **Step 8: Commit**

```bash
git add web/src/components/ParamForm.tsx web/src/components/ParamForm.subquestion-predraw.test.tsx
git commit -m "feat(web): pre-draw per-子題 學習內容/學習表現 into outbound payload"
```

---

### Task 3: Render per-子題 LC/LP in the confirmation screen

**Files:**
- Modify: `web/src/components/ParamForm.tsx:670-672` (remove the raw JSON `各小題配置` label row)
- Modify: `web/src/components/ParamForm.tsx:681-763` (extend confirmation JSX with a structured per-子題 section below the existing 學習內容 block)
- Modify: `web/src/i18n/messages.ts` (add per-子題 keys — en-US block near lines 137-140 AND zh-TW block near lines 344-347)
- Modify: `web/src/components/ParamForm.subquestion-predraw.test.tsx` (add rendering assertions)

**Interfaces:**
- Consumes: `pendingResolvedSubquestionConfigs` from Task 2; existing `schemas` state; the i18n keys added below.
- Produces (i18n): keys `form.confirm_subquestion_heading`, `form.confirm_subquestion_row_title`, `form.confirm_subq_lp_selected`, `form.confirm_subq_lp_random_pool`, `form.confirm_subq_lc_selected`, `form.confirm_subq_lc_random_pool`, `form.confirm_subq_lp_empty`, `form.confirm_subq_lc_empty`.

- [ ] **Step 1: Add the new i18n keys (en-US + zh-TW)**

In `web/src/i18n/messages.ts` en-US block (immediately after the existing `form.confirm_lc_random_pool` line around 140), add:

```ts
"form.confirm_subquestion_heading": "Per-sub-question configuration",
"form.confirm_subquestion_row_title": "Sub-question {n}",
"form.confirm_subq_lp_selected": "Learning performance ({n} selected)",
"form.confirm_subq_lp_random_pool": "Learning performance ({n} pre-drawn from pool)",
"form.confirm_subq_lc_selected": "Learning content ({n} selected)",
"form.confirm_subq_lc_random_pool": "Learning content ({n} pre-drawn from pool)",
"form.confirm_subq_lp_empty": "Learning performance: falls back to global pool at generation time",
"form.confirm_subq_lc_empty": "Learning content: falls back to global pool at generation time",
```

In the zh-TW block (immediately after the existing `form.confirm_lc_random_pool` line around 347), add:

```ts
"form.confirm_subquestion_heading": "各小題配置",
"form.confirm_subquestion_row_title": "第 {n} 小題",
"form.confirm_subq_lp_selected": "學習表現（已選 {n} 項）",
"form.confirm_subq_lp_random_pool": "學習表現（隨機抽取 {n} 項）",
"form.confirm_subq_lc_selected": "學習內容（已選 {n} 項）",
"form.confirm_subq_lc_random_pool": "學習內容（隨機抽取 {n} 項）",
"form.confirm_subq_lp_empty": "學習表現：生成時將沿用全域抽樣池",
"form.confirm_subq_lc_empty": "學習內容：生成時將沿用全域抽樣池",
```

- [ ] **Step 2: Write the failing render test**

Append to `web/src/components/ParamForm.subquestion-predraw.test.tsx`:

```tsx
it("renders each 子題's pre-drawn LC/LP codes in the confirmation screen", async () => {
  const onSubmit = vi.fn();
  render(<ParamForm subject="natural_sciences" onSubmit={onSubmit} />);
  await screen.findByPlaceholderText("自動 3-7");
  fireEvent.change(screen.getByPlaceholderText("自動 3-7"), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: /form\.btn_generate/i }));

  await waitFor(() => screen.getByText("form.confirm_subquestion_heading"));
  expect(screen.getByText("form.confirm_subquestion_row_title:1")).toBeInTheDocument();
  expect(screen.getByText("form.confirm_subquestion_row_title:2")).toBeInTheDocument();

  const section = screen
    .getByText("form.confirm_subquestion_heading")
    .closest("section")!;
  const html = section.innerHTML;
  const lcVisible = ["INc-IV-1", "INc-IV-2", "INc-IV-3", "INc-IV-4"].some((c) =>
    html.includes(c),
  );
  const lpVisible = ["tr-IV-1", "tr-IV-2", "tr-IV-3"].some((c) => html.includes(c));
  expect(lcVisible).toBe(true);
  expect(lpVisible).toBe(true);
});
```

- [ ] **Step 3: Verify the render test fails**

Run: `cd web && pnpm vitest run src/components/ParamForm.subquestion-predraw.test.tsx -t "renders each 子題"`
Expected: FAIL — text `form.confirm_subquestion_heading` not found in DOM.

- [ ] **Step 4: Remove the raw JSON `各小題配置` row from the confirmation label list**

In `web/src/components/ParamForm.tsx`, delete the entry that reads (currently at ~line 671):

```ts
{ label: "各小題配置", value: p.subquestion_configs },
```

(Keep the neighboring `{ label: "小題數量", ... }` row.)

- [ ] **Step 5: Add the structured per-子題 section to the confirmation JSX**

Immediately below the existing 學習內容 confirmation block (which ends around `ParamForm.tsx:743`, right before the confirm/cancel buttons at 745-753), insert:

```tsx
{pendingResolvedSubquestionConfigs.length > 0 && (
  <section className="confirm-subquestion-block">
    <h3>{t("form.confirm_subquestion_heading")}</h3>
    <ol>
      {pendingResolvedSubquestionConfigs.map((row, i) => (
        <li key={i}>
          <h4>{t("form.confirm_subquestion_row_title", { n: i + 1 })}</h4>
          {row.question_type && <div>題型: {row.question_type}</div>}
          {row.instruction && <div>出題指示: {row.instruction}</div>}
          <div>
            {row.learning_performance && row.learning_performance.length > 0 ? (
              <>
                <div>
                  {t(
                    row._lpWasAutoDrawn
                      ? "form.confirm_subq_lp_random_pool"
                      : "form.confirm_subq_lp_selected",
                    { n: row.learning_performance.length },
                  )}
                </div>
                <ul>
                  {row.learning_performance.map((code) => (
                    <li key={code}>{code}</li>
                  ))}
                </ul>
              </>
            ) : (
              <div>{t("form.confirm_subq_lp_empty")}</div>
            )}
          </div>
          <div>
            {row.learning_content && row.learning_content.length > 0 ? (
              <>
                <div>
                  {t(
                    row._lcWasAutoDrawn
                      ? "form.confirm_subq_lc_random_pool"
                      : "form.confirm_subq_lc_selected",
                    { n: row.learning_content.length },
                  )}
                </div>
                <ul>
                  {row.learning_content.map((code) => (
                    <li key={code}>{code}</li>
                  ))}
                </ul>
              </>
            ) : (
              <div>{t("form.confirm_subq_lc_empty")}</div>
            )}
          </div>
        </li>
      ))}
    </ol>
  </section>
)}
```

- [ ] **Step 6: Verify the render test passes**

Run: `cd web && pnpm vitest run src/components/ParamForm.subquestion-predraw.test.tsx`
Expected: PASS on both tests in the file.

- [ ] **Step 7: Regression check**

Run: `cd web && pnpm vitest run src/components/ParamForm`
Expected: PASS.

- [ ] **Step 8: Manual smoke — visually inspect the confirmation screen**

Run: `cd web && pnpm dev`

- Open `http://localhost:5173/generate/natural_sciences`
- Choose 年級, 情境, 題型; leave global 學習內容 and 學習表現 blank; set 小題數量=3; leave every per-小題 學習內容 and 學習表現 blank.
- Click the submit / 送出 button. The confirmation screen must show:
  - The existing global 學習表現 / 學習內容 auto-drawn amber sections.
  - A new "各小題配置" section with 3 numbered cards, each listing pre-drawn 學習表現 (1–2 codes) and 學習內容 (1–3 codes) under the "隨機抽取 {n} 項" wording.
- Repeat at `/generate/social_studies` and confirm the same structure appears.

- [ ] **Step 9: Commit**

```bash
git add web/src/components/ParamForm.tsx web/src/components/ParamForm.subquestion-predraw.test.tsx web/src/i18n/messages.ts
git commit -m "feat(web): show per-子題 pre-drawn 學習內容/學習表現 in confirmation"
```

---

### Task 4: Documentation update

**Files:**
- Modify: `CLAUDE.md` (the "Web confirmation dialog pre-draw" section)

- [ ] **Step 1: Extend the pre-draw invariant**

Find the `### Web confirmation dialog pre-draw` block in `CLAUDE.md`. Append the following paragraph immediately after the existing text:

```
For 社會領域 and 自然科學 requests that specify `sub_question_count`, the
frontend also pre-draws per-小題 學習內容 (1–3) and 學習表現 (1–2) from
the currently-active global pool whenever a 子題's per-小題 selection is
empty. The drawn codes appear in the confirmation screen under a
"各小題配置" section (one card per 小題) and are sent to the backend as
`subquestion_configs[*].learning_content` / `learning_performance`.
Explicit per-小題 selections are preserved verbatim and never
overwritten. Empty global pools disable per-小題 auto-draw for that
field, in which case the backend's `or global pool` prompt-build
fallback still applies at generation time.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: extend confirmation pre-draw section for per-子題 LC/LP"
```

---

## Self-Review

- **Spec coverage:** "Show each 子題's randomly-drawn 學習內容/學習表現 in the confirmation screen, just like the global 學習內容/學習表現 pre-draw does" → Tasks 2 (payload) and 3 (render) implement the frontend flow; Task 1 refactors the shared shuffle to keep the two draws honest; Task 4 captures the invariant in `CLAUDE.md`. Backend contract is intentionally untouched (existing `subquestion_configs[*].learning_content/performance` already accept the payload).
- **Placeholder scan:** No `TBD`, `TODO`, "implement later", or bare "add appropriate error handling" instructions. Every step has concrete code or exact commands.
- **Type consistency:** `SubQuestionConfig` field names match `web/src/components/ParamForm.tsx:6-17` (`learning_content`, `learning_performance`, `question_type`, `instruction`, `content_type`, `image_generation_mode`, `question_word_limit`, `option_word_limit`, `text_word_limit`, `reporting_scale`). Internal flags use `_lcWasAutoDrawn` / `_lpWasAutoDrawn` consistently across Tasks 2 and 3 and are stripped before `JSON.stringify` (Task 2 Step 4).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-19-per-subquestion-lc-lp-predraw-display.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
**2. Inline Execution** — batch execution with checkpoints for review.

Which approach?
