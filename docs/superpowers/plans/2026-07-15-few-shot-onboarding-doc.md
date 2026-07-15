# Few-Shot Sample Onboarding Doc Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single zh-TW onboarding guide (`docs/ADDING_SAMPLES.md`) that covers how to add a few-shot sample for all three subject pipelines (math, social studies, natural sciences), cross-link it from every relevant loader and from `README.md`, so a data filler no longer has to reverse-engineer three different loaders (GitHub issue #109).

**Architecture:** Docs-only change. One new markdown file under `docs/`; three one-line docstring edits at the top of `src/data_loader.py`, `src/social_studies/data_loader.py`, `src/natural_sciences/data_loader.py`; one contributor-section note appended to `README.md` under the existing `## Data Sources` → **Few-shot Examples** subsection.

**Tech Stack:** Markdown only. Verification uses the actual runtime loaders via `uv run python -c ...` and the existing pytest suite (`uv run pytest -k few_shot`).

**Spec:** `docs/superpowers/specs/2026-07-15-few-shot-onboarding-doc-design.md`

## Global Constraints

- New doc is written in **zh-TW** to match the audience of `data/social_studies/csv_填寫指南.md` (data fillers / researchers).
- Doc lives at the repo-root-relative path `docs/ADDING_SAMPLES.md` (a new `docs/` sibling for user-facing docs; the existing `docs/superpowers/` tree is a separate concern).
- Covers all three subjects: **math** (`data/few_shot/{style}/`), **social studies** (`data/social_studies/few_shot/` — root JSON + optional `few_shot_examples.csv`), **natural sciences** (`data/natural_sciences/few_shot/{q_type_folder}/`).
- Enumerates the **exact 情境 values** per subject, the **6 科學能力 codes** for natural sciences, and the **required fields per 題型** (including the JSON-array `評分規準` requirement for constructed-response items).
- Documents the silent-drop behaviors: `chart_spec` that fails `json.loads` is silently discarded (`src/data_loader.py` L196-200, `src/social_studies/data_loader.py` L164-169, `src/natural_sciences/data_loader.py` L115-120); `範例_`-prefixed files under `data/social_studies/` are never loaded; CSV must be `utf-8-sig` with `;` as multi-value separator.
- Provides one runnable verification one-liner per subject **and** a `pytest -k few_shot` fallback. The one-liners must succeed against the current repo before Task 1 commits.
- Documents the runtime-reload guarantee: all three loaders re-glob on each call (no caching); no server restart or redeploy needed after adding a sample.
- Cross-links land in **all three** loaders' module docstrings and in the README `Few-shot Examples` paragraph — no orphan doc.
- Do not translate Chinese identifiers (情境, 學習內容, 學習表現, 核心素養, 科學能力, 題型, 範例編號, 評分規準) in either the doc or the commit messages.
- No loader code changes; no unification refactor; no sample-validation CLI (spec §Out of scope).

---

### Task 1: Author `docs/ADDING_SAMPLES.md`

**Files:**
- Create: `docs/ADDING_SAMPLES.md`

**Interfaces:**
- Consumes: nothing — pure documentation.
- Produces: the doc file referenced by Tasks 2 and 3.

- [x] **Step 1: Confirm the target directory exists**

Run: `test -d /workspace/exam-generation/docs && echo OK`
Expected: `OK` (the `docs/` directory already exists as parent of `docs/superpowers/`).

- [x] **Step 2: Write the doc file**

Create `docs/ADDING_SAMPLES.md` with the following complete content (zh-TW):

