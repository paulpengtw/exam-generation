"""
Research #873 — every_item_required field: labelled set and generation-run input.

This script:
1. Defines the every_item_required labelled set (22 corpus entries + synthetic
   positives + near-misses). ALL 22 rubric levels that use 皆/均/都/全部 in
   open-response (Constructed-response) 小題 across every NS few_shot folder
   are included. Only fasting-method seq=3 code=2 is True; all others are False.
2. Runs the every_item_required evaluation on the labelled set (reads cache first;
   LLM calls only for entries not yet cached). Reports the confusion matrix.
3. Collects 30 open-response 小題 from the NS few-shot corpus as generation-run
   input (3 flagged for #650 conversion, 27 ready).
4. For each ready generation-run item, prompts the model to write a rubric using
   OPEN_RESPONSE_RUBRIC_RULE. Caches every response.
5. Computes two counts from the generation-run output:
   a. EXTRA_ITEMS_FIXED_SENTENCE substring check (programmatic — no LLM needed).
   b. every_item_required hand-label slot (requires LLM).

Cache key scheme:
  - every_item_required labelled set: "eir|{key}"
  - generation-run rubric responses:  "genrun|{file_stem}|{item_idx}|{seq}"

Rubric key shape handling:
  Standard: {code, 規準說明, 學生作答實例}
  Legacy:   {編碼, 說明}
  Both are queried with get() fallback.

IMPORTANT: No LLM calls are made until API credits are restored.
Step 1 (EXTRA_ITEMS_FIXED_SENTENCE count) runs immediately.
LLM-dependent steps 2 and 3 are gated behind a credit probe.

Run from the repo root:
    uv run python scripts/research/rubric_873_harness.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
from dataclasses import dataclass
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
from src.config import Config  # noqa: E402
from src.llm_client import LLMClient  # noqa: E402

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
CR_DIR = ROOT / "data" / "natural_sciences" / "few_shot" / "Constructed-response"
FS_DIR = ROOT / "data" / "natural_sciences" / "few_shot"
OUT_873 = ROOT / "docs" / "research" / "873-every-item-required"
OUT_873.mkdir(parents=True, exist_ok=True)

RESPONSES_873 = OUT_873 / "responses.jsonl"

# ---------------------------------------------------------------------------
# every_item_required definition
# ---------------------------------------------------------------------------
#
# every_item_required = True iff:
#   The [2] level uses 皆/均/都/全部 over a STUDENT-GENERATED (open) scope:
#   any item the student independently writes must satisfy the condition,
#   and extra wrong-scope items cause a downgrade to [1].
#   Pattern: 「所提結論皆…」, 「所列理由均須…」, 「每一項都…」
#
# every_item_required = False when:
#   - 皆/均/都/全部 applies only to a set the 小題 names in advance
#     (「兩個條件均提及」, 「五點全部正確…」, 「甲、乙兩者均…」).
#     Student-added extras are NOT penalised.
#   - 皆/均/都/全部 applies to parts of ONE required answer chain
#     (「主張與數據皆須相符」) — not to extra student items.
#   - 皆/均/都/全部 appears in code=1 or code=0 criteria, not code=2.
#   - The rubric has no 皆/均/都/全部 at all.
#
# KEY TEST: "student-driven open scope" (True) vs "question-framed members
#           or single-answer-chain parts" (False).

# ---------------------------------------------------------------------------
# Labelled set for every_item_required
# ---------------------------------------------------------------------------

@dataclass
class EIRItem:
    """One labelled entry for the every_item_required evaluation."""
    key: str           # unique key — format: "{source}|{file_stem}|{seq}|{code}"
    file_stem: str     # JSON filename stem (or "(synthetic)")
    seq: int | None    # 小題 序號 (None for synthetic)
    item_idx: int      # item index within the file (0-based)
    code: str          # rubric code: "2", "1", "0", or "N/A" for synthetic
    label: bool        # gold label: True = every_item_required
    label_rule: str    # which rule clause determines label
    stem_snippet: str  # first ~70 chars of 題目
    rubric_desc: str   # the rubric entry 規準說明 verbatim (whichever code hits)
    source: str        # "corpus" | "synth_positive" | "near_miss"


# ── CORPUS: 22 rubric levels in 19 open-response 小題 ─────────────────────
# Scan: python3 -c "
#   import json,pathlib
#   fs=pathlib.Path('data/natural_sciences/few_shot')
#   for f in fs.rglob('*.json'):
#     d=json.loads(f.read_text())
#     items=d if isinstance(d,list) else [d]
#     for i,item in enumerate(items):
#       q=item.get('question',item)
#       for sq in q.get('subquestions',[]):
#         if 'Constructed' not in sq.get('題型',''):continue
#         for r in sq.get('評分規準',[]):
#           code=r.get('code',r.get('編碼',''))
#           desc=r.get('規準說明',r.get('說明',''))
#           if any(kw in desc for kw in ['皆','均','都','全部']):
#             print(f'{f.stem} item={i} seq={sq[\"序號\"]} code={code}: {desc[:80]}')
# "
# Hit count: 22 entries, 19 unique (file, item_idx, seq) triples.
# Only fasting-method seq=3 code=2 is True. Ticket criterion: 21 framed-set False.

EIR_LABELLED_SET: list[EIRItem] = [

    # ── Corpus True (1) ────────────────────────────────────────────────────
    #
    # fasting-method seq=3 code=2:
    # 「且均基於組間比較」 — student writes free conclusions; every conclusion
    # must be based on inter-group comparison (student-driven open scope).
    # Any extra conclusion that is NOT 基於組間比較 → [1].
    EIRItem(
        key="corpus|fasting-method|3|2",
        file_stem="fasting-method",
        seq=3,
        item_idx=0,
        code="2",
        label=True,
        label_rule="T1: 均 over student-generated conclusions (open scope)",
        stem_snippet="請問以上實驗可以得出什麼結論？（請寫兩個結論）",
        rubric_desc="正確寫出兩個合理且有所不同的結論，且均基於組間比較",
        source="corpus",
    ),

    # ── Corpus False — framed-set and answer-chain uses of 皆/均/都/全部 ────

    # entomopathogenic-fungi seq=3 code=2:
    # 「兩個條件均提及」 — 兩個條件 (保護行, 多區塊設計) named in the rubric.
    EIRItem(
        key="corpus|entomopathogenic-fungi|3|2",
        file_stem="entomopathogenic-fungi",
        seq=3,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1: 均 over two named members (保護行, 多區塊設計)",
        stem_snippet="曉萍決定以藥劑A來進行田間施藥試驗…如何設計實驗才能控制變因？",
        rubric_desc=(
            "同時提及保護行避免藥液污染，以及多區塊設計避免位置效應（兩個條件均提及）"
        ),
        source="corpus",
    ),

    # fishing-harbor-renovation seq=2 code=2:
    # 「兩組數據均正確標示」 — 兩組 are named experimental groups (黑/白房屋).
    EIRItem(
        key="corpus|fishing-harbor-renovation|2|2",
        file_stem="fishing-harbor-renovation",
        seq=2,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1: 均 over two named experimental groups (黑色/白色房屋)",
        stem_snippet="試將兩組房屋溫度數據繪製成適當的圖形（折線圖）。",
        rubric_desc=(
            "正確繪製折線圖，橫軸時間、縱軸溫度，兩組數據均正確標示並有完整圖例"
        ),
        source="corpus",
    ),

    # hot-pack seq=4 code=2:
    # 「兩組數據均正確繪出」 — 兩組 are named experimental groups (實驗1/實驗2).
    EIRItem(
        key="corpus|hot-pack|4|2",
        file_stem="hot-pack",
        seq=4,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1: 均 over two named experimental groups (實驗1, 實驗2)",
        stem_snippet="試將實驗1與實驗2的數據繪製成適當且正確的圖形。",
        rubric_desc=(
            "正確選用折線圖，橫軸為時間、縱軸為溫度，兩組數據均正確繪出並有標示"
        ),
        source="corpus",
    ),

    # sea-ice-land-ice seq=2 code=2:
    # 「海冰組和陸冰組…均正確」 — 兩組 are named groups.
    EIRItem(
        key="corpus|sea-ice-land-ice|2|2",
        file_stem="sea-ice-land-ice",
        seq=2,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1: 均 over two named groups (海冰組, 陸冰組)",
        stem_snippet="請預測冰塊融化後海冰組及陸冰組水面高度變化，並說明理由。",
        rubric_desc=(
            "海冰組和陸冰組預測及理由均正確，且引用阿基米德原理或質量守恆解釋"
        ),
        source="corpus",
    ),

    # sea-ice-land-ice seq=3 code=2:
    # 「兩項均選擇合理器材」 — 兩項 = 陸地/海洋 roles named by question.
    EIRItem(
        key="corpus|sea-ice-land-ice|3|2",
        file_stem="sea-ice-land-ice",
        seq=3,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1: 均 over two named roles (陸地, 海洋) in framed choice",
        stem_snippet="請選擇器材模擬陸地與海洋，並說明理由。",
        rubric_desc=(
            "兩項均選擇合理器材，且理由充分說明為何比木板更適合"
        ),
        source="corpus",
    ),

    # seawater-vertical-properties seq=2 code=2:
    # 「五點全部正確」 — 五點 are given data points in the table.
    EIRItem(
        key="corpus|seawater-vertical-properties|2|2",
        file_stem="seawater-vertical-properties",
        seq=2,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1: 全部 over five given data points in the table",
        stem_snippet="請將五點不同水深的海水參數依海水深度由淺至深重新排列。",
        rubric_desc="五點全部正確依深度排列",
        source="corpus",
    ),

    # soil-liquefaction seq=5 code=0:
    # 「兩人評估均錯誤」 — code=0; 兩人 are named evaluators (小彥, 小禮).
    EIRItem(
        key="corpus|soil-liquefaction|5|0",
        file_stem="soil-liquefaction",
        seq=5,
        item_idx=0,
        code="0",
        label=False,
        label_rule="F1+code0: code=0 criterion; 均 over two named evaluators",
        stem_snippet="小彥與小禮分別提出不同的防液化方法評估，請評估兩人的說法。",
        rubric_desc="兩人評估均錯誤或未作答",
        source="corpus",
    ),

    # truck-cornering seq=2 code=0:
    # 「兩問均錯誤」 — code=0; 兩問 are the two named sub-question parts.
    EIRItem(
        key="corpus|truck-cornering|2|0",
        file_stem="truck-cornering",
        seq=2,
        item_idx=0,
        code="0",
        label=False,
        label_rule="F1+code0: code=0 criterion; 均 over two named sub-question parts",
        stem_snippet="請說明貨車過彎穩定性的影響因素，並計算安全過彎速度。",
        rubric_desc="兩問均錯誤或說明與力學原理不符",
        source="corpus",
    ),

    # weather-proverbs seq=1 code=1:
    # 「兩個都說出但機制解釋不完整」 — code=1; 兩個 systems named (梅雨鋒/太平洋高壓).
    EIRItem(
        key="corpus|weather-proverbs|1|1",
        file_stem="weather-proverbs",
        seq=1,
        item_idx=0,
        code="1",
        label=False,
        label_rule="F1+code1: code=1 criterion; 都 over two named weather systems",
        stem_snippet="請說明五月與六月南風代表不同天氣型態的原因。",
        rubric_desc=(
            "只正確說明其中一個系統，或兩個都說出但機制解釋不完整"
        ),
        source="corpus",
    ),

    # weather-proverbs seq=2 code=2:
    # 「兩種系統均正確標示」 — 兩種系統 named (北方鋒面, 東方高壓).
    EIRItem(
        key="corpus|weather-proverbs|2|2",
        file_stem="weather-proverbs",
        seq=2,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1: 均 over two named weather systems (北方鋒面, 東方高壓)",
        stem_snippet="請在圖中標示影響五月與六月氣候的天氣系統位置、風向及天氣型態。",
        rubric_desc=(
            "兩種系統均正確標示位置（北方鋒面/東方高壓）、"
            "風向（南風箭頭）與天氣型態（多雨/晴朗）"
        ),
        source="corpus",
    ),

    # weather-proverbs seq=2 code=1:
    # 「兩種均標示但缺少…」 — code=1; same named pair.
    EIRItem(
        key="corpus|weather-proverbs|2|1",
        file_stem="weather-proverbs",
        seq=2,
        item_idx=0,
        code="1",
        label=False,
        label_rule="F1+code1: code=1; 均 over two named weather systems",
        stem_snippet="請在圖中標示影響五月與六月氣候的天氣系統位置、風向及天氣型態。",
        rubric_desc=(
            "一種系統正確標示，另一種有誤；"
            "或兩種均標示但缺少風向或天氣型態說明"
        ),
        source="corpus",
    ),

    # weather-proverbs seq=2 code=0:
    # 「兩種系統均標示錯誤」 — code=0; same named pair.
    EIRItem(
        key="corpus|weather-proverbs|2|0",
        file_stem="weather-proverbs",
        seq=2,
        item_idx=0,
        code="0",
        label=False,
        label_rule="F1+code0: code=0; 均 over two named weather systems",
        stem_snippet="請在圖中標示影響五月與六月氣候的天氣系統位置、風向及天氣型態。",
        rubric_desc=(
            "兩種系統均標示錯誤，或圖示與說明完全不符天氣系統特性"
        ),
        source="corpus",
    ),

    # 大氣能見度 seq=3 code=2 (legacy):
    # 「表格全部答對」 — 全部 over table cells pre-specified by the 小題.
    EIRItem(
        key="corpus|大氣能見度|3|2",
        file_stem="大氣能見度",
        seq=3,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1: 全部 over pre-specified table cells (AQI fill-in)",
        stem_snippet="請依監測資料填寫各污染物副指標值及當日AQI。",
        rubric_desc="表格全部答對",
        source="corpus",
    ),

    # 拉塞福散射 seq=2 code=0 (legacy):
    # 「兩者均錯」 — code=0; 兩者 = the two named positions.
    EIRItem(
        key="corpus|拉塞福散射|2|0",
        file_stem="拉塞福散射",
        seq=2,
        item_idx=0,
        code="0",
        label=False,
        label_rule="F1+code0: code=0; 均 over two named positions (第一/最後投影幕)",
        stem_snippet="請填入第一個及最後一個設置的投影幕位置編號。",
        rubric_desc="兩者均錯",
        source="corpus",
    ),

    # 日食 seq=2 code=1 (legacy):
    # 「兩個問題均為『是』」 — code=1; 兩個問題 named (靠近/靠近眼前).
    EIRItem(
        key="corpus|日食|2|1",
        file_stem="日食",
        seq=2,
        item_idx=0,
        code="1",
        label=False,
        label_rule="F1+code1: code=1; 均 over two named yes/no questions",
        stem_snippet="觀察大拇指靠近太陽與靠近眼前時，能否遮住太陽？",
        rubric_desc=(
            "正確回答兩個問題均為「是」（靠近和靠近眼前均能遮住），"
            "或正確區分靠近vs.遠離的遮蓋效果差異。"
        ),
        source="corpus",
    ),

    # 果凍 seq=5 code=1 (legacy):
    # 「兩者都需寫出才給分」 — code=1; 兩者 = 蛋白質 and 酵素 (named).
    EIRItem(
        key="corpus|果凍|5|1",
        file_stem="果凍",
        seq=5,
        item_idx=0,
        code="1",
        label=False,
        label_rule="F1+code1: code=1; 都 over two named keywords (蛋白質, 酵素)",
        stem_snippet="請說明新鮮木瓜抑止吉利丁果凍形成的原因（引用參考資料）。",
        rubric_desc=(
            "同時寫出「蛋白質」和「酵素」兩個關鍵字（明膠的蛋白質被木瓜酵素分解），"
            "兩者都需寫出才給分。"
        ),
        source="corpus",
    ),

    # 生長素與向光性 seq=6 code=2 (legacy):
    # 「a=40；b=50；a'=45；b'=45全部正確」 — 全部 over 4 named values.
    EIRItem(
        key="corpus|生長素與向光性|6|2",
        file_stem="生長素與向光性",
        seq=6,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1: 全部 over four named calculated values (a, b, a', b')",
        stem_snippet="請推算a、b、a'、b'四塊洋菜膠中的生長素含量。",
        rubric_desc="a=40；b=50；a'=45；b'=45全部正確",
        source="corpus",
    ),

    # 胡椒蛾の分子機制 seq=3 code=0 (legacy):
    # 「全部錯誤」 — code=0; 全部 means student's answers all wrong, not EIR.
    EIRItem(
        key="corpus|胡椒蛾の分子機制|3|0",
        file_stem="胡椒蛾的分子機制",
        seq=3,
        item_idx=0,
        code="0",
        label=False,
        label_rule="F3+code0: code=0; 全部 means all-answers-wrong, not EIR scope",
        stem_snippet="造成黑色等位基因比例增加的可能原因有哪些？（請至少列舉三項）",
        rubric_desc="未作答或全部錯誤",
        source="corpus",
    ),

    # 蛙勒 seq=2 code=2 (legacy):
    # 「四個項目全部答對」 — 全部 over 四個項目 (named in the fill-in table).
    EIRItem(
        key="corpus|蛙勒|2|2",
        file_stem="蛙勒",
        seq=2,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1: 全部 over four named table items",
        stem_snippet="請依據說明填寫表(一)（生殖方式、受精方式、類似構造、生態意義）。",
        rubric_desc=(
            "四個項目全部答對（項目4提及能增加受精機率或子代數目等意義）。"
        ),
        source="corpus",
    ),

    # 蛙勒 seq=2 code=0 (legacy):
    # 「全部答錯」 — code=0; same framed table.
    EIRItem(
        key="corpus|蛙勒|2|0",
        file_stem="蛙勒",
        seq=2,
        item_idx=0,
        code="0",
        label=False,
        label_rule="F1+code0: code=0; 全部 over named table items (all wrong)",
        stem_snippet="請依據說明填寫表(一)（生殖方式、受精方式、類似構造、生態意義）。",
        rubric_desc="多項答錯或全部答錯。",
        source="corpus",
    ),

    # 自製夢幻飲品 seq=6 code=0 (legacy, Simple-MC folder but type=Constructed response):
    # 「兩種顏色皆錯誤」 — code=0; 皆 over 兩種顏色 (酸性/鹼性 — named by question).
    EIRItem(
        key="corpus|自製夢幻飲品|6|0",
        file_stem="自製夢幻飲品",
        seq=6,
        item_idx=0,
        code="0",
        label=False,
        label_rule="F1+code0: code=0; 皆 over two named answer items (酸性色/鹼性色)",
        stem_snippet="蝶豆花水溶液在酸性溶液呈現什麼顏色？在鹼性溶液呈現什麼顏色？",
        rubric_desc="僅答出其中一種顏色，或兩種顏色皆錯誤。",
        source="corpus",
    ),

    # ── Synthetic positives: label = True ─────────────────────────────────
    #
    # Pattern: 「所提…皆…」 or 「均須…」 over a student-generated OPEN scope.
    # Any student-added extra item that fails the condition → [1].

    # synth_positive_1: open recommendation question
    EIRItem(
        key="synth|every_item|1",
        file_stem="(synthetic)",
        seq=None,
        item_idx=0,
        code="2",
        label=True,
        label_rule="T1: 皆 over student-generated recommendations (open scope)",
        stem_snippet="請提出至少兩個改善實驗設計的方案。",
        rubric_desc=(
            "提出兩個以上改善方案，且所提方案皆應可行並與實驗數據相關。"
            "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
        ),
        source="synth_positive",
    ),

    # synth_positive_2: open causal explanation question
    EIRItem(
        key="synth|every_item|2",
        file_stem="(synthetic)",
        seq=None,
        item_idx=0,
        code="2",
        label=True,
        label_rule="T1: 均 over student-generated causal explanations (open scope)",
        stem_snippet="請說明可能造成此現象的原因。",
        rubric_desc=(
            "正確說明兩個以上可能原因，且均須基於文本所提供的數據或機制。"
            "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
        ),
        source="synth_positive",
    ),

    # synth_positive_3: open evidence-based argument question
    EIRItem(
        key="synth|every_item|3",
        file_stem="(synthetic)",
        seq=None,
        item_idx=0,
        code="2",
        label=True,
        label_rule="T1: 都 over student-generated arguments (open scope)",
        stem_snippet="請利用實驗數據提出支持此假設的論點。",
        rubric_desc=(
            "提出兩個以上論點，且所提論點都需引用具體實驗數據加以支撐。"
            "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
        ),
        source="synth_positive",
    ),

    # ── Near-misses: label = False ─────────────────────────────────────────
    #
    # Kind A: 皆/均 over named members of a framed set (looks like True but isn't).
    # Kind B: 皆/均 over parts of ONE required answer chain (「主張與數據皆須相符」).

    # A1: named experimental groups (甲/乙)
    EIRItem(
        key="near_miss|named_pair|1",
        file_stem="(synthetic)",
        seq=None,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1/A: 均 over two named members (甲方法, 乙方法)",
        stem_snippet="請分別說明甲方法與乙方法的優缺點。",
        rubric_desc=(
            "甲方法與乙方法的優缺點均正確說明，且各包含具體科學依據。"
        ),
        source="near_miss",
    ),

    # A2: named variables (操縱變因, 控制變因)
    EIRItem(
        key="near_miss|named_pair|2",
        file_stem="(synthetic)",
        seq=None,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1/A: 均 over two named variable types (操縱變因, 應變變因)",
        stem_snippet="請指出此實驗的操縱變因與應變變因，並說明控制變因的方法。",
        rubric_desc=(
            "操縱變因與應變變因均正確指出，且至少說明一個合理的控制變因。"
        ),
        source="near_miss",
    ),

    # A3: named prediction items (高溫/低溫組)
    EIRItem(
        key="near_miss|named_pair|3",
        file_stem="(synthetic)",
        seq=None,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1/A: 均 over two named experimental conditions (高溫組, 低溫組)",
        stem_snippet="請預測高溫組與低溫組的實驗結果，並說明理由。",
        rubric_desc=(
            "高溫組和低溫組的預測及理由均正確，且引用相關物理化學原理說明。"
        ),
        source="near_miss",
    ),

    # A4: named criteria (定性判斷, 定量計算)
    EIRItem(
        key="near_miss|named_pair|4",
        file_stem="(synthetic)",
        seq=None,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1/A: 均 over two named answer dimensions (定性判斷, 定量計算)",
        stem_snippet="請判斷此設計是否可行，並計算所需能量。",
        rubric_desc=(
            "定性判斷與定量計算均正確，且單位換算無誤。"
        ),
        source="near_miss",
    ),

    # A5: three named table columns (甲/乙/丙 three plants)
    EIRItem(
        key="near_miss|named_triple|1",
        file_stem="(synthetic)",
        seq=None,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F1/A: 全部 over three named plants (甲, 乙, 丙) from the table",
        stem_snippet="請依據圖表資料，判斷甲、乙、丙三種植物的光合速率大小關係。",
        rubric_desc=(
            "甲、乙、丙三種植物的光合速率大小關係全部正確，且能引用圖表數據說明。"
        ),
        source="near_miss",
    ),

    # B1: parts of ONE answer chain — claim + evidence (主張 + 數據)
    EIRItem(
        key="near_miss|answer_chain|1",
        file_stem="(synthetic)",
        seq=None,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F2/B: 均 over parts of ONE required answer chain (claim + data)",
        stem_snippet="請解釋此現象的物理機制（含受力分析與加速度推導）。",
        rubric_desc=(
            "受力分析與加速度推導均正確，且邏輯推論完整不遺漏關鍵步驟。"
        ),
        source="near_miss",
    ),

    # B2: claim + evidence — classic EIR-lookalike
    EIRItem(
        key="near_miss|answer_chain|2",
        file_stem="(synthetic)",
        seq=None,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F2/B: 皆 over parts of ONE argument (主張, 數據)",
        stem_snippet="請用實驗數據說明你的結論。",
        rubric_desc=(
            "所提結論的主張與所引數據皆須相符，且推論方向正確。"
        ),
        source="near_miss",
    ),

    # B3: mechanism + consequence parts of one explanation chain
    EIRItem(
        key="near_miss|answer_chain|3",
        file_stem="(synthetic)",
        seq=None,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F2/B: 均 over cause+effect parts of ONE explanation chain",
        stem_snippet="請說明酵素失去活性的機制及其對細胞代謝的影響。",
        rubric_desc=(
            "機制說明（蛋白質結構改變）與影響（代謝速率降低）均正確，"
            "且兩者的因果關係清楚連結。"
        ),
        source="near_miss",
    ),

    # B4: observation + inference parts of one scientific reasoning chain
    EIRItem(
        key="near_miss|answer_chain|4",
        file_stem="(synthetic)",
        seq=None,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F2/B: 皆 over observation+inference parts of ONE reasoning chain",
        stem_snippet="請根據實驗結果推論，並說明依據。",
        rubric_desc=(
            "觀察到的現象描述與科學推論皆需正確且相互呼應，"
            "推論需明確引用所觀察到的數據。"
        ),
        source="near_miss",
    ),

    # B5: hypothesis + experimental design (two parts of ONE research plan)
    EIRItem(
        key="near_miss|answer_chain|5",
        file_stem="(synthetic)",
        seq=None,
        item_idx=0,
        code="2",
        label=False,
        label_rule="F2/B: 均 over hypothesis+design parts of ONE research proposal",
        stem_snippet="請提出一個可驗證的假設，並設計對應的實驗。",
        rubric_desc=(
            "假設與實驗設計均符合科學邏輯，且實驗設計能有效驗證所提假設。"
        ),
        source="near_miss",
    ),
]

# Verify composition
_true_count = sum(1 for e in EIR_LABELLED_SET if e.label)
_false_count = sum(1 for e in EIR_LABELLED_SET if not e.label)
_corpus = sum(1 for e in EIR_LABELLED_SET if e.source == "corpus")
_synth = sum(1 for e in EIR_LABELLED_SET if e.source == "synth_positive")
_near = sum(1 for e in EIR_LABELLED_SET if e.source == "near_miss")
assert _corpus == 22, f"Expected 22 corpus entries, got {_corpus}"
assert _synth == 3, f"Expected 3 synth_positive entries, got {_synth}"
assert _near == 10, f"Expected 10 near_miss entries, got {_near}"
assert _true_count == 4, f"Expected 4 True entries, got {_true_count}"
assert _false_count == 31, f"Expected 31 False entries, got {_false_count}"

# ---------------------------------------------------------------------------
# Verifier prompt templates
# ---------------------------------------------------------------------------

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
  ——使用「所提結論皆…」「所列理由均須…」「每一項都…」等語句，
  即任何一個學生自行多寫的「錯誤額外項目」會讓學生降為 [1]。

every_item_required 為 False，當：
  - [2] 只要求本小題「事前指名的成員」均成立（如「兩個條件均提及」、
    「甲、乙兩個面向均正確」），學生自行多寫的額外項目不影響結果；
  - [2] 的 皆/均/都/全部 是「一個答案鏈中各步驟均正確」
    （如「主張與數據皆須相符」，不涉及學生是否多寫額外項目）；或
  - [2] 不使用皆/均/都/全部等語句。

請仔細區分：
  「學生自行新增的每一項」（True）
    vs
  「題目預先指名的各成員」（False）
    vs
  「一個答案中各組成部分的品質要求」（False）
""".format(rule_c=OPEN_RESPONSE_RUBRIC_RULE)

