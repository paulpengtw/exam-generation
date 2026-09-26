## 1. 前置確認

- [ ] 1.1 在以 `origin/staging` 為基準的乾淨 worktree 承接本 change，並確認 [Does a set framed only by the figure or table count as 事前框定?](https://github.com/paulpengtw/exam-generation/issues/859) 與 [Where is the boundary of the counting-stem ban?](https://github.com/paulpengtw/exam-generation/issues/650) 的狀態。若任一張已修改規則區塊，先更新 `specs/open-response-rubric/spec.md` 的區塊文字再繼續。以 `gh issue view 859`、`gh issue view 650` 與 `git status`（無其他變更）驗證。

## 2. 單一來源規則區塊

- [x] 2.1 新增 `src/common/open_response_rubric.py`，放入三樣東西：spec 規則區塊的常數 `OPEN_RESPONSE_RUBRIC_RULE`、`EXPECTED_EXAMPLE_COUNTS = {"2": 1, "1": 2, "0": 1}`，以及開放式題型判定（接受 enum 或字串）。新增單元測試斷言：七個標記【禁止】【判準】【注意】【提問】【額外項目】【具體性】【學生作答實例】各起頭恰好一個子句（以「行首 strip 後以標記開頭」計），其他子句中的交叉引用不限（見 #871 核准版本）；不含 `{` 與 `}`；實例數常數為 1 / 2 / 1；`開放式建構反應題` 與 `Constructed response` 判定為開放式，其他題型不是。以 `uv run pytest` 跑新測試驗證。（#866 實作；含 EXTRA_ITEMS_FIXED_SENTENCE、COUNTING_STEM_CORRECTION_ROUTING_LINE；byte-identical to tests/fixtures/open_response_rubric/approved_block.txt；2970 passed 2026-09-27；#871 approved block cited）

## 3. Prompt 落點（依 design D2 替換表）

- [x] 3.1 社會領域子題產生器：以常數取代 L1170，L1155 改為 2 / 1 / 0。測試 `build_subquestion_system_prompt`：各學習階段都只含區塊一次，且不含「0..N」與「1-2 個學生作答實例」，prompt 可正常 `.format()`。（#868 實作：OPEN_RESPONSE_RUBRIC_RULE 插入 f-string；L1155 改為 2 / 1 / 0）
- [x] 3.2 自然科學子題產生器：以常數取代 L828，L827 的 `Complex multiple-choice` 行保持原字。測試子題 system prompt 含區塊一次、不再含「2 / 1 / 0 / 0X」，且 `Complex multiple-choice` 行不變。（#866 實作：context_builder.py build_subquestion_system_prompt f-string 插入 {OPEN_RESPONSE_RUBRIC_RULE}）
- [x] 3.3 兩科 corrector：在 `_CORRECTION_SYSTEM_PROMPT_CORE` 的評分規準原則之後加入引導句與區塊。測試兩科 corrector system prompt 都含區塊，四個 prompt 中的區塊擷取文字 byte-identical。（#868 實作：SS corrector 改為串接字串形式，插入 COUNTING_STEM_CORRECTION_ROUTING_LINE + 引導句 + OPEN_RESPONSE_RUBRIC_RULE；test_four_rubric_authoring_prompts_carry_block_byte_identical 通過）
- [x] 3.4 社會領域文本生成器與內含的舊版 system prompt：依 D2 修改 L374、L489、L490、L918、L971、L1054。更新 `tests/test_paper_rescore_retirement.py::test_new_social_studies_prompts_use_native_scoring_language`，改為斷言：
  - 含「計分 0/1」與「每題專屬評分指引」。
  - 不含「0..N」、「2/1/0/0X」與「每一分數級距附 1-2 個學生作答實例」。
  - 文本生成器 system prompt 不含「學生作答實例」。
  - 選擇題子句 byte-identical。（#868 實作：context_builder.py 6 處改寫；test updated）
- [x] 3.5 自然科學舊版模板：依 D2 修改 L216，L215 不動。測試 render 後的 Constructed response 行為「使用 2 / 1 / 0」，且該行不含 `0X` 與「學生作答實例」。（#866 實作：SYSTEM_PROMPT_TEMPLATE 改為「使用 2 / 1 / 0。」）
- [x] 3.6 社會領域驗證：依 D2 修改 L36、刪除 L37，並把 `_ss_rubric_scale_check_hook` 訊息改為「2 / 1 / 0」。驗證 prompt 不含「0..N」與「每一分數級距應有 1-2 個學生作答實例」；`test_new_era_0x_rubric_code_fails_deterministic_verification` 增加斷言 details 含「2 / 1 / 0」、不含「0..N」。（#868 實作：verifier.py 修改）

## 4. 形狀檢核 hook（design D3–D6）

- [x] 4.1 在 `src/common/open_response_rubric.py` 實作 `check_open_response_rubric_shape(subquestions, *, in_scope)`，訊息依 D3 表格。以 table-driven 單元測試驗證：
  - 合規時無 issue；[1] 缺一則。
  - 空白字串實例；多一級（3 / 2 / 1 / 0）、少一級（2 / 0）、重複 code。
  - 級距集合不符時仍報告數量。
  - 多個小題依序號各報一項；`in_scope` 為假時略過。（#866 實作：tests/test_open_response_rubric.py 含固定句缺失檢核；2970 passed 2026-09-27）
- [x] 4.2 新增 `_ss_rubric_shape_check_hook`，in_scope 條件為：`題型` 是開放式建構反應題，且 `認知歷程` 非空。登錄在 `_SS_POST_VERIFY_HOOKS`，排在 `0X` hook 之後。以 `verify_question` 搭配通過型假 client 測試：
  - 不合規的新紀錄 `passed is False`，details 含 `[評分規準形狀檢核]`、「第1題」與級距。
  - LLM 已失敗時保留原 details。
  - 既有 `test_legacy_0x_rubric_code_is_left_untouched_by_new_era_check` 不修改仍通過。（#868 實作：verifier.py 新增 hook，test_paper_rescore_retirement.py 4 個新測試）
- [x] 4.3 新增 `_ns_rubric_shape_check_hook`，in_scope 條件為：`題型` 是 `Constructed response`。登錄在 `_NS_POST_VERIFY_HOOKS`，排在 `_ns_code_check_hook` 之後。
  - 把 `tests/test_natural_sciences_verifier.py` 的開放式 fixture（L186-231）改為 2 / 1 / 0 且 1 / 2 / 1 實例，使 `test_ns_verifier_valid_codes_pass_per_item_family` 仍通過。
  - 新增測試：題組標題題型為 `Complex multiple-choice`、內含 `Constructed response` 小題的混合題組，只檢核該小題；`Complex multiple-choice` 小題帶 `0X` 與空實例不被報告。（#866 實作：4 個新測試；2970 passed 2026-09-27）
- [x] 4.4 人工審題修正整合：以 `tests/server/test_modification_routes.py` 或 `test_modification_correction_structure.py` 的既有 fixture 模式，建立一筆自然科學舊紀錄（2 / 1 / 0 / 0X、無實例）走修改流程。驗證三件事：重新驗證失敗且 details 含形狀檢核；修正結果存成以 `parent_record_id` 連回的新紀錄；原紀錄的 `question_json` 未變。（#869 實作：tests/server/test_869_legacy_ns_rubric.py；2978 passed 2026-09-27）
- [x] 4.5 讀取相容：測試載入 code 為 3 / 2 / 1 / 0 / 0X、實例為空的既有紀錄時不出錯，且級距原樣保留（`RubricEntry` 與 web 型別都不改動）。（#869 實作：tests/server/test_869_legacy_ns_rubric.py；2978 passed 2026-09-27）

## 5. 文件與詞彙

- [x] 5.1 `docs/ADDING_SAMPLES.md`：依 D8 改寫 L158、L205-215 範例與 L250 欄位表。範例須符合區塊：[2] 一則、[1] 兩則（第一則為最小對照）、[0] 一則合理錯誤，不用 `0X`、不用「不知道」。以 `grep -n -E "0\.\.N|0X|1-2 個學生作答實例" docs/ADDING_SAMPLES.md` 驗證開放式題不再出現舊指示（選擇題與 `Complex multiple-choice` 的 `0X` 描述除外）。
- [x] 5.2 `data/social_studies/curriculum/schema_parameters.csv` 第 8 列：只改說明欄，改為 2 / 1 / 0 與 1 / 2 / 1。以 schema loader 既有測試驗證 `題型` enum 值不變。
- [x] 5.3 `CONTEXT.md`：加入 D7 的四個詞條（評分規準、計數式規準、學生作答實例、最小對照），放在「題目結構」段落。以 `git diff CONTEXT.md` 確認只新增詞條、沒有改動其他內容。

## 6. 整合驗證

- [x] 6.1 以 `choom -n 500 -- uv run pytest` 跑完整測試套件並全數通過。再用 `grep -rn -E "0\.\.N|2 / 1 / 0 / 0X|1-2 個學生作答實例" src` 確認只剩 `Complex multiple-choice` 行與舊碼相容處，開放式題的語句都已更新。（#870 實作：49 passed 2026-09-27；src/web/CLAUDE.md/AGENTS.md/README.md/data 全數更新；剩餘 hit 均為 backward-compat 標注，已分類）
- [ ] 6.2 需要 LLM 金鑰：兩科各生成一小批（例如各 5 題組）含開放式小題的題目，記錄首稿形狀檢核失敗率、修正後通過率，以及修正回合數，貼回 map [評分規準 must measure reasoning, not count answers](https://github.com/paulpengtw/exam-generation/issues/646)。若環境沒有金鑰，在 PR 說明中註明未執行及原因，不以估計值代替。