```markdown
# 加入 Few-shot 範例指南

> **適用對象**：負責新增或維護 few-shot 範例的研究人員／教師。
> 三個科目（數學 / 社會 / 自然）各有獨立的 loader 與目錄結構；本指南以「新增一則範例」為目標，提供每科目的最小可執行範例與驗證方式。

## 前言

系統以 few-shot 範例作為 LLM 生題時的示範。每次生成請求都會**即時** re-glob 對應資料夾（無快取）：新增或修改檔案後，下一次 API 呼叫或 CLI 執行即生效，**無須重啟伺服器或重新 build**。

三個科目的入口對照：

| 科目 | Loader | 資料夾 | 檔案格式 |
|------|--------|--------|---------|
| 數學 | `src.data_loader.load_few_shot_examples` | `data/few_shot/{style}/` | 每檔一個 JSON 物件或陣列；style = `text_only` / `with_chart` / `with_image` / `creative_scenario` |
| 社會 | `src.social_studies.data_loader.load_few_shot_example_groups` | `data/social_studies/few_shot/` | 根目錄 JSON（每檔一個 sampling group）＋ 選用 `few_shot_examples.csv`（長格式，一列一子題，以 `範例編號` 分組） |
| 自然 | `src.natural_sciences.data_loader.load_few_shot_example_groups` | `data/natural_sciences/few_shot/{q_type_folder}/` | 每檔一個 JSON 物件或陣列；資料夾對應 PISA 題型：`Simple-multiple-choice` / `Complex-multiple-choice` / `Constructed-response` |

---

## 一、數學（`data/few_shot/`）

### 目錄結構

```
data/few_shot/
├── text_only/                # style = text_only 的範例 JSON
├── with_chart/               # style = with_chart 的範例 JSON
├── with_image/               # style = with_image 的範例 JSON
├── creative_scenario/        # style = creative_scenario 的範例 JSON
├── few_shot_examples.csv     # 選用：跨 style 的 CSV 來源（欄位含 style）
└── images/<範例編號>/manifest.json   # 選用：CSV 範例配圖
```

- 每個 style 子資料夾下放置 `*.json`，每檔可以是**單一物件**或**陣列**（loader 兩種都接受）。
- CSV 為選用；欄位包含 `範例編號, style, description, 情境, 題型種類, 題型, 學習內容, 學習表現, 核心素養, 出題概念, 題目, 正確解題分析, chart_spec`。
- 圖檔透過 `images/<範例編號>/manifest.json` 綁定；`manifest.json` 為 `[{"file": "...", "caption": "..."}]` 陣列。

### 最小可執行範例

新增到 `data/few_shot/text_only/my_first_example.json`：

```json
{
  "style": "text_only",
  "description": "一元一次方程式應用",
  "question": {
    "情境": "個人",
    "題型種類": "單一題",
    "題型": "選擇題",
    "數學思考": ["運用"],
    "學習內容": [
      {"編碼": "A-7-1", "說明": "一元一次方程式的解及其應用。"}
    ],
    "題目": [
      "小明買了 3 支筆和 2 本筆記本共花費 130 元；已知一支筆為 20 元，則一本筆記本為多少元？",
      "(A) 25",
      "(B) 30",
      "(C) 35",
      "(D) 40"
    ],
    "正確解題分析": [
      "正確答案：(C)",
      "設筆記本一本 x 元。3×20 + 2x = 130 → 60 + 2x = 130 → x = 35。"
    ]
  }
}
```

---

## 二、社會（`data/social_studies/few_shot/`）

### 目錄結構

```
data/social_studies/few_shot/
├── *.json                       # 每檔為一個等機率抽樣 group
├── few_shot_examples.csv        # 選用：長格式 CSV，一列一子題，以 範例編號 分組
├── 範例_few_shot_examples.csv   # 研究人員參考範例，系統永遠不會載入
└── images/<範例編號>/manifest.json
```

- 根目錄 JSON 適合**單一精選題組**：一檔一題組，寫成陣列或物件皆可。
- CSV 適合**大量、多小題**題組；每列一小題，依 `範例編號` 分組。欄位逐欄說明見 `data/social_studies/csv_填寫指南.md`。
- **`範例_` 前綴的檔案永遠不會被載入**（`data/social_studies/curriculum/範例_*.csv` 與 `data/social_studies/few_shot/範例_few_shot_examples.csv` 皆然）。此規則實作於研究人員參考用途，勿依賴之。
- Loader 將**每個 JSON 檔**與**每個 CSV `範例編號`**各視為一個 sampling group（等機率抽樣）。

### 最小可執行範例

新增到 `data/social_studies/few_shot/my_first_group.json`：

```json
[
  {
    "style": "text_only",
    "description": "跨區傳染病與公共衛生題組",
    "question": {
      "核心問題": "傳染病在全球化下如何跨區擴散？",
      "文本": "近年跨國旅行頻繁，使部分傳染病能在短時間內跨越國界。城市人口密集與交通樞紐地位提高感染風險…",
      "取材面": ["公共衛生資料整理"],
      "情境": ["公共"],
      "題型種類": "題組題",
      "題型": "選擇題",
      "閱讀歷程": ["擷取訊息"],
      "文本形式": "連續文本",
      "subquestions": [
        {
          "序號": 1,
          "年級": 7,
          "科目": ["地理"],
          "核心素養": ["社-J-A2"],
          "學習內容": [{"編碼": "地Aa-Ⅳ-2", "說明": "全球海陸分布。"}],
          "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "應用社會領域內容知識解析生活經驗或社會現象。"}],
          "出題概念": "評量學生能否從文本擷取跨區擴散因素。",
          "題型": "選擇題",
          "題目": "根據文本，傳染病快速跨區擴散的主要原因最接近下列何者？(A) 跨國旅行與交通樞紐頻繁 (B) 農村完全隔絕 (C) 各國即時公開資訊 (D) 醫療資源平均分配",
          "答案": "A",
          "答案解析": "文本明示跨國旅行與交通樞紐是主因。",
          "評分規準": []
        }
      ]
    }
  }
]
```

**CSV 替代路徑**：若你要新增一組多小題（3–7 小題）題組，改為在 `few_shot_examples.csv` 追加對應列數，同 `範例編號`。逐欄語意見 `data/social_studies/csv_填寫指南.md`。

---

## 三、自然（`data/natural_sciences/few_shot/`）

### 目錄結構

```
data/natural_sciences/few_shot/
├── Simple-multiple-choice/    # 對應 題型 = "Simple multiple-choice"
├── Complex-multiple-choice/   # 對應 題型 = "Complex multiple-choice"
└── Constructed-response/      # 對應 題型 = "Constructed response"
```

- 每個題型資料夾下放 `*.json`（單一物件或陣列），或選用 `few_shot_examples.csv`。
- 題型 → 資料夾名稱由 `src/natural_sciences/data_loader.py` 的 `_TYPE_TO_FOLDER` 決定：空格替換為連字號（如 `"Simple multiple-choice"` → `Simple-multiple-choice/`）。
- 若呼叫端不指定題型，loader 會**遞迴掃描所有子資料夾**與根目錄 CSV（`_load_examples_from_dir`）。

### 最小可執行範例

新增到 `data/natural_sciences/few_shot/Constructed-response/my_first_example.json`：

```json
{
  "style": "text_only",
  "description": "水的比熱與能量守恆",
  "question": {
    "核心問題": "如何用比熱與能量守恆解釋日常加熱現象？",
    "文本": "小華以 100 g 常溫水（25°C）進行加熱實驗，記錄 5 分鐘後溫度上升至 55°C。已知水的比熱為 1 卡/(g·°C)。",
    "取材面": ["國中自然課程素材"],
    "情境": ["Personal"],
    "情境子類別": "健康",
    "題型種類": "題組題",
    "題型": "Constructed response",
    "科學能力": ["能力二：建構和評估科學探究之設計，並批判性地詮釋科學資料和證據"],
    "題目內容類型": "純文字",
    "subquestions": [
      {
        "序號": 1,
        "年級": 8,
        "科目": ["自然科學"],
        "科學能力": ["能力二：建構和評估科學探究之設計，並批判性地詮釋科學資料和證據"],
        "核心素養": [],
        "學習內容": [{"編碼": "INc-IV-1", "說明": "熱與比熱。"}],
        "學習表現": [{"編碼": "tr-IV-1", "說明": "能運用觀察、實驗結果進行推理。"}],
        "出題概念": "計算加熱效率並解釋單位。",
        "題型": "Constructed response",
        "題目": "請計算此杯水在 5 分鐘內吸收的總熱量，並說明計算過程。",
        "答案": "3000 卡（100 × 30 × 1 = 3000）。",
        "答案解析": "熱量 Q = 質量 × 溫差 × 比熱 = 100 g × 30 °C × 1 卡/(g·°C) = 3000 卡。",
        "評分規準": [
          {"code": "2", "規準說明": "正確列出公式與代入並得 3000 卡。", "學生作答實例": ["Q=100×30×1=3000 卡"]},
          {"code": "1", "規準說明": "公式正確但數值計算錯誤。", "學生作答實例": ["Q=100×25×1=2500 卡"]},
          {"code": "0", "規準說明": "公式錯誤或無法計算。", "學生作答實例": ["不知道"]},
          {"code": "0X", "規準說明": "未作答。", "學生作答實例": [""]}
        ]
      }
    ]
  }
}
```

---

## 四、驗證規則（三科目共通）

### 情境 enum

| 科目 | 允許值 |
|------|--------|
| 數學 | `個人 / 社會時事 / 科學 / 職業 / 建築與藝術 / 數學文字情境`（見 `question_schemas.json`） |
| 社會 | `個人 / 公共 / 職業 / 教育`（見 `data/social_studies/curriculum/schema_parameters.csv`） |
| 自然 | `Personal / Local and national / Global`（見 `data/natural_sciences/curriculum/schema_parameters.csv`） |

### 自然科學能力（6 個代碼，寫成完整字串）

```
能力一：以科學的角度解釋現象
能力二：建構和評估科學探究之設計，並批判性地詮釋科學資料和證據
能力三：研究、評估和運用科學資訊進行決策與行動
環境能力一：解釋人類與地球系統的相互作用對環境的影響
環境能力二：評估證據並做出有根據的決策以重建和維護環境
環境能力三：抱持希望並尊重多元觀點以回應社會生態危機
```

### 題型必要欄位

| 題型 | 必要欄位 |
|------|----------|
| 選擇題 / `Simple multiple-choice` / `Complex multiple-choice` | `題目`（含 A–D 選項字串）、`答案`（單一或多個字母）；`評分規準` 可為空陣列。 |
| 封閉式建構反應題 | `答案`（短字串）、`答案解析`；`評分規準` 可為空陣列。 |
| 開放式建構反應題 / `Constructed response` | **`評分規準` 必須是 JSON 陣列**，包含 `2 / 1 / 0 / 0X` 四個評分等級，每筆 `{code, 規準說明, 學生作答實例}`。 |

### 隱性/寧靜失敗（silent drop）

- **`chart_spec` 必須是合法 JSON**：三個 loader 皆以 `try: json.loads(...) except json.JSONDecodeError: pass` 處理，**解析失敗會靜默丟棄整個 `chart_spec`**（題目其他欄位維持）。修改後請先用 `python -m json.tool` 或線上 JSON 驗證器檢查。
- **CSV 編碼**：`utf-8-sig`（Excel 存檔請選「CSV UTF-8」）。多值欄位分隔符為分號 `;`（不是逗號，不是斜線）。
- **`範例_` 前綴檔**：`data/social_studies/**/範例_*.csv` 永遠不會被載入。

---

## 五、如何驗證你的範例被 loader 讀到

執行以下對應指令；成功時輸出一個整數（載入的 group 數），加入新範例後數字應該比之前多。若指令拋錯（`json.JSONDecodeError` / `KeyError` / `csv.Error` …），代表你的檔案格式有問題。

### 數學

```bash
uv run python -c "from pathlib import Path; from src.data_loader import load_few_shot_examples; print(len(load_few_shot_examples(Path('data/few_shot'), 'text_only')))"
```

### 社會

```bash
uv run python -c "from pathlib import Path; from src.social_studies.data_loader import load_few_shot_example_groups; print(len(load_few_shot_example_groups(Path('data/social_studies/few_shot'))))"
```

### 自然

```bash
uv run python -c "from pathlib import Path; from src.natural_sciences.data_loader import load_few_shot_example_groups; print(len(load_few_shot_example_groups(Path('data/natural_sciences/few_shot'), 'Constructed-response')))"
```

### 三科目共用：跑相關單元測試

```bash
uv run pytest -k few_shot
```

---

## 六、Runtime reload 保證

三個 loader 都是**執行時 re-glob**：

- `src.data_loader.load_few_shot_examples`：`sorted(style_dir.glob("*.json"))`（每次呼叫重新掃描）
- `src.social_studies.data_loader.load_few_shot_example_groups`：`sorted(few_shot_dir.glob("*.json"))` + CSV 重讀
- `src.natural_sciences.data_loader.load_few_shot_example_groups`：`_load_examples_from_dir` 逐 folder `sorted(path.glob("*.json"))` + CSV 重讀

沒有 in-memory 快取，也沒有 build step。**加入或修改範例後，下一次 CLI 執行或 API request 即生效**，不需要 `docker-compose restart`、不需要 `uv sync`、不需要重新 build 前端。

---

## 相關文件

- `data/social_studies/csv_填寫指南.md` — 社會 CSV 每欄逐欄填寫指南（zh-TW）
- `README.md` §Data Sources → Few-shot Examples — 三科目 few-shot 概覽
- `docs/superpowers/specs/2026-07-15-few-shot-onboarding-doc-design.md` — 本文件的設計規格
```

