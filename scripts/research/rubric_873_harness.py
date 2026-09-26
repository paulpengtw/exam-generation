"""
Research #873 — every_item_required field: labelled set and generation-run input.

This script:
1. Defines the every_item_required labelled set (corpus + synthetic + near-miss).
2. Runs the every_item_required evaluation on the labelled set (reads cache first;
   LLM calls only for entries not yet cached).  Reports the confusion matrix.
3. Collects ~30 open-response 小題 from the NS few-shot corpus as generation-run
   input (including three counting_stem cases flagged for #650 conversion).
4. For each generation-run item, prompts the model to write a rubric using
   OPEN_RESPONSE_RUBRIC_RULE.  Caches every response.
5. Computes two counts from the generation-run output:
   a. every_item_required hand-label slot: True/False per [2] rubric entry.
   b. EXTRA_ITEMS_FIXED_SENTENCE substring check: does [2] contain the fixed
      sentence?  (Programmatic; no LLM required.)

Cache key scheme:
  - every_item_required labelled set: "eir|{key}"
  - generation-run rubric responses: "genrun|{file_stem}|{item_idx}|{seq}"
  Previously cached responses from #872 (counting_stem standalone, "counting_stem|{key}")
  and from #651 ("v2|{file_stem}|{item_idx}|{seq}") are NOT re-read here; those caches
  are in separate JSONL files.

IMPORTANT: No LLM calls are made until API credits are restored.
The harness prints the EXTRA_ITEMS_FIXED_SENTENCE count (programmatic) immediately.
LLM-dependent steps are prepared but gated behind a credit check.

Run from the repo root:
    uv run python scripts/research/rubric_873_harness.py

If credits are unavailable, the script reports the programmatic counts and exits.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.common.open_response_rubric import (  # noqa: E402
    EXTRA_ITEMS_FIXED_SENTENCE,
    OPEN_RESPONSE_RUBRIC_RULE,
)
from src.config import Config   # noqa: E402
from src.llm_client import LLMClient  # noqa: E402

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
CR_DIR = ROOT / "data" / "natural_sciences" / "few_shot" / "Constructed-response"
OUT_873 = ROOT / "docs" / "research" / "873-every-item-required"
OUT_873.mkdir(parents=True, exist_ok=True)

RESPONSES_873 = OUT_873 / "responses.jsonl"

# ---------------------------------------------------------------------------
# every_item_required definition
# ---------------------------------------------------------------------------
#
# every_item_required = True iff:
#   The [2] level requires that EVERY item the student independently writes must
#   satisfy a condition, using 皆/均/都/全部 over the student-generated scope.
#   Pattern: 「所提結論皆…」, 「所列理由均…」, 「每一項都…」
#   The student's extra items can cause a downgrade to [1].
#
# every_item_required = False when:
#   - [2] uses 皆/均/都/全部 only over a set of members that the 小題 names in
#     advance (「兩個條件均提及」, 「海冰組和陸冰組預測及理由均正確」, 「五點全部…」).
#     The student writing extra items does not trigger a downgrade.
#   - [2] does not use 皆/均/都/全部 at all.
#
# The distinction: "student-driven scope" (True) vs "question-driven framing" (False).

# ---------------------------------------------------------------------------
# Labelled set for every_item_required
# ---------------------------------------------------------------------------

@dataclass
class EIRItem:
    """One labelled entry for the every_item_required evaluation."""
    key: str                        # unique key (used for cache lookup)
    file_stem: str                  # JSON filename stem
    seq: int                        # 小題 序號
    item_idx: int                   # item index within the file (0-based)
    label: bool                     # gold label: True = every_item_required
    label_rule: str                 # which rule determines label (for audit)
    stem_snippet: str               # first 80 chars of 題目
    rubric_level_2: str             # [2] 規準說明 verbatim
    source: str                     # "corpus" | "synth_positive" | "near_miss"


EIR_LABELLED_SET: list[EIRItem] = [
    # ── Corpus: label = True (1 case) ─────────────────────────────────────
    # fasting-method seq=3: 「且均基於組間比較」 — student writes conclusions;
    # every conclusion must be 基於組間比較. Any extra wrong-scope conclusion → [1].
    EIRItem(
        key="corpus|fasting-method|3",
        file_stem="fasting-method",
        seq=3,
        item_idx=0,
        label=True,
        label_rule="T1: 均 over student-generated conclusions",
        stem_snippet="請問以上實驗可以得出什麼結論？（請寫兩個結論）",
        rubric_level_2="正確寫出兩個合理且有所不同的結論，且均基於組間比較",
        source="corpus",
    ),

    # ── Corpus: label = False (named/framed-set 皆/均) ─────────────────────
    # entomopathogenic-fungi seq=3: 「兩個條件均提及」 — both conditions named.
    EIRItem(
        key="corpus|entomopathogenic-fungi|3",
        file_stem="entomopathogenic-fungi",
        seq=3,
        item_idx=0,
        label=False,
        label_rule="F1: 均 over two named members (保護行, 多區塊設計)",
        stem_snippet="曉萍決定以藥劑A來進行田間施藥試驗。",
        rubric_level_2=(
            "同時提及保護行避免藥液污染，以及多區塊設計避免位置效應"
            "（兩個條件均提及）"
        ),
        source="corpus",
    ),

    # fishing-harbor-renovation seq=2: 「兩組數據均正確標示」 — 兩組 are named by experiment.
    EIRItem(
        key="corpus|fishing-harbor-renovation|2",
        file_stem="fishing-harbor-renovation",
        seq=2,
        item_idx=0,
        label=False,
        label_rule="F1: 均 over two named experimental groups (黑色/白色房屋)",
        stem_snippet="請繪製折線圖呈現黑色與白色房屋的溫度變化。",
        rubric_level_2=(
            "正確繪製折線圖，橫軸時間、縱軸溫度，"
            "兩組數據均正確標示並有完整圖例"
        ),
        source="corpus",
    ),

    # hot-pack seq=4: 「兩組數據均正確繪出」 — 兩組 are named by experiment.
    EIRItem(
        key="corpus|hot-pack|4",
        file_stem="hot-pack",
        seq=4,
        item_idx=0,
        label=False,
        label_rule="F1: 均 over two named experimental groups (實驗1/實驗2)",
        stem_snippet="試將實驗數據以圖表呈現（折線圖），並附完整圖例。",
        rubric_level_2=(
            "正確選用折線圖，橫軸為時間、縱軸為溫度，"
            "兩組數據均正確繪出並有標示"
        ),
        source="corpus",
    ),

    # sea-ice-land-ice seq=2: 「海冰組和陸冰組…均正確」 — two named experimental groups.
    EIRItem(
        key="corpus|sea-ice-land-ice|2",
        file_stem="sea-ice-land-ice",
        seq=2,
        item_idx=0,
        label=False,
        label_rule="F1: 均 over two named groups (海冰組, 陸冰組)",
        stem_snippet="請你預測冰塊融化後海冰組及陸冰組水面高度變化為何？並說明理由。",
        rubric_level_2=(
            "海冰組和陸冰組預測及理由均正確，"
            "且引用阿基米德原理或質量守恆解釋"
        ),
        source="corpus",
    ),

    # sea-ice-land-ice seq=3: 「兩項均選擇合理器材」 — 兩項 = 陸地/海洋 named by question.
    EIRItem(
        key="corpus|sea-ice-land-ice|3",
        file_stem="sea-ice-land-ice",
        seq=3,
        item_idx=0,
        label=False,
        label_rule="F1: 均 over two named roles (陸地, 海洋) in framed choice task",
        stem_snippet="請從下方器材或材料中選擇器材來模擬陸地與海洋的情形。",
        rubric_level_2=(
            "兩項均選擇合理器材，且理由充分說明為何比木板更適合"
        ),
        source="corpus",
    ),

    # seawater-vertical-properties seq=2: 「五點全部正確依深度排列」 — five data points given.
    EIRItem(
        key="corpus|seawater-vertical-properties|2",
        file_stem="seawater-vertical-properties",
        seq=2,
        item_idx=0,
        label=False,
        label_rule="F1: 全部 over five given data points in the table",
        stem_snippet="請將五點不同水深的海水參數依海水深度由淺至深重新排列。",
        rubric_level_2="五點全部正確依深度排列",
        source="corpus",
    ),

    # weather-proverbs seq=2: 「兩種系統均正確標示」 — 兩種系統 are named (北方鋒面/東方高壓).
    EIRItem(
        key="corpus|weather-proverbs|2",
        file_stem="weather-proverbs",
        seq=2,
        item_idx=0,
        label=False,
        label_rule="F1: 均 over two named meteorological systems (北方鋒面, 東方高壓)",
        stem_snippet="請在圖中正確標示影響五月與六月氣候的天氣系統。",
        rubric_level_2=(
            "兩種系統均正確標示位置（北方鋒面/東方高壓）、"
            "風向（南風箭頭）與天氣型態（多雨/晴朗）"
        ),
        source="corpus",
    ),

    # ── Synthetic positives: label = True ─────────────────────────────────
    # synth_1: 「所提論點皆應包含…」 — open recommendation; any item must satisfy.
    EIRItem(
        key="synth|every_item|1",
        file_stem="(synthetic)",
        seq=1,
        item_idx=0,
        label=True,
        label_rule="T1: 皆 over student-generated recommendations (open set)",
        stem_snippet="請提出至少兩個改善方案。",
        rubric_level_2=(
            "提出兩個以上改善方案，且所提方案皆應可行並與實驗數據相關。"
            "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
        ),
        source="synth_positive",
    ),

    # synth_2: 「所列原因均須基於…」 — open causal question; any reason must be evidence-based.
    EIRItem(
        key="synth|every_item|2",
        file_stem="(synthetic)",
        seq=2,
        item_idx=0,
        label=True,
        label_rule="T1: 均 over student-generated explanations (open set)",
        stem_snippet="請說明可能造成此現象的原因。",
        rubric_level_2=(
            "正確說明兩個以上可能原因，且均須基於文本所提供的數據或機制。"
            "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
        ),
        source="synth_positive",
    ),

    # ── Near-misses: label = False ─────────────────────────────────────────
    # near_miss_1: 皆 over named members of a framed set (明顯的 False)
    EIRItem(
        key="near_miss|named_pair|1",
        file_stem="(synthetic)",
        seq=1,
        item_idx=0,
        label=False,
        label_rule="F1: 均 over two named members (甲方法, 乙方法)",
        stem_snippet="請分別說明甲方法與乙方法的優缺點。",
        rubric_level_2=(
            "甲方法與乙方法的優缺點均正確說明，"
            "且各包含具體科學依據。"
        ),
        source="near_miss",
    ),

    # near_miss_2: 皆 over parts of one answer chain (推理鏈各步驟均成立)
    EIRItem(
        key="near_miss|answer_chain|1",
        file_stem="(synthetic)",
        seq=1,
        item_idx=0,
        label=False,
        label_rule="F2: 均 over steps of ONE required answer chain, not extra student items",
        stem_snippet="請解釋此現象的物理機制（含受力分析與加速度推導）。",
        rubric_level_2=(
            "受力分析與加速度推導均正確，"
            "且邏輯推論完整不遺漏關鍵步驟。"
        ),
        source="near_miss",
    ),
]

# ---------------------------------------------------------------------------
# Verifier prompt templates (from #872 harness — reused here)
# ---------------------------------------------------------------------------
# NOTE: VERIFIER_SYSTEM_V2 and VERIFIER_USER_TEMPLATE_V2 are intentionally
# duplicated (not imported) so #873 can evolve its prompt independently.

VERIFIER_SYSTEM_V2 = """\
你是108課綱自然科學／社會領域素養導向命題的評分規準稽核員。
你的任務是判斷一道小題的評分規準是否違反規則 C，
同時判斷題目（小題）是否構成「計數式提問」（counting_stem），
以及 [2] 級距是否要求學生「所提的每一個項目皆…」（every_item_required）。