VERIFIER_USER_TEMPLATE_V2 = """\
請判斷以下小題的評分規準是否違反規則 C，並判斷是否構成計數式提問（counting_stem），
以及 [2] 級距是否要求學生所寫的每一項均須成立（every_item_required）。

## 小題題目
{stem}

## 評分規準（[{code}] 級距）
{rubric_desc}

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

def count_extra_items_sentence(fs_dir: Path) -> dict[str, int]:
    """Scan all few_shot Constructed-response rubrics; count [2] entries
    with/without EXTRA_ITEMS_FIXED_SENTENCE.  Returns {'total': N, 'has': N}.
    Handles both rubric key shapes (standard: code/規準說明; legacy: 編碼/說明).
    """
    total = 0
    has = 0
    for json_file in sorted(fs_dir.rglob("*.json")):
        try:
            data = json.loads(json_file.read_text())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            q = item.get("question", item)
            for sq in q.get("subquestions", []):
                if "Constructed" not in sq.get("題型", ""):
                    continue
                for r in sq.get("評分規準", []):
                    code = str(r.get("code", r.get("編碼", "")))
                    if code == "2":
                        total += 1
                        desc = r.get("規準說明", r.get("說明", ""))
                        if EXTRA_ITEMS_FIXED_SENTENCE in desc:
                            has += 1
    return {"total": total, "has": has}


# ---------------------------------------------------------------------------
# Generation-run input: 30 open-response 小題 from NS corpus
# ---------------------------------------------------------------------------

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
            "Note: this item also has every_item_required=True."
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
            "observations or reduce to one item."
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
            "「至少三項」 of Hardy-Weinberg violations is counting_stem. "
            "Convert: name the five conditions explicitly or reduce to one."
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
        stem_snippet="曉萍決定以藥劑A進行田間試驗，應如何設計實驗才能控制變因？",
    ),
    GenRunItem(
        key="fasting-method|0|2",
        file_stem="fasting-method",
        item_idx=0,
        seq=2,
        stem_snippet="小丁與小基各自提出一個假設，請說明哪個假設更合理並說明理由。",
    ),
    GenRunItem(
        key="fasting-method|0|4",
        file_stem="fasting-method",
        item_idx=0,
        seq=4,
        stem_snippet="下列哪一個計畫適合雷神索爾？請依據圖一、圖二及圖三的資料說明理由。",
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
        stem_snippet="請分別解釋為何大多突變前的等位基因為顯性，而突變後的等位基因為隱性。",
    ),
]

assert len(GENERATION_RUN_ITEMS) == 30, (
    f"Expected 30 gen-run items, got {len(GENERATION_RUN_ITEMS)}"
)

# ---------------------------------------------------------------------------
# Rubric-writing prompt template
# ---------------------------------------------------------------------------

RUBRIC_WRITING_SYSTEM_PROMPT = (
    "你是108課綱自然科學領域素養導向命題的評分規準撰寫專家。\n"
    "根據提供的小題，請撰寫符合以下規則的評分規準。\n\n"
    + OPEN_RESPONSE_RUBRIC_RULE
    + "\n\n## 輸出格式\n"
    "請直接輸出 JSON（無 markdown 包裹）：\n"
    '{"rubric_level_2": "...", "rubric_level_1": "...", "rubric_level_0": "...", '
    '"examples_2": ["...","..."], "examples_1": ["...","..."], "examples_0": ["..."], '
    '"every_item_required": <true|false>, "every_item_required_reason": "..."}\n'
)

RUBRIC_WRITING_USER_TEMPLATE = (
    "請為以下小題撰寫評分規準。\n\n"
    "## 小題題目\n{stem}\n\n"
    "## 參考答案（如有）\n{answer}\n\n"
    "## 注意事項\n"
    f"- 請在 [2] 規準說明結尾逐字加上固定句：\n"
    f"  「{EXTRA_ITEMS_FIXED_SENTENCE}」\n"
    "- 若此小題要求學生所寫的每一項均須成立（皆/均/都/全部），\n"
    "  請在 every_item_required 中填 true，否則填 false。\n"
)

# ---------------------------------------------------------------------------
# Step 1: Programmatic count — EXTRA_ITEMS_FIXED_SENTENCE in corpus
# ---------------------------------------------------------------------------

def step1_extra_items_count() -> None:
    counts = count_extra_items_sentence(FS_DIR)
    total = counts["total"]
    has = counts["has"]
    print("\n[Step 1] EXTRA_ITEMS_FIXED_SENTENCE count in Constructed-response corpus")
    print(f"  Total [2] rubric entries: {total}")
    print(f"  Has fixed sentence:       {has} ({100*has/total:.1f}% if total else 'N/A')")
    print(f"  Missing fixed sentence:   {total - has}")
    print(
        "  → Baseline: 0% of existing corpus rubrics have the #871 fixed sentence.\n"
        "    The generation-run measures whether the new prompt achieves ≥90% inclusion."
    )
    print("\n[Step 1] Labelled set composition")
    print("  Corpus (22 rubric levels in 19 小題): True=1, False=21")
    print("  Synthetic positives (3): True=3")
    print("  Near-misses (10): False=10")
    print(f"  Total: {len(EIR_LABELLED_SET)} entries (True={_true_count}, False={_false_count})")


# ---------------------------------------------------------------------------
# Step 2: every_item_required labelled set evaluation (needs LLM)
# ---------------------------------------------------------------------------

def step2_eir_evaluation(client: LLMClient, config: Any, cache: dict) -> None:
    model = config.model_verify
    results = []
    for item in EIR_LABELLED_SET:
        cache_key = f"eir|{item.key}"
        if cache_key in cache:
            resp = cache[cache_key]
            print(f"  [cache] {item.key}")
        else:
            print(f"  [call]  {item.key}", end="", flush=True)
            user_msg = VERIFIER_USER_TEMPLATE_V2.format(
                stem=item.stem_snippet,
                code=item.code,
                rubric_desc=item.rubric_desc,
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
                results.append({"key": item.key, "label": item.label,
                                "source": item.source, "error": str(e)})
                continue
            time.sleep(0.3)

        try:
            pred_eir = resp["raw"].get("every_item_required")
            results.append({
                "key": item.key,
                "label": item.label,
                "pred": pred_eir,
                "match": pred_eir == item.label,
                "source": item.source,
                "code": item.code,
            })
        except Exception as e:
            results.append({"key": item.key, "label": item.label,
                            "source": item.source, "error": str(e)})

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

    # Print false positives and false negatives
    for r in results:
        if r.get("pred") != r.get("label"):
            direction = "FN" if r.get("label") else "FP"
            print(f"  {direction}: {r['key']} (source={r.get('source')} code={r.get('code')})")


# ---------------------------------------------------------------------------
# Step 3: Generation-run rubric writing (needs LLM)
# ---------------------------------------------------------------------------

def step3_generation_run(client: LLMClient, config: Any, cache: dict) -> None:
    print(f"\n[Step 3] Generation-run rubric writing ({len(GENERATION_RUN_ITEMS)} items)")
    model = config.model_verify

    corpus_data: dict[str, Any] = {}
    for json_file in FS_DIR.rglob("*.json"):
        try:
            corpus_data[json_file.stem] = json.loads(json_file.read_text())
        except Exception:
            pass

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
            sq = next(
                (s for s in q.get("subquestions", []) if s.get("序號") == item.seq),
                None,
            )
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
                    model=model,
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

        rubric_2 = resp.get("raw", {}).get("rubric_level_2", "")
        has_fixed = EXTRA_ITEMS_FIXED_SENTENCE in rubric_2
        eir = resp.get("raw", {}).get("every_item_required", None)
        generated_rubrics.append({
            "key": item.key,
            "has_fixed_sentence": has_fixed,
            "every_item_required": eir,
        })

    if generated_rubrics:
        total = len(generated_rubrics)
        has_fixed = sum(1 for r in generated_rubrics if r["has_fixed_sentence"])
        eir_true = sum(1 for r in generated_rubrics if r["every_item_required"])
        print("\n[Step 3 results]")
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

    step1_extra_items_count()

    try:
        config = Config.from_env()
        client = LLMClient(config)
    except Exception as e:
        print(f"\n[WARN] Cannot initialize LLMClient: {e}")
        print("Steps 2 and 3 require API credits. Exiting.")
        return

    # Credit probe
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
            print(f"\n[WARN] API credit check failed: {err[:120]}")
            print("Steps 2 and 3 skipped — restore credits and rerun.")
            return

    cache = _load_cache(RESPONSES_873)
    print(f"\n[cache] Loaded {len(cache)} entries from {RESPONSES_873.name}")

    step2_eir_evaluation(client, config, cache)
    step3_generation_run(client, config, cache)
    print("\nDone.")


if __name__ == "__main__":
    main()