- [x] **Step 3: Verify all three one-liners actually run against the current repo**

Run each command from `/workspace/exam-generation` (the repo root) — every one must exit 0 and print a non-negative integer:

```bash
cd /workspace/exam-generation
uv run python -c "from pathlib import Path; from src.data_loader import load_few_shot_examples; print(len(load_few_shot_examples(Path('data/few_shot'), 'text_only')))"
uv run python -c "from pathlib import Path; from src.social_studies.data_loader import load_few_shot_example_groups; print(len(load_few_shot_example_groups(Path('data/social_studies/few_shot'))))"
uv run python -c "from pathlib import Path; from src.natural_sciences.data_loader import load_few_shot_example_groups; print(len(load_few_shot_example_groups(Path('data/natural_sciences/few_shot'), 'Constructed-response')))"
```

Expected: each prints an integer `>= 1` (repo currently ships ≥1 example per subject: math `text_only/` has 2+ files, social studies has 4 root JSONs + CSV, natural sciences `Constructed-response/` has ≥1 file). No `Traceback` / `Error`.

- [x] **Step 4: Confirm the referenced pytest suite is green today**

Run: `cd /workspace/exam-generation && uv run pytest -k few_shot -q`
Expected: PASS — the existing few-shot tests (`tests/test_social_studies_few_shot.py`, `tests/test_natural_sciences_few_shot.py`) all green.