## 規則 C（完整條文，含 #859 修訂）

{rule_c}

## counting_stem 的定義

counting_stem 為 True，當且僅當：
  小題要求學生從「不能事前框定的開放集合」中產出 ≥2 個答案項目——
  使用「請寫兩個」「至少列舉N項」「有哪些」「任N項」（N < 總集合成員數）等語句。

counting_stem 為 False（以下任一排除條件成立即可）：
  F1 — 計數修飾的是題目所給的材料或情境，而非答案項目。
  F2 — 集合成員已在題幹中逐一點名（「一個優點與一個缺點」、「甲、乙兩個面向」）。
  F3 — 完整答案集合直接由題目所指的圖表決定（任何人看同一張圖即可列出相同清單）。
  F4 — 集合是某科學概念的必要組成（如光合作用的完整方程式）。
  F5 — 「哪些」問的是材料已列出的封閉集合（學生從中選出，而非自行產出）。
  F6 — 只要求寫出「一項」。

## every_item_required 的定義

every_item_required 為 True，當且僅當：
  [2] 級距要求學生「所提的每一個項目」都成立
  ——使用「所提結論皆…」「所列理由都…」「每一項均…」等語句，
  即任何一個學生自行多寫的「錯誤額外項目」會讓學生降為 [1]。