- [x] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add docs/ADDING_SAMPLES.md
git commit -m "docs: add zh-TW few-shot onboarding guide covering all 3 subjects (#109)"
```

---

### Task 2: Add docstring cross-links in all three loaders

**Files:**
- Modify: `src/data_loader.py:1` (module docstring)
- Modify: `src/social_studies/data_loader.py:1` (module docstring)
- Modify: `src/natural_sciences/data_loader.py:1` (module docstring)

**Interfaces:**
- Consumes: `docs/ADDING_SAMPLES.md` (Task 1).
- Produces: nothing — pointer-only edits.

- [x] **Step 1: Update `src/data_loader.py` module docstring**

Replace the single-line docstring on `src/data_loader.py:1`:

```python
"""Load and index curriculum data from JSON files."""
```

with:

```python
"""Load and index curriculum data from JSON files.

Few-shot examples for math live under ``data/few_shot/{style}/`` and are
loaded by :func:`load_few_shot_examples`. To add a new sample, see the
onboarding guide at ``docs/ADDING_SAMPLES.md`` (zh-TW), which documents
the directory layout, required fields per 題型, validation rules
(e.g. malformed ``chart_spec`` is silently dropped), and the one-liner
verification command for all three subject pipelines.
"""
```

- [x] **Step 2: Update `src/social_studies/data_loader.py` module docstring**

Replace the single-line docstring on `src/social_studies/data_loader.py:1`:

```python
"""Data loading for social studies — few-shot examples and CSV-driven curriculum."""
```

with:

```python
"""Data loading for social studies — few-shot examples and CSV-driven curriculum.

Few-shot examples live under ``data/social_studies/few_shot/``: each root
JSON file is one sampling group, and ``few_shot_examples.csv`` groups rows
by ``範例編號``. ``範例_``-prefixed files are never loaded. To add a new
sample, see ``docs/ADDING_SAMPLES.md`` (zh-TW) — it covers the JSON vs CSV
tradeoff, required fields per 題型, silent-drop behaviors (malformed
``chart_spec``, CSV encoding), and the one-liner verification command.
"""
```

- [x] **Step 3: Update `src/natural_sciences/data_loader.py` module docstring**

Replace the single-line docstring on `src/natural_sciences/data_loader.py:1`:

```python
"""Data loading for natural-sciences few-shot examples."""
```

with:

```python
"""Data loading for natural-sciences few-shot examples.

Examples live in one folder per PISA-Science 題型 under
``data/natural_sciences/few_shot/``: ``Simple-multiple-choice/``,
``Complex-multiple-choice/``, ``Constructed-response/``. The folder name
is derived from the 題型 string via :data:`_TYPE_TO_FOLDER` (spaces →
hyphens). When 題型 is ``None``, all subdirectories are scanned. To add
a new sample, see ``docs/ADDING_SAMPLES.md`` (zh-TW) — it documents the
mapping, the ``評分規準`` JSON-array requirement for ``Constructed
response`` items, and the one-liner verification command.
"""
```

- [x] **Step 4: Verify Python still imports cleanly**

Run:

```bash
cd /workspace/exam-generation
uv run python -c "import src.data_loader, src.social_studies.data_loader, src.natural_sciences.data_loader; print('imports OK')"
```

Expected: prints `imports OK`. No `SyntaxError` from the multi-line docstrings.

- [x] **Step 5: Verify ruff is still happy**

Run: `cd /workspace/exam-generation && uv run ruff check src/data_loader.py src/social_studies/data_loader.py src/natural_sciences/data_loader.py`
Expected: no new errors introduced by the docstring changes.

- [x] **Step 6: Verify the existing few-shot tests still pass (docstring changes cannot break them)**

Run: `cd /workspace/exam-generation && uv run pytest -k few_shot -q`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
cd /workspace/exam-generation
git add src/data_loader.py src/social_studies/data_loader.py src/natural_sciences/data_loader.py
git commit -m "docs(loaders): point module docstrings at ADDING_SAMPLES.md (#109)"
```

---

### Task 3: Add README contributor-section link

**Files:**
- Modify: `README.md` (Data Sources → Few-shot Examples subsection around lines 628-636)

**Interfaces:**
- Consumes: `docs/ADDING_SAMPLES.md` (Task 1).
- Produces: a discoverable pointer from the project README.

- [x] **Step 1: Insert the pointer paragraph after the Few-shot Examples subsection**

In `README.md`, the current `### Few-shot Examples` subsection ends at the paragraph starting with `**Social studies** (data/social_studies/few_shot/): …` (around line 636). Append a new paragraph directly after that block, before the next `### Past Exams` heading:

```markdown
> **想新增一則 few-shot 範例？** 三個科目的目錄結構、每個題型的必要欄位、隱性失敗
> （例如 `chart_spec` JSON 格式錯誤會被靜默丟棄）以及「一行指令確認 loader 有讀到你的範例」
> 都彙整在 **[`docs/ADDING_SAMPLES.md`](docs/ADDING_SAMPLES.md)** (zh-TW)。加入或修改
> 範例後**下一次執行即生效**，無須重啟服務或重新 build。
```

- [x] **Step 2: Verify the Markdown link resolves**

Run:

```bash
cd /workspace/exam-generation
test -f docs/ADDING_SAMPLES.md && echo "link OK" || echo "MISSING"
```