every_item_required 為 False，當：
  - [2] 只要求本小題「事前指名的成員」均成立（如「兩個條件均提及」、
    「甲、乙兩個面向均正確」），學生自行多寫的額外項目不影響結果；或
  - [2] 不使用皆/均/都/全部等語句。

請仔細區分「學生自行新增的每一項」（True）與「題目預先指名的各成員」（False）。
""".format(rule_c=OPEN_RESPONSE_RUBRIC_RULE)

VERIFIER_USER_TEMPLATE_V2 = """\
請判斷以下小題的評分規準是否違反規則 C，並判斷是否構成計數式提問（counting_stem），
以及 [2] 級距是否要求學生所寫的每一項均須成立（every_item_required）。

## 小題題目
{stem}

## 評分規準
[2] {rubric_2}

## 輸出格式
請直接輸出 JSON（無 markdown 包裹）：
{{
  "rule_c_verdict": "<VIOLATES|LEGAL|CONFORMING|OUT_OF_SCOPE_C3>",
  "rule_c_framing_basis": "<題幹|圖表|其他|N/A>",
  "rule_c_contestable": <true|false>,
  "rule_c_reason": "<一句話說明>",
  "counting_stem": <true|false>,
  "counting_stem_reason": "<一句話說明（F1-F6 或為何是 True）>",
  "every_item_required": <true|false>,
  "every_item_required_reason": "<一句話說明>",
  "details": "<若 VIOLATES/counting_stem/every_item_required 為 true，填入說明句；否則空字串>"
}}
"""

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _load_cache(path: Path) -> dict[str, Any]:
    cache: dict[str, Any] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                cache[entry["key"]] = entry
            except Exception:
                pass
    return cache


def _save_cache_entry(path: Path, entry: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# EXTRA_ITEMS_FIXED_SENTENCE count (programmatic — no LLM)
# ---------------------------------------------------------------------------

def count_extra_items_sentence(cr_dir: Path) -> dict[str, int]:
    """Scan all Constructed-response rubrics; count [2] entries with/without the
    EXTRA_ITEMS_FIXED_SENTENCE.  Returns {'total': N, 'has_sentence': N}.
    """
    total = 0
    has_sentence = 0
    for json_file in sorted(cr_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            q = item.get("question", item)
            for sq in q.get("subquestions", []):
                for r in sq.get("評分規準", []):
                    code = str(r.get("code", r.get("編碼", "")))
                    if code == "2":
                        total += 1
                        desc = r.get("規準說明", r.get("說明", ""))
                        if EXTRA_ITEMS_FIXED_SENTENCE in desc:
                            has_sentence += 1
    return {"total": total, "has_sentence": has_sentence}


# ---------------------------------------------------------------------------
# Generation-run input: ~30 open-response 小題 from NS corpus
# ---------------------------------------------------------------------------
# Criteria for selection:
#   1. Constructed-response file with a proper 評分規準 (code 2/1/0).
#   2. Diverse across files (no more than 2 small questions per file).
#   3. Three flagged items need #650 conversion before rubric-writing:
#      - fasting-method seq=3 (counting_stem=True; rewrite to name the two groups)
#      - washing-machine-physics seq=5 (counting_stem=True; rewrite to 逐一點名觀察點)
#      - 胡椒蛾的分子機制 seq=3 (counting_stem=True; rewrite 至少三項 → 逐一點名)
#   4. Remaining 27 items should NOT have counting_stem issues.
#
# The list below is the selected corpus (key = "file_stem|item_idx|seq").
# Items marked counting_stem_needs_conversion=True must NOT be sent to the
# rubric-writing LLM until the stem is rewritten per #650.

@dataclass
class GenRunItem:
    key: str
    file_stem: str
    item_idx: int
    seq: int
    stem_snippet: str
    counting_stem_needs_conversion: bool = False
    conversion_note: str = ""


GENERATION_RUN_ITEMS: list[GenRunItem] = [
    # ── Counting-stem items (need #650 conversion before rubric-writing) ──
    GenRunItem(
        key="fasting-method|0|3",
        file_stem="fasting-method",
        item_idx=0,
        seq=3,
        stem_snippet="請問以上實驗可以得出什麼結論？（請寫兩個結論）",
        counting_stem_needs_conversion=True,
        conversion_note=(
            "「請寫兩個結論」is counting_stem. Convert: change stem to "
            "「請寫出一個關於飲食的結論」or name the two conclusions explicitly. "
            "Note: this item also has every_item_required=True, so after conversion "
            "the 皆 condition may still apply if the stem says 「所提結論皆應…」."
        ),
    ),
    GenRunItem(
        key="washing-machine-physics|0|5",
        file_stem="washing-machine-physics",
        item_idx=0,
        seq=5,
        stem_snippet="請問型號B比起型號A有何不同之處，請寫下至少兩點你觀察到的變因關係。",
        counting_stem_needs_conversion=True,
        conversion_note=(
            "「至少兩點」from open set is counting_stem. Convert: name the specific "
            "observations (e.g., 「請觀察轉速與重量的關係，以及洗滌時間的變化」), "
            "or reduce to one item (「請寫出你觀察到的一個最主要的變因關係」)."
        ),
    ),
    GenRunItem(
        key="胡椒蛾的分子機制|0|3",
        file_stem="胡椒蛾的分子機制",
        item_idx=0,
        seq=3,
        stem_snippet="造成黑色等位基因比例增加的可能原因有哪些？（請至少列舉三項）",
        counting_stem_needs_conversion=True,
        conversion_note=(
            "「至少三項」 of Hardy-Weinberg violations is counting_stem (any-N-of-5). "
            "Convert: name the five conditions explicitly and ask which are violated, "
            "or reduce to asking for the single most important cause."
        ),
    ),

    # ── Normal items (no counting_stem issue) ──────────────────────────────
    GenRunItem(
        key="entomopathogenic-fungi|0|2",
        file_stem="entomopathogenic-fungi",
        item_idx=0,
        seq=2,
        stem_snippet="請從資料說明農業防治害蟲時，使用真菌農藥的好處？",
    ),
    GenRunItem(
        key="entomopathogenic-fungi|0|3",
        file_stem="entomopathogenic-fungi",
        item_idx=0,
        seq=3,
        stem_snippet="曉萍決定以藥劑A來進行田間施藥試驗，應如何設計實驗才能控制變因？",
    ),
    GenRunItem(
        key="fasting-method|0|2",
        file_stem="fasting-method",
        item_idx=0,
        seq=2,
        stem_snippet="小丁認為體重增重與用餐的次數有關；小基認為體重增重與飲食的時段有關。",
    ),
    GenRunItem(
        key="fasting-method|0|4",
        file_stem="fasting-method",
        item_idx=0,
        seq=4,
        stem_snippet="下列哪一個計畫是適合雷神索爾？請依據圖一、圖二及圖三的資料說明理由。",
    ),
    GenRunItem(
        key="fishing-harbor-renovation|0|1",
        file_stem="fishing-harbor-renovation",
        item_idx=0,
        seq=1,
        stem_snippet="請依據表一，說明黑色房屋與白色房屋吸收輻射量的差異。",
    ),
    GenRunItem(
        key="fishing-harbor-renovation|0|3",
        file_stem="fishing-harbor-renovation",
        item_idx=0,
        seq=3,
        stem_snippet="請說明為何魚港整修時選用白色塗料比黑色塗料更能降低室內溫度。",
    ),
    GenRunItem(
        key="hot-pack|0|2",
        file_stem="hot-pack",
        item_idx=0,
        seq=2,
        stem_snippet="請利用實驗一的結果，說明選擇暖暖包時應如何取捨升溫效率和成本。",
    ),
    GenRunItem(
        key="hot-pack|0|3",
        file_stem="hot-pack",
        item_idx=0,
        seq=3,
        stem_snippet="請從實驗數據推論，食鹽對暖暖包的加熱效果是否有顯著影響？",
    ),
    GenRunItem(
        key="sea-ice-land-ice|0|1",
        file_stem="sea-ice-land-ice",
        item_idx=0,
        seq=1,
        stem_snippet="請說明此實驗模型與真實海洋冰川環境的主要差異。",
    ),
    GenRunItem(
        key="seawater-vertical-properties|0|1",
        file_stem="seawater-vertical-properties",
        item_idx=0,
        seq=1,
        stem_snippet="請說明海水溫度隨深度增加而降低的原因。",
    ),
    GenRunItem(
        key="seawater-vertical-properties|0|3",
        file_stem="seawater-vertical-properties",
        item_idx=0,
        seq=3,
        stem_snippet="請解釋為何躍溫層在海洋生態中具有重要意義。",
    ),
    GenRunItem(
        key="weather-proverbs|0|1",
        file_stem="weather-proverbs",
        item_idx=0,
        seq=1,
        stem_snippet="請說明梅雨鋒面形成的主要氣象條件。",
    ),
    GenRunItem(
        key="weather-proverbs|0|3",
        file_stem="weather-proverbs",
        item_idx=0,
        seq=3,
        stem_snippet="請根據俗諺推論，七月颱風帶來的降雨與梅雨季的降雨有何不同？",
    ),
    GenRunItem(
        key="black-white-car-heat|0|1",
        file_stem="black-white-car-heat",
        item_idx=0,
        seq=1,
        stem_snippet="請說明黑色與白色物體在陽光下升溫差異的物理原因。",
    ),
    GenRunItem(
        key="black-white-car-heat|0|2",
        file_stem="black-white-car-heat",
        item_idx=0,
        seq=2,
        stem_snippet="請從實驗數據說明車內空氣的熱對流如何影響升溫速率。",
    ),
    GenRunItem(
        key="soil-liquefaction|0|1",
        file_stem="soil-liquefaction",
        item_idx=0,
        seq=1,
        stem_snippet="請說明土壤液化發生的主要條件。",
    ),
    GenRunItem(
        key="soil-liquefaction|0|2",
        file_stem="soil-liquefaction",
        item_idx=0,
        seq=2,
        stem_snippet="請從圖表說明土壤液化程度與哪些因素有關。",
    ),
    GenRunItem(
        key="entomopathogenic-fungi|0|1",
        file_stem="entomopathogenic-fungi",
        item_idx=0,
        seq=1,
        stem_snippet="請說明昆蟲感染蟲生真菌後，哪一階段會讓病菌向外傳播？",
    ),
    GenRunItem(
        key="crazy-track|0|1",
        file_stem="crazy-track",
        item_idx=0,
        seq=1,
        stem_snippet="請說明此軌道設計如何達到加速效果。",
    ),
    GenRunItem(
        key="crazy-track|0|2",
        file_stem="crazy-track",
        item_idx=0,
        seq=2,
        stem_snippet="請從能量觀點分析，此軌道中動能與位能的轉換。",
    ),
    GenRunItem(
        key="truck-cornering|0|1",
        file_stem="truck-cornering",
        item_idx=0,
        seq=1,
        stem_snippet="請說明重心位置如何影響貨車過彎的穩定性。",
    ),
    GenRunItem(
        key="truck-cornering|0|2",
        file_stem="truck-cornering",
        item_idx=0,
        seq=2,
        stem_snippet="請從摩擦力與向心力的關係，說明過彎速度與翻車風險的關聯。",
    ),
    GenRunItem(
        key="wind-corridor-effect|0|1",
        file_stem="wind-corridor-effect",
        item_idx=0,
        seq=1,
        stem_snippet="請說明都市熱島效應的形成機制。",
    ),
    GenRunItem(
        key="washing-machine-physics|0|2",
        file_stem="washing-machine-physics",
        item_idx=0,
        seq=2,
        stem_snippet="請說明脫水進程中，水分被甩出通過孔槽的物理原理。",
    ),
    GenRunItem(
        key="washing-machine-physics|0|6",
        file_stem="washing-machine-physics",
        item_idx=0,
        seq=6,
        stem_snippet="請說明型號B較型號A可以延長軸承使用年限的原因。",
    ),
    GenRunItem(
        key="胡椒蛾的分子機制|0|1",
        file_stem="胡椒蛾的分子機制",
        item_idx=0,
        seq=1,
        stem_snippet="請說明黑色等位基因B如何透過轉錄與轉譯影響胡椒蛾的表徵？",
    ),
    GenRunItem(
        key="胡椒蛾的分子機制|0|2",
        file_stem="胡椒蛾的分子機制",
        item_idx=0,
        seq=2,
        stem_snippet="請從等位基因轉錄、轉譯產物及對表徵影響的角度，分別解釋顯性與隱性的原因。",
    ),
]

assert len(GENERATION_RUN_ITEMS) == 30, f"Expected 30 gen-run items, got {len(GENERATION_RUN_ITEMS)}"

# ---------------------------------------------------------------------------
# Rubric-writing prompt template
# ---------------------------------------------------------------------------

RUBRIC_WRITING_SYSTEM_PROMPT = """\
你是108課綱自然科學領域素養導向命題的評分規準撰寫專家。
根據提供的小題，請撰寫符合以下規則的評分規準。

{rule}

## 輸出格式
請直接輸出 JSON（無 markdown 包裹）：
{{
  "rubric_level_2": "<[2] 規準說明>",
  "rubric_level_1": "<[1] 規準說明>",
  "rubric_level_0": "<[0] 規準說明>",
  "examples_2": ["<學生作答實例1>", "<學生作答實例2>"],
  "examples_1": ["<學生作答實例1（最小對照）>", "<學生作答實例2（另一種缺口）>"],
  "examples_0": ["<學生作答實例>"],
  "every_item_required": <true|false>,
  "every_item_required_reason": "<一句話說明>"
}}
""".format(rule=OPEN_RESPONSE_RUBRIC_RULE)

RUBRIC_WRITING_USER_TEMPLATE = """\
請為以下小題撰寫評分規準。

## 小題題目
{stem}

## 參考答案（如有）
{answer}

## 注意事項
- 請在 [2] 規準說明結尾逐字加上固定句：
  「{fixed_sentence}」
- 若此小題要求學生所寫的每一項均須成立（皆/均/都/全部），
  請在 every_item_required 中填 true，否則填 false。
""".format(
    stem="{stem}",
    answer="{answer}",
    fixed_sentence=EXTRA_ITEMS_FIXED_SENTENCE,
)

# ---------------------------------------------------------------------------
# Step 1: Programmatic count — EXTRA_ITEMS_FIXED_SENTENCE in corpus
# ---------------------------------------------------------------------------

def step1_extra_items_count() -> None:
    counts = count_extra_items_sentence(CR_DIR)
    total = counts["total"]
    has = counts["has_sentence"]
    print(f"\n[Step 1] EXTRA_ITEMS_FIXED_SENTENCE count in Constructed-response corpus")
    print(f"  Total [2] rubric entries: {total}")
    print(f"  Has fixed sentence:       {has} ({100*has/total:.1f}%)")
    print(f"  Missing fixed sentence:   {total - has}")
    print(
        "  → Baseline: 0% of existing corpus rubrics have the #871 fixed sentence. "
        "The generation-run measures whether the new rubric-writing prompt achieves "
        "≥90% inclusion."
    )


# ---------------------------------------------------------------------------
# Step 2: every_item_required labelled set evaluation (needs LLM)
# ---------------------------------------------------------------------------

def step2_eir_evaluation(client: LLMClient, config: Any, cache: dict) -> None:

    results = []
    model = config.model_verify
    for item in EIR_LABELLED_SET:
        cache_key = f"eir|{item.key}"
        if cache_key in cache:
            resp = cache[cache_key]
            print(f"  [cache] {item.key}")
        else:
            print(f"  [call]  {item.key}", end="", flush=True)
            user_msg = VERIFIER_USER_TEMPLATE_V2.format(
                stem=item.stem_snippet,
                rubric_2=item.rubric_level_2,
            )
            try:
                raw = client.generate_json(
                    system=VERIFIER_SYSTEM_V2,
                    user=user_msg,
                    model=model,
                    purpose="verify",
                )
                resp = {"key": cache_key, "label": item.label, "raw": raw}
                _save_cache_entry(RESPONSES_873, resp)
                cache[cache_key] = resp
                print(" ✓")
            except Exception as e:
                print(f" ERROR: {e}")
                results.append({"key": item.key, "label": item.label, "error": str(e)})
                continue
            time.sleep(0.3)

        # Parse result
        try:
            pred_eir = resp["raw"].get("every_item_required")
            results.append({
                "key": item.key,
                "label": item.label,
                "pred": pred_eir,
                "match": pred_eir == item.label,
                "source": item.source,
            })
        except Exception as e:
            results.append({"key": item.key, "label": item.label, "error": str(e)})

    # Confusion matrix
    tp = sum(1 for r in results if r.get("label") and r.get("pred"))
    fn = sum(1 for r in results if r.get("label") and not r.get("pred"))
    fp = sum(1 for r in results if not r.get("label") and r.get("pred"))
    tn = sum(1 for r in results if not r.get("label") and not r.get("pred"))
    print(f"\n[Step 2] every_item_required confusion matrix (n={len(results)})")
    print(f"  TP={tp} FN={fn} FP={fp} TN={tn}")
    if tp + fn > 0:
        print(f"  Recall: {tp}/{tp+fn} = {tp/(tp+fn):.1%}")
    if fp + tn > 0:
        print(f"  FPR:    {fp}/{fp+tn} = {fp/(fp+tn):.1%}")


# ---------------------------------------------------------------------------
# Step 3: Generation-run rubric writing (needs LLM)
# ---------------------------------------------------------------------------

def step3_generation_run(client: LLMClient, config: Any, cache: dict) -> None:
    print(f"\n[Step 3] Generation-run rubric writing ({len(GENERATION_RUN_ITEMS)} items)")

    # Load actual stem text from corpus
    corpus_data: dict[str, Any] = {}
    for json_file in CR_DIR.glob("*.json"):
        try:
            data = json.loads(json_file.read_text())
        except Exception:
            continue
        corpus_data[json_file.stem] = data

    generated_rubrics = []
    for item in GENERATION_RUN_ITEMS:
        if item.counting_stem_needs_conversion:
            print(f"  [skip]  {item.key} — needs #650 conversion first")
            print(f"          → {item.conversion_note[:80]}")
            continue

        cache_key = f"genrun|{item.key}"
        if cache_key in cache:
            print(f"  [cache] {item.key}")
            resp = cache[cache_key]
        else:
            # Load stem from corpus
            file_data = corpus_data.get(item.file_stem)
            if file_data is None:
                print(f"  [skip]  {item.key} — file not found")
                continue
            items_list = file_data if isinstance(file_data, list) else [file_data]
            try:
                item_obj = items_list[item.item_idx]
            except IndexError:
                print(f"  [skip]  {item.key} — item_idx out of range")
                continue
            q = item_obj.get("question", item_obj)
            sqs = q.get("subquestions", [])
            sq = next((s for s in sqs if s.get("序號") == item.seq), None)
            if sq is None:
                print(f"  [skip]  {item.key} — seq {item.seq} not found")
                continue
            stem_full = sq.get("題目", "")
            answer = sq.get("答案", sq.get("答案解析", "（未提供）"))[:200]

            user_msg = RUBRIC_WRITING_USER_TEMPLATE.format(
                stem=stem_full,
                answer=answer,
            )
            print(f"  [call]  {item.key}", end="", flush=True)
            try:
                raw = client.generate_json(
                    system=RUBRIC_WRITING_SYSTEM_PROMPT,
                    user=user_msg,
                    model=config.model_verify,
                    purpose="verify",
                )
                resp = {"key": cache_key, "raw": raw}
                _save_cache_entry(RESPONSES_873, resp)
                cache[cache_key] = resp
                print(" ✓")
            except Exception as e:
                print(f" ERROR: {e}")
                continue
            time.sleep(0.3)

        # Count EXTRA_ITEMS_FIXED_SENTENCE
        rubric_2 = resp.get("raw", {}).get("rubric_level_2", "")
        has_fixed = EXTRA_ITEMS_FIXED_SENTENCE in rubric_2
        eir = resp.get("raw", {}).get("every_item_required", None)
        generated_rubrics.append({
            "key": item.key,
            "has_fixed_sentence": has_fixed,
            "every_item_required": eir,
            "rubric_2": rubric_2[:80],
        })

    if generated_rubrics:
        total = len(generated_rubrics)
        has_fixed = sum(1 for r in generated_rubrics if r["has_fixed_sentence"])
        eir_true = sum(1 for r in generated_rubrics if r["every_item_required"])
        print(f"\n[Step 3 results]")
        print(f"  Items generated: {total}")
        print(f"  Has EXTRA_ITEMS_FIXED_SENTENCE: {has_fixed}/{total} ({100*has_fixed/total:.1f}%)")
        print(f"  every_item_required = True: {eir_true}/{total} ({100*eir_true/total:.1f}%)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("Research #873 — every_item_required")
    print("=" * 60)

    # Step 1: Programmatic count (always runs)
    step1_extra_items_count()

    # Check for LLM credits
    try:
        config = Config.from_env()
        client = LLMClient(config)
    except Exception as e:
        print(f"\n[WARN] Cannot initialize LLMClient: {e}")
        print("Steps 2 and 3 require API credits. Exiting.")
        return

    # Test API credit availability with a minimal call
    try:
        _ = client.generate_json(
            system='Reply with JSON: {"ok": true}',
            user="ping",
            model=config.model_verify,
            purpose="verify",
        )
    except Exception as e:
        err = str(e)
        if "credit" in err.lower() or "balance" in err.lower() or "400" in err:
            print(f"\n[WARN] API credit check failed: {err}")
            print("Steps 2 and 3 skipped — restore credits and rerun.")
            return
        # Other errors: proceed (might succeed on actual calls)

    # Load cache
    cache = _load_cache(RESPONSES_873)
    print(f"\n[cache] Loaded {len(cache)} entries from {RESPONSES_873.name}")

    # Step 2: every_item_required labelled set evaluation
    step2_eir_evaluation(client, config, cache)

    # Step 3: Generation-run rubric writing
    step3_generation_run(client, config, cache)

    print("\nDone.")


if __name__ == "__main__":
    main()