Expected: `link OK`.

- [x] **Step 3: Verify the README still parses (no unterminated code fence or bad reference)**

Run:

```bash
cd /workspace/exam-generation
uv run python -c "import pathlib, re; s = pathlib.Path('README.md').read_text(encoding='utf-8'); fences = re.findall(r'^```', s, flags=re.M); assert len(fences) % 2 == 0, f'unmatched code fences: {len(fences)}'; print('README fences balanced:', len(fences))"
```

Expected: prints `README fences balanced: <even integer>`. No `AssertionError`.

- [x] **Step 4: Commit**

```bash
cd /workspace/exam-generation
git add README.md
git commit -m "docs(readme): link to ADDING_SAMPLES.md from Few-shot Examples section (#109)"
```

---

### Task 4: Final acceptance — run through the doc's own instructions

**Files:** none (verification only).

**Interfaces:**
- Consumes: everything from Tasks 1–3.

- [x] **Step 1: Re-run the three one-liners exactly as they appear in the doc**

The three one-liners in `docs/ADDING_SAMPLES.md` §五 must still succeed after the docstring edits:

```bash
cd /workspace/exam-generation
uv run python -c "from pathlib import Path; from src.data_loader import load_few_shot_examples; print(len(load_few_shot_examples(Path('data/few_shot'), 'text_only')))"
uv run python -c "from pathlib import Path; from src.social_studies.data_loader import load_few_shot_example_groups; print(len(load_few_shot_example_groups(Path('data/social_studies/few_shot'))))"
uv run python -c "from pathlib import Path; from src.natural_sciences.data_loader import load_few_shot_example_groups; print(len(load_few_shot_example_groups(Path('data/natural_sciences/few_shot'), 'Constructed-response')))"
```

Expected: three non-negative integers, no tracebacks.

- [x] **Step 2: Run the whole few-shot pytest slice**

Run: `cd /workspace/exam-generation && uv run pytest -k few_shot -q`
Expected: PASS.

- [x] **Step 3: Confirm doc is discoverable from each documented entry point**

Run:

```bash
cd /workspace/exam-generation
grep -l "ADDING_SAMPLES.md" README.md src/data_loader.py src/social_studies/data_loader.py src/natural_sciences/data_loader.py
```

Expected: all four paths listed.

- [x] **Step 4: No additional commit — this is a verification-only task**

If Steps 1–3 all pass, the plan is complete. No changes were made in Task 4; nothing to commit.
