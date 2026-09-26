"""
Research #872 — counting_stem flag and figure-framing route.

This script:
1. Applies the three #859 relabels to the #651 labelled set and saves the
   relabelled set alongside the original.
2. Re-runs the counting check on the relabelled set (reads the #651 cache
   first; LLM calls only for entries not yet cached).  Expected recall: 5/9.
3. Extends the criterion with a third output field `counting_stem` and runs it
   over a mixed corpus-plus-synthetic labelled set.  Reports the counting_stem
   confusion matrix.
4. Builds generated 題組-style items with rendered chart images attached the
   way the live verifier attaches them (multimodal message).  Reports a
   figure-route confusion matrix broken into three cases.
5. Caches every LLM response to JSONL under docs/research/872-…/responses.jsonl.

Design for #873 extensibility: the extended criterion JSON schema already has a
placeholder field `every_item_required` so the next run just flips the flag.

Run from the repo root:
    uv run python scripts/research/rubric_872_harness.py
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

from src.config import Config   # noqa: E402
from src.llm_client import LLMClient  # noqa: E402
from src.renderer import render_chart  # noqa: E402

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
OUT_651 = ROOT / "docs" / "research" / "651-counting-rubric-prototype"
OUT_872 = ROOT / "docs" / "research" / "872-counting-stem-figure-route"
OUT_872.mkdir(parents=True, exist_ok=True)

LABELLED_SET_ORIG = OUT_651 / "labelled_set.json"
LABELLED_SET_RELABELLED = OUT_651 / "labelled_set_relabelled.json"
RESPONSES_651 = OUT_651 / "responses.jsonl"
RESPONSES_872 = OUT_872 / "responses.jsonl"

# ---------------------------------------------------------------------------
# #859 relabels applied to the #651 labelled set
# Three changes (recorded in #859 resolution comment):
#   1. black-white-car-heat 5  : basis 圖表資料 → 題幹; contestable True → False
#   2. entomopathogenic-fungi 6: basis 圖表資料 → 題幹; contestable True → False
#   3. entomopathogenic-fungi 5: LEGAL → VIOLATES; basis 圖表資料 → 其他; contestable True → False
# ---------------------------------------------------------------------------

RELABELS_859: dict[tuple[str, int], dict] = {
    ("black-white-car-heat", 5): {
        "rule_c_framing_basis": "題幹",
        "rule_c_contestable": False,
        # verdict stays LEGAL
    },
    ("entomopathogenic-fungi", 6): {
        "rule_c_framing_basis": "題幹",
        "rule_c_contestable": False,
        # verdict stays LEGAL
    },
    ("entomopathogenic-fungi", 5): {
        "rule_c_verdict": "VIOLATES",
        "rule_c_framing_basis": "其他",
        "rule_c_contestable": False,
        "rule_c_reason": (
            "「研究員為何會提出這樣的質疑？」，[2] 要求兩個具體缺陷，"
            "成員集合只存在於答案欄，圖表只提供資料不決定成員（#859 FLIES Q2 型）"
        ),
    },
}

# ---------------------------------------------------------------------------
# Verifier system prompt (updated 【判準】 from #859 + counting_stem field)
# ---------------------------------------------------------------------------

VERIFIER_SYSTEM_V2 = """\
你是108課綱自然科學／社會領域素養導向命題的評分規準稽核員。
你的任務是判斷一道小題的評分規準是否違反下列「規則 C」，
同時判斷題目（小題）是否構成「計數式提問」（counting_stem），
以及 [2] 級距是否要求學生「所提的每一個項目皆…」（every_item_required）。

## 規則 C（完整條文，含 #859 修訂）

開放式建構反應題 / Constructed response 的評分規準必須依循以下規定：

  【禁止】不得以學生列舉的項目「數量」區分級距。

  【判準】要分辨是「完整度」還是「數量」，看該小題自身的題目敘述與所宣告的
  學習內容／科學能力，能否在事前把「完整答案的成分集合」框定下來：
  - 能框定 → 依補齊幾個成分分級為合法，且 [2] 必須逐一指名該集合的成員。
    （例：題目明寫「請從甲、乙兩個面向說明」；或該科學概念本身即由數個必要環節構成；
    或題目所指的圖表本身決定了成員——完整答案可直接從圖表讀出，任何人看圖即列出同一份清單。）
    以圖表框定時，[2] 須指明每個成員取自哪一張圖表（如「圖(一)」「附表」），
    且該成員須以該圖表上可見的標示出現（軸、欄、列、圖例或區域）。
  - 不能框定 → 不得依數量分級；[1] 必須以推理鏈條的缺口描述，
    不得寫成「僅提及其中之一」。
    （例：題目問「有什麼好處？」「請提出建議」，可接受的答案是一群開放、獨立的項目；
    或「研究員為何質疑？」這類須分析資料才能提出的項目——圖表只提供資料，不決定成員。）

  【注意】題幹指定的「數量」不等於框定「集合」。「請寫兩個結論」只固定了個數，
  並未固定是哪兩個，因此屬於不能框定。

  【具體性】評分規準說明必須指名本小題的內容——[2] 要寫出本題該答對什麼，
  [1] 要寫出本題最可能出現的缺口。不得使用「完整正確回答／部分正確／錯誤」
  這類可套用到任何題目的字樣。

## counting_stem（計數式提問）的定義

counting_stem 為 true，當且僅當：
  題目要求學生寫出**兩項以上**的答案，且答案的**完整集合無法事前框定**
  ——不論以數字（「請寫兩個結論」「至少列舉三項」）、以「有哪些」、
  或以「任 N 項」（N < 集合總數）提問。

以下情況 counting_stem 為 false（常見誤判，請特別注意）：
  1. 集合已由題幹文字逐一點名成員（如「優點與缺點」「甲、乙兩個面向」）。
  2. 集合由題目所指的圖表直接讀出（圖表固定成員）。
  3. 集合由科學概念的必要環節唯一決定。
  4. 「哪些」是針對文本／素材已列出的項目集合（文本供應集合，而非開放集合）。
  5. 題目只要求一項。
  6. 計數修飾的是**素材或情境**（「兩個烤箱」「三支試管」），不是要求的答案個數。

注意：
- 本規則僅適用於「Constructed response / 開放式建構反應題」。
- Complex multiple-choice 與 Simple multiple-choice 不受此規則約束。
"""

VERIFIER_USER_TEMPLATE_V2 = """\
請判斷以下小題的評分規準是否違反規則 C，並判斷是否構成計數式提問（counting_stem），
以及 [2] 級距是否要求學生所寫的每一項均須成立（every_item_required）。

題型：{question_type}
題目（小題）：
{question_stem}

學習內容：{learning_content}
科學能力：{science_ability}

評分規準各級距說明：
{rubric_text}

{figure_note}

## every_item_required 的定義

every_item_required 為 true，當且僅當：
  [2] 級距要求學生「所提的每一個項目」都成立
  ——使用「所提結論皆…」「所列理由都…」「每一項均…」等語句，
  即任何一個學生自行多寫的「錯誤額外項目」會讓學生降為 [1]。

every_item_required 為 false，當：
  - [2] 只要求本小題「事前指名的成員」均成立（如「兩個條件均提及」、「甲、乙兩個面向均正確」），
    學生自行多寫的額外項目不影響結果；或
  - [2] 不使用皆/均/都/全部等語句。

（請注意：「兩條件均提及」和「所提項目皆…」的差別：前者僅審查題目指定的成分，後者審查學生的全部作答。）

請嚴格依照規則 C 的【判準】邏輯逐步推理，然後以下列 JSON 格式輸出（不要輸出其他文字）：

{{
  "set_framed": <bool: 題幹或宣告的學習內容／科學能力／圖表，能否事前框定「完整答案的成分集合」>,
  "framing_evidence": "<str: 引用框定集合的文字，或說明無法框定的原因（限60字）>",
  "counting_violation": <bool: 評分規準依數量分級，且集合未被框定>,
  "counting_stem": <bool: 題目要求學生列出≥2項，且集合無法事前框定（見定義）>,
  "every_item_required": <bool: [2] 級距要求學生所寫的每一項均成立（見定義）>,
  "specificity_violation": <bool: 評分規準使用「完整正確回答／部分正確／錯誤」等空泛語句>,
  "verdict": "<pass 或 fail: counting_violation 或 specificity_violation 任一為 true 則 fail>",
  "details": "<str: verdict 為 fail 時，一句說明修正方向，以「[評分規準檢核]」開頭；pass 時輸出空字串>"
}}
"""

# Cache key prefix for the V2 criterion (with every_item_required).
# V1 = original #651 format (keys: {file_stem}|{item_idx}|{seq})
# V2 = this combined criterion (keys: v2|{file_stem}|{item_idx}|{seq})
# The counting_stem standalone criterion uses: counting_stem|{entry.key}
# These prefixes ensure previously-cached #651/#872 responses stay valid.
VERIFIER_V2_CACHE_PREFIX = "v2"

# ---------------------------------------------------------------------------
# counting_stem standalone criterion (for runs where we only need that field)
# ---------------------------------------------------------------------------

COUNTING_STEM_SYSTEM = """\
你是108課綱自然科學／社會領域素養導向命題的評分規準稽核員。
你的任務只有一件：判斷一道小題是否構成「計數式提問」（counting_stem）。

## 計數式提問的定義

counting_stem 為 true，當且僅當：
  題目要求學生寫出**兩項以上**的答案，且答案的**完整集合無法事前框定**
  ——不論以數字（「請寫兩個結論」「至少列舉三項」）、以「有哪些」、
  或以「任 N 項」（N < 集合總數）提問。

以下情況 counting_stem 為 false（常見誤判，請特別注意）：
  1. 集合已由題幹文字逐一點名成員（如「一個優點與一個缺點」「甲、乙兩個面向」）。
  2. 集合由題目所指的圖表直接讀出（任何人看圖即列出相同清單）。
  3. 集合由科學概念的必要環節唯一決定。
  4. 「哪些」是針對文本／素材已列出的固定項目（文本供應集合，非開放集合）。
     例：文本列出了三個因素，問「下列哪些因素屬於…？」
  5. 題目只要求一項（一個、一種）。
  6. 計數修飾的是**素材或情境**（如「兩個烤箱」「三支試管」「三位同學」），
     不是要求學生答出的項目個數。
  7. 題目明確逐一點名各項（「(1)…(2)…」「理由一與理由二」）。

判斷步驟：
  (A) 識別題目要求的答案項目個數是否 ≥ 2。
  (B) 若是，判斷答案集合是否可事前框定（依上列例外）。
  (C) 若無法框定，counting_stem = true；否則 false。
"""

COUNTING_STEM_USER_TEMPLATE = """\
題目：{question_stem}

學習內容（選填）：{learning_content}

{figure_note}

請依照定義判斷，只輸出 JSON（不要其他文字）：

{{
  "counting_stem": <bool>,
  "reason": "<str: 一句說明判斷依據（限50字）>"
}}
"""

# ---------------------------------------------------------------------------
# Figure-route criterion (multimodal)
# ---------------------------------------------------------------------------

FIGURE_VERIFIER_SYSTEM = """\
你是108課綱自然科學素養導向命題的評分規準稽核員。
你的任務是判斷一道有圖表附件的小題，其評分規準中的「以圖表框定集合」是否成立。

## 圖表框定的規則（#859 決議）

圖表框定集合，當且僅當：
  - 完整答案的所有成員可以直接從圖表讀出（任何人看圖即列出同一份清單），且
  - [2] 規準說明逐一點名每個成員並標明來源圖表，且
  - 每個成員在圖表上以可見標示出現（軸、欄、列、圖例或區域標籤）。

若圖表只提供資料（需要分析才能推論成員），不構成框定。
若 [2] 所宣告的成員在圖表上找不到可見標示，不構成框定。

## 輸出格式

請輸出 JSON（不要其他文字）：
{{
  "figure_frames_set": <bool: 圖表確實框定了該集合>,
  "members_visible_in_figure": <bool: [2] 所宣告的成員在圖表中均可見>,
  "read_off_or_analysis": "<'read_off' 或 'analysis'：完整答案是直接讀圖還是需要分析>",
  "verdict": "<'accept' 或 'reject'>",
  "reject_reason": "<若 reject，簡述原因；accept 時輸出空字串>"
}}
"""

FIGURE_VERIFIER_USER_TEMPLATE = """\
以下是一道有圖表附件的小題。請結合附上的圖表圖片，判斷評分規準中的圖表框定是否成立。

題型：Constructed response / 開放式建構反應題
題目（小題）：{question_stem}

評分規準 [2] 級距說明：
{rubric_level_2}

附圖說明：{figure_description}
"""

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def load_cache(path: Path) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    if not path.exists():
        return cache
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            key = rec.get("_key", "")
            # Migrate v1 keys (file_stem|seq) → v2 (file_stem|0|seq)
            parts = key.split("|")
            if len(parts) == 2:
                key = f"{parts[0]}|0|{parts[1]}"
                rec["_key"] = key
            if key:
                cache[key] = rec
        except Exception:
            pass
    return cache


def save_to_cache(path: Path, key: str, response: dict) -> None:
    record = {"_key": key, **response}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Step 1: Apply relabels + save relabelled set
# ---------------------------------------------------------------------------

def apply_relabels_859(orig_path: Path, out_path: Path) -> list[dict]:
    """Apply the three #859 relabels to the labelled set and save."""
    data = json.loads(orig_path.read_text(encoding="utf-8"))
    changed = 0
    for entry in data:
        key = (entry.get("file_stem", ""), entry.get("seq"))
        if key in RELABELS_859:
            patch = RELABELS_859[key]
            for field, value in patch.items():
                entry[field] = value
            changed += 1
    assert changed == 3, f"Expected 3 relabels, got {changed}"

    # Recompute derived fields: expected_pass and strict_expected_pass
    for entry in data:
        verdict = entry.get("rule_c_verdict")
        contestable = entry.get("rule_c_contestable", False)
        entry["expected_pass"] = (verdict != "VIOLATES")
        entry["strict_expected_pass"] = not (verdict == "VIOLATES" or contestable)

    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Saved relabelled set: {out_path}", file=sys.stderr)
    return data


# ---------------------------------------------------------------------------
# Step 2: Re-run counting check on relabelled set (cache-first)
# ---------------------------------------------------------------------------

def _build_651_user_prompt(entry: dict) -> str:
    """Build the user prompt using the ORIGINAL #651 criterion format."""
    template = """\
請判斷以下小題的評分規準是否違反規則 C。

題型：{question_type}
題目（題幹）：
{question_stem}

學習內容：{learning_content}
科學能力：{science_ability}

評分規準各級距說明：
{rubric_text}

請嚴格依照規則 C 的【判準】邏輯逐步推理，然後以下列 JSON 格式輸出（不要輸出其他文字）：

{{
  "set_framed": <bool: 題幹或宣告的學習內容／科學能力，能否事前框定「完整答案的成分集合」>,
  "framing_evidence": "<str: 引用題幹中框定集合的文字，或說明為何無法框定（限50字）>",
  "counting_violation": <bool: 評分規準依數量分級，且集合未被框定>,
  "specificity_violation": <bool: 評分規準使用「完整正確回答／部分正確／錯誤」等空泛語句>,
  "verdict": "<pass 或 fail: counting_violation 或 specificity_violation 任一為 true 則 fail>",
  "details": "<str: verdict 為 fail 時，一句說明修正方向，以「[評分規準檢核]」開頭，
    指示 corrector 如何改寫（不得說「計數少一點」）；verdict 為 pass 時輸出空字串>"
}}
"""
    return template.format(
        question_type=entry.get("question_type", ""),
        question_stem=(entry.get("question_stem", "") or "")[:600],
        learning_content=(entry.get("learning_content", "") or "")[:200],
        science_ability=(entry.get("science_ability", "") or "")[:200],
        rubric_text=(entry.get("rubric_text", "") or "")[:600],
    )


_651_SYSTEM = """\
你是108課綱自然科學／社會領域素養導向命題的評分規準稽核員。
你的任務是判斷一道小題的評分規準是否違反下列「規則 C」。

## 規則 C（完整條文）

開放式建構反應題 / Constructed response 的評分規準必須依循以下規定：

  【禁止】不得以學生列舉的項目「數量」區分級距。

  【判準】要分辨是「完整度」還是「數量」，看該小題自身的題目敘述與所宣告的
  學習內容／科學能力，能否在事前把「完整答案的成分集合」框定下來：
  - 能框定 → 依補齊幾個成分分級為合法，且 [2] 必須逐一指名該集合的成員。
    （例：題目明寫「請從甲、乙兩個面向說明」；或該科學概念本身即由數個必要環節構成；
    或題目所指的圖表本身決定了成員——完整答案可直接從圖表讀出，任何人看圖即列出同一份清單。）
    以圖表框定時，[2] 須指明每個成員取自哪一張圖表（如「圖(一)」「附表」），
    且該成員須以該圖表上可見的標示出現（軸、欄、列、圖例或區域）。
  - 不能框定 → 不得依數量分級；[1] 必須以推理鏈條的缺口描述，
    不得寫成「僅提及其中之一」。
    （例：題目問「有什麼好處？」「請提出建議」，可接受的答案是一群開放、獨立的項目；
    或「研究員為何質疑？」這類須分析資料才能提出的項目——圖表只提供資料，不決定成員。）

  【注意】題幹指定的「數量」不等於框定「集合」。「請寫兩個結論」只固定了個數，
  並未固定是哪兩個，因此屬於不能框定。

  【具體性】評分規準說明必須指名本小題的內容——[2] 要寫出本題該答對什麼，
  [1] 要寫出本題最可能出現的缺口。不得使用「完整正確回答／部分正確／錯誤」
  這類可套用到任何題目的字樣。

注意：
- 本規則僅適用於「Constructed response / 開放式建構反應題」。
- Complex multiple-choice 與 Simple multiple-choice 不受此規則約束。
"""


def run_651_recheck_on_relabelled(
    relabelled: list[dict],
    client: LLMClient,
    cache_651: dict[str, dict],
    new_cache_path: Path,
    rate_limit: float = 0.3,
) -> tuple[list[dict], int]:
    """Re-run the #651 counting criterion on the relabelled set.

    Reads from the #651 cache; makes new LLM calls only for entries
    that are not already cached (there should be none — all 257 were
    cached in the original run).  New calls go to the #872 responses file.

    The three relabelled entries keep their existing LLM results from the
    original run (the relabels change the label, not the cached model output).
    Returns the relabelled list with llm_* fields populated and call_count.
    """
    call_count = 0
    new_cache = load_cache(new_cache_path) if new_cache_path.exists() else {}

    for entry in relabelled:
        cache_key = f"{entry['file_stem']}|{entry.get('item_idx', 0)}|{entry['seq']}"
        # Try #651 cache first, then #872 cache
        rec = cache_651.get(cache_key) or new_cache.get(cache_key)
        if rec and "error" not in rec:
            entry["llm_set_framed"] = rec.get("set_framed")
            entry["llm_counting_violation"] = rec.get("counting_violation")
            entry["llm_specificity_violation"] = rec.get("specificity_violation")
            entry["llm_verdict"] = rec.get("verdict")
            entry["llm_details"] = rec.get("details", "")
            entry["llm_framing_evidence"] = rec.get("framing_evidence", "")
            continue

        # Entry not cached — make a new call
        prompt = _build_651_user_prompt(entry)
        try:
            result = client.generate_json(
                system=_651_SYSTEM,
                user=prompt,
                purpose="verify",
            )
            call_count += 1
            entry["llm_set_framed"] = result.get("set_framed")
            entry["llm_counting_violation"] = result.get("counting_violation")
            entry["llm_specificity_violation"] = result.get("specificity_violation")
            entry["llm_verdict"] = result.get("verdict")
            entry["llm_details"] = result.get("details", "")
            entry["llm_framing_evidence"] = result.get("framing_evidence", "")
            save_to_cache(new_cache_path, cache_key, result)
            if rate_limit > 0:
                time.sleep(rate_limit)
        except Exception as e:
            print(f"  [ERROR] {cache_key}: {e}", file=sys.stderr)
            entry["llm_verdict"] = None

    return relabelled, call_count


def compute_counting_recall_relabelled(relabelled: list[dict]) -> dict:
    """Compute counting-only recall on the 9 VIOLATES entries."""
    violates = [e for e in relabelled if e.get("rule_c_verdict") == "VIOLATES"]
    tp = [e for e in violates if e.get("llm_counting_violation") is True]
    fn = [e for e in violates if e.get("llm_counting_violation") is not True]
    # FP on LEGAL entries (counting-only)
    legal = [
        e for e in relabelled
        if e.get("rule_c_verdict") != "VIOLATES" and e.get("rule_c_verdict") is not None
    ]
    fp = [e for e in legal if e.get("llm_counting_violation") is True]
    tn = [e for e in legal if e.get("llm_counting_violation") is not True]

    return {
        "violates_count": len(violates),
        "tp": len(tp),
        "fn": len(fn),
        "fp_legal": len(fp),
        "tn_legal": len(tn),
        "tp_entries": [(e["file_stem"], e["seq"]) for e in tp],
        "fn_entries": [(e["file_stem"], e["seq"], e.get("llm_details")) for e in fn],
        "fp_entries": [(e["file_stem"], e["seq"]) for e in fp],
    }


# ---------------------------------------------------------------------------
# Step 3: counting_stem labelled set and run
# ---------------------------------------------------------------------------

@dataclass
class CountingStemEntry:
    """One entry in the counting_stem labelled set."""
    key: str
    question_stem: str
    learning_content: str = ""
    figure_note: str = ""      # non-empty when a figure is relevant
    # Ground-truth label (from the written rule; NOT derived from model output)
    label: bool = False        # True = counting_stem
    label_reason: str = ""
    category: str = ""         # "corpus_positive" | "synthetic_positive" | "corpus_negative" | "dangerous_fp"
    # LLM output
    llm_counting_stem: bool | None = None
    llm_reason: str = ""
    llm_raw: dict = dc_field(default_factory=dict)


# -- Labelling rule (written before any model output is seen) --
# counting_stem = True when:
#   The 小題 asks the student to produce ≥2 answer items from an OPEN set
#   (by numeral, 「至少N」, 「有哪些」, or 「任N項」 of a larger set).
# counting_stem = False when any of:
#   F1. Count describes the material/situation, not the answer items.
#   F2. Set is named member-by-member in the stem.
#   F3. Set is read directly off a figure the stem points to.
#   F4. Set is the scientifically necessary components of a concept.
#   F5. 「哪些」 over a set the material/passage already lists (closed set).
#   F6. Exactly one item requested.
#   F7. Named tuples: (1)…(2)… or 甲、乙 enumerated.


def build_counting_stem_labelled_set() -> list[CountingStemEntry]:
    """Build the counting_stem labelled set.

    Labels are derived from the written rule above (F1–F7),
    NOT from model verdicts.
    """
    entries: list[CountingStemEntry] = []

    # === Corpus positives (3 known, 1 to check) ===

    entries.append(CountingStemEntry(
        key="corpus|fasting-method|3",
        question_stem=(
            "請根據實驗結果寫出兩個結論。"
        ),
        learning_content="生命科學；斷食代謝研究",
        label=True,
        label_reason="「兩個結論」：個數固定但結論內容開放，集合無法事前框定（【注意】：數字≠集合）",
        category="corpus_positive",
    ))

    entries.append(CountingStemEntry(
        key="corpus|washing-machine-physics|5",
        question_stem=(
            "根據實驗數據，寫出影響洗衣機振動的因素（至少兩點，答兩點以上得分）。"
        ),
        learning_content="力學；洗衣機振動",
        label=True,
        label_reason="「至少兩點」且評分規準以個數分級，影響因素集合開放",
        category="corpus_positive",
    ))

    entries.append(CountingStemEntry(
        key="corpus|胡椒蛾的分子機制|3",
        question_stem=(
            "Hardy-Weinberg 平衡需要五個條件成立。若族群不符合 Hardy-Weinberg 平衡，"
            "請至少列舉三項可能原因。"
        ),
        learning_content="遺傳學；Hardy-Weinberg平衡",
        label=True,
        label_reason=(
            "「至少列舉三項」且科學概念有5個條件，要求任意3項——「任N項」型，集合未被全部框定"
        ),
        category="corpus_positive",
    ))

    entries.append(CountingStemEntry(
        key="corpus|wind-corridor-effect|1",
        question_stem=(
            "若要驗證「城市熱島效應中風廊道可降低溫度」的假說，"
            "你認為研究者需要進行哪些實驗？"
        ),
        learning_content="地球科學；城市熱島效應",
        label=True,
        label_reason=(
            "「哪些實驗」：實驗類型集合開放，題目或參考定義並未固定具體的實驗步驟清單"
        ),
        category="corpus_positive",
    ))

    # === Synthetic positives ===

    entries.append(CountingStemEntry(
        key="synth|open_count_any|1",
        question_stem=(
            "請列舉至少兩個溫室效應加劇的可能原因。"
        ),
        learning_content="",
        label=True,
        label_reason="「至少兩個」對開放集合（原因），集合無法事前框定",
        category="synthetic_positive",
    ))

    entries.append(CountingStemEntry(
        key="synth|open_count_any|2",
        question_stem=(
            "請寫出兩個影響海洋生物多樣性的人為因素。"
        ),
        learning_content="",
        label=True,
        label_reason="「兩個影響因素」對開放集合，個數固定但成員開放",
        category="synthetic_positive",
    ))

    entries.append(CountingStemEntry(
        key="synth|open_count_any|3",
        question_stem=(
            "根據文章，研究者對這個實驗的改進方法有哪些？請至少舉出兩點。"
        ),
        learning_content="",
        label=True,
        label_reason="「有哪些…至少兩點」：改進方法集合開放，文章未逐一列出",
        category="synthetic_positive",
    ))

    # === Dangerous false positives — corpus ===

    # F5: 「哪些」 over a set the material supplies
    entries.append(CountingStemEntry(
        key="dangerous_fp|truck-cornering|3",
        question_stem=(
            "卡車在彎道中有翻覆的危險，影響翻覆的因素包括：重心高度、速度、轉彎半徑、"
            "貨物偏移量。下列因素中哪些會增加翻覆的風險？（可複選）"
        ),
        learning_content="力學；卡車翻覆",
        label=False,
        label_reason="F5: 文本已列出四個固定因素，「哪些」針對已供應的封閉集合",
        category="dangerous_fp",
    ))

    entries.append(CountingStemEntry(
        key="dangerous_fp|乒乓球|3",
        question_stem=(
            "課文提到以下三種彈性碰撞的情境：正面碰撞、側面碰撞、旋轉碰撞。"
            "其中哪些會使乒乓球的速度增加？"
        ),
        learning_content="力學；彈性碰撞",
        label=False,
        label_reason="F5: 文本已列出三種固定情境，「哪些」針對已供應的封閉集合",
        category="dangerous_fp",
    ))

    entries.append(CountingStemEntry(
        key="dangerous_fp|蛙勒|4",
        question_stem=(
            "根據圖(三)，蛙勒在哪幾個月份的種類最多？"
        ),
        learning_content="生物；蛙類物候",
        figure_note="附圖(三)：各月份蛙種數長條圖，4、5、6月柱子最高",
        label=False,
        label_reason="F3: 月份集合由圖(三)直接讀出（讀圖型），任何人看圖即列出相同月份",
        category="dangerous_fp",
    ))

    # F1: counts that describe the material
    entries.append(CountingStemEntry(
        key="dangerous_fp|material_count|1",
        question_stem=(
            "實驗使用了兩個烤箱，分別設定為 200°C 和 250°C。"
            "請解釋為何較高溫度的烤箱中麵包膨脹更快。"
        ),
        learning_content="",
        label=False,
        label_reason="F1: 「兩個烤箱」描述素材，答案只要求一個解釋，不是要求列出兩項",
        category="dangerous_fp",
    ))

    entries.append(CountingStemEntry(
        key="dangerous_fp|material_count|2",
        question_stem=(
            "研究者依據數據做出三項推論。請評估這三項推論是否都有資料支持，並說明原因。"
        ),
        learning_content="",
        label=False,
        label_reason=(
            "F1: 「三項推論」是素材中已給定的固定三項，學生不需自行列出，"
            "而是針對已有的三項評估"
        ),
        category="dangerous_fp",
    ))

    # F6: count of one
    entries.append(CountingStemEntry(
        key="dangerous_fp|count_one|1",
        question_stem=(
            "請根據實驗結果提出一個改進建議，並說明理由。"
        ),
        learning_content="",
        label=False,
        label_reason="F6: 只要求一項，不在此限",
        category="dangerous_fp",
    ))

    entries.append(CountingStemEntry(
        key="dangerous_fp|count_one|2",
        question_stem=(
            "從上述實驗中，你認為最重要的一個控制變因是什麼？請說明。"
        ),
        learning_content="",
        label=False,
        label_reason="F6: 「最重要的一個」，只要求一項",
        category="dangerous_fp",
    ))

    # F2: named members in stem
    entries.append(CountingStemEntry(
        key="dangerous_fp|named_members|1",
        question_stem=(
            "二氧化碳的產生與改變可能和哪兩項因素的關係？"
            "請根據附圖說明光合作用速率與這兩項因素的關係。"
        ),
        learning_content="植物生理；光合作用",
        figure_note="附圖：x軸=光強度，y軸=CO2固定速率，有高溫/低溫兩條曲線",
        label=False,
        label_reason="F3: 圖表有兩個可見變數（光強度、溫度），由圖直接讀出，count = whole set",
        category="dangerous_fp",
    ))

    entries.append(CountingStemEntry(
        key="dangerous_fp|named_members|2",
        question_stem=(
            "請分別說明實驗組甲和實驗組乙的實驗結果，並比較兩者的差異。"
        ),
        learning_content="",
        label=False,
        label_reason="F2: 「甲」和「乙」已由題幹逐一點名，集合為 {甲, 乙}，已框定",
        category="dangerous_fp",
    ))

    # Named-member request corpus case: 二氧化碳的產生與改變 4
    entries.append(CountingStemEntry(
        key="dangerous_fp|corpus|二氧化碳的產生與改變|4",
        question_stem=(
            "根據上圖，分別說明光強度與溫度對光合作用速率的影響。"
            "（[2]: 正確說明光強度的影響，且正確說明溫度的影響）"
        ),
        learning_content="植物生理；光合作用速率",
        label=False,
        label_reason="F2: 「光強度與溫度」已由題幹逐一點名兩個成員，集合已框定",
        category="dangerous_fp",
    ))

    # === Synthetic negatives — non-corpus false-positive traps ===

    entries.append(CountingStemEntry(
        key="dangerous_fp|synth|named_pair",
        question_stem=(
            "請比較方法A和方法B的優缺點，並說明你更推薦哪一種方法。"
        ),
        learning_content="",
        label=False,
        label_reason="F2: 「方法A和方法B」已由題幹逐一點名，集合已框定",
        category="dangerous_fp",
    ))

    entries.append(CountingStemEntry(
        key="dangerous_fp|synth|scientific_necessity",
        question_stem=(
            "請說明生態系中能量流動的完整過程，包括生產者、消費者與分解者各自扮演的角色。"
        ),
        learning_content="生態學；能量流動",
        label=False,
        label_reason="F4: 「生產者、消費者、分解者」是生態系能量流動的必要環節，由科學概念唯一決定",
        category="dangerous_fp",
    ))

    entries.append(CountingStemEntry(
        key="dangerous_fp|synth|passage_supplies",
        question_stem=(
            "文章提到三種節能策略：LED照明、隔熱窗、太陽能板。"
            "請說明其中哪些策略適合在台灣的氣候條件下使用，並說明理由。"
        ),
        learning_content="",
        label=False,
        label_reason="F5: 文章已列出三種固定策略，「哪些」針對供應的封閉集合",
        category="dangerous_fp",
    ))

    # === Additional entries to ensure ≥3 per dangerous-FP category ===

    # F1 (material count) — third entry; conversions noted in label_reason
    entries.append(CountingStemEntry(
        key="dangerous_fp|material_count|3",
        question_stem=(
            "實驗組使用了三支試管，分別裝入不同濃度的葡萄糖溶液。"
            "請說明濃度最高的試管中細胞滲透壓的變化。"
        ),
        learning_content="",
        label=False,
        label_reason=(
            "F1: 「三支試管」描述素材中已給的試管數量；"
            "答案只要求一個說明（滲透壓變化），不是要求學生列出三項。"
            "轉換後若題目改問各試管的差異，才需逐一點名（甲管…乙管…丙管…）。"
        ),
        category="dangerous_fp",
    ))

    # F6 (count of one) — third entry
    entries.append(CountingStemEntry(
        key="dangerous_fp|count_one|3",
        question_stem=(
            "從圖中選取一個最能支持你的論點的數據，並說明該數據如何支持你的推論。"
        ),
        learning_content="",
        label=False,
        label_reason=(
            "F6: 「一個數據」，只要求學生列出一項，不在計數式提問的禁止範圍內。"
        ),
        category="dangerous_fp",
    ))

    # F5 — fourth 「哪些」 entry: question over a materially-supplied closed set
    entries.append(CountingStemEntry(
        key="dangerous_fp|material_supplied_set|1",
        question_stem=(
            "下列五種元素：C、H、O、N、P，哪些是構成蛋白質的基本元素？（可複選）"
        ),
        learning_content="",
        label=False,
        label_reason=(
            "F5: 題目已列出五種固定選項（C、H、O、N、P），「哪些」針對已供應的封閉集合，"
            "學生是從給定集合中選擇，不是從開放集合中自行產出。"
        ),
        category="dangerous_fp",
    ))

    # === Synthetic positives with conversion notes ===
    # These make the positive corpus more robust and document the standard conversion.

    entries.append(CountingStemEntry(
        key="synth|open_count_any|4",
        question_stem=(
            "請說明基因突變對生物進化的影響，至少列舉兩項可能的結果。"
        ),
        learning_content="",
        label=True,
        label_reason=(
            "「至少兩項可能的結果」對開放集合（突變結果），集合無法事前框定。"
            "轉換方式：改為「請說明基因突變對生物進化的一項影響，並以此說明其進化意義」"
            "（只要求一項），或改為「請說明基因突變如何分別影響適應性和遺傳多樣性（甲、乙兩個面向）」"
            "（逐一點名）。"
        ),
        category="synthetic_positive",
    ))

    entries.append(CountingStemEntry(
        key="synth|open_count_any|5",
        question_stem=(
            "根據實驗數據，請提出兩個改善實驗設計的建議，並說明各建議的理由。"
        ),
        learning_content="",
        label=True,
        label_reason=(
            "「兩個改善建議」對開放集合，個數固定但成員開放，集合無法事前框定。"
            "轉換方式：改為「請提出一個改善實驗設計的建議，並說明理由」（只要求一項），"
            "或改為「請針對缺少對照組和未控制溫度變因這兩個問題各提出一項改善方案」（逐一點名）。"
        ),
        category="synthetic_positive",
    ))

    return entries


def run_counting_stem_criterion(
    entries: list[CountingStemEntry],
    client: LLMClient,
    cache_path: Path,
    rate_limit: float = 0.3,
) -> tuple[list[CountingStemEntry], int]:
    cache = load_cache(cache_path)
    call_count = 0

    for entry in entries:
        cache_key = f"counting_stem|{entry.key}"
        rec = cache.get(cache_key)
        if rec and "error" not in rec:
            entry.llm_counting_stem = rec.get("counting_stem")
            entry.llm_reason = rec.get("reason", "")
            entry.llm_raw = rec
            continue

        prompt = COUNTING_STEM_USER_TEMPLATE.format(
            question_stem=entry.question_stem,
            learning_content=entry.learning_content or "（未指定）",
            figure_note=f"附圖資訊：{entry.figure_note}" if entry.figure_note else "",
        )
        try:
            result = client.generate_json(
                system=COUNTING_STEM_SYSTEM,
                user=prompt,
                purpose="verify",
            )
            call_count += 1
            entry.llm_counting_stem = result.get("counting_stem")
            entry.llm_reason = result.get("reason", "")
            entry.llm_raw = result
            save_to_cache(cache_path, cache_key, result)
        except Exception as e:
            print(f"  [ERROR] {cache_key}: {e}", file=sys.stderr)
            entry.llm_counting_stem = None
            entry.llm_raw = {"error": str(e)}
            save_to_cache(cache_path, cache_key, {"error": str(e)})

        if rate_limit > 0:
            time.sleep(rate_limit)

    return entries, call_count


def compute_counting_stem_matrix(entries: list[CountingStemEntry]) -> dict:
    """Compute confusion matrix for counting_stem."""
    tp = [e for e in entries if e.label is True and e.llm_counting_stem is True]
    fn = [e for e in entries if e.label is True and e.llm_counting_stem is not True]
    fp = [e for e in entries if e.label is False and e.llm_counting_stem is True]
    tn = [e for e in entries if e.label is False and e.llm_counting_stem is not True]
    errors = [e for e in entries if e.llm_counting_stem is None]
    return {
        "total": len(entries),
        "tp": len(tp), "fn": len(fn), "fp": len(fp), "tn": len(tn),
        "errors": len(errors),
        "tp_entries": [(e.key, e.question_stem[:50]) for e in tp],
        "fn_entries": [(e.key, e.question_stem[:50], e.llm_reason) for e in fn],
        "fp_entries": [(e.key, e.question_stem[:50], e.llm_reason) for e in fp],
    }


# ---------------------------------------------------------------------------
# Step 4: Figure route
# ---------------------------------------------------------------------------

@dataclass
class FigureRouteEntry:
    """One item for the figure-route test."""
    key: str
    question_stem: str
    rubric_level_2: str
    figure_description: str
    chart_spec: dict           # passed to render_chart
    image_path: Path | None = None   # set after rendering
    # Ground-truth label
    case: str = ""             # "read_off" | "supplies_data" | "absent_members"
    expected_verdict: str = ""  # "accept" | "reject"
    label_reason: str = ""
    # LLM output
    llm_figure_frames_set: bool | None = None
    llm_members_visible: bool | None = None
    llm_read_off_or_analysis: str = ""
    llm_verdict: str = ""
    llm_reject_reason: str = ""
    llm_raw: dict = dc_field(default_factory=dict)


def build_figure_route_items(image_dir: Path) -> list[FigureRouteEntry]:
    """Build generated 題組-style items with chart images.

    Matched pairs on the same rendered chart:
    - read_off: the chart fixes the members → accept
    - supplies_data: the chart only supplies data → reject
    Plus negatives where [2] claims members absent from the figure → reject.
    """
    image_dir.mkdir(parents=True, exist_ok=True)
    items: list[FigureRouteEntry] = []

    # --- Chart A: bar chart (4 experiment groups labeled 甲乙丙丁) ---
    chart_a_spec = {
        "render_mode": "chart",
        "chart_type": "histogram",
        "title": "四組實驗的溫度變化（°C）",
        "data": {
            "bins": ["甲", "乙", "丙", "丁"],
            "counts": [12, 8, 15, 5],
        },
        "labels": {"x": "實驗組", "y": "溫度變化（°C）"},
    }

    # A1: read-off — asks which group had the highest temperature change
    items.append(FigureRouteEntry(
        key="fig|chart_A|read_off",
        question_stem=(
            "根據圖(一)，哪個實驗組的溫度變化最大，哪個最小？"
            "請各列出一組，並說明你是如何從圖中判斷的。"
        ),
        rubric_level_2=(
            "[2] 能正確指出圖(一)中溫度變化最大的組別為丙組（15°C）且最小的為丁組（5°C），"
            "並說明是依柱狀圖高度判斷。學生多寫的其他項目不影響評分，"
            "但若與得分的作答矛盾，最高給 [1]。"
        ),
        figure_description="圖(一)：四個實驗組（甲、乙、丙、丁）的溫度變化長條圖，各組高度清晰可讀",
        chart_spec=chart_a_spec,
        case="read_off",
        expected_verdict="accept",
        label_reason=(
            "圖表直接顯示四組的高度值，任何人看圖即讀出丙最高丁最低；"
            "[2] 指名了圖(一)及兩個成員，均在圖上有可見標示"
        ),
    ))

    # A2: supplies-data — uses the same chart but asks why, which requires analysis
    items.append(FigureRouteEntry(
        key="fig|chart_A|supplies_data",
        question_stem=(
            "根據圖(一)的數據，請分析造成各實驗組溫度差異的可能原因，"
            "並提出兩個合理的假設。"
        ),
        rubric_level_2=(
            "[2] 能提出兩個合理的科學假設說明溫度差異的原因（例如：實驗組丙使用了不同的催化劑"
            "和較高的起始濃度），每個假設都有邏輯依據。"
            "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
        ),
        figure_description="圖(一)：四個實驗組（甲、乙、丙、丁）的溫度變化長條圖",
        chart_spec=chart_a_spec,
        case="supplies_data",
        expected_verdict="reject",
        label_reason=(
            "圖表只提供各組數值，「原因」需要分析推論；"
            "且[2]要求「兩個合理假設」，假設集合開放，圖表不決定成員"
        ),
    ))

    # --- Chart B: bar chart (3 groups, day-5 survival rates) ---
    # Note: _render_line_chart does not support the "series" key format;
    # switched to histogram so the data actually renders on screen.
    chart_b_spec = {
        "render_mode": "chart",
        "chart_type": "histogram",
        "title": "三種處理方式第5天細胞存活率（%）",
        "data": {
            "bins": ["處理A", "處理B", "處理C"],
            "counts": [30, 62, 25],
        },
        "labels": {"x": "處理方式", "y": "第5天細胞存活率（%）"},
    }

    # B1: read-off — asks which treatment had best and worst survival
    items.append(FigureRouteEntry(
        key="fig|chart_B|read_off",
        question_stem=(
            "根據圖(二)，哪種處理方式在第5天的細胞存活率最高，哪種最低？"
        ),
        rubric_level_2=(
            "[2] 正確指出圖(二)中存活率最高的是處理B（62%），最低的是處理C（25%），"
            "兩者均從圖(二)的長條讀出。"
            "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
        ),
        figure_description="圖(二)：三種處理方式（處理A、B、C）在第5天的細胞存活率長條圖，各長條均有標示數值",
        chart_spec=chart_b_spec,
        case="read_off",
        expected_verdict="accept",
        label_reason=(
            "各長條的數值直接從圖讀出；[2]指名圖(二)及兩個成員（處理B、處理C），"
            "均在長條上有可見標示"
        ),
    ))

    # B2: supplies-data — asks what caused the difference, which requires analysis
    items.append(FigureRouteEntry(
        key="fig|chart_B|supplies_data",
        question_stem=(
            "根據圖(二)的數據，請分析存活率最低的兩種處理方式可能的共同原因。"
        ),
        rubric_level_2=(
            "[2] 能正確識別存活率較低的處理方式（如A和C），並提供合理的生物學解釋"
            "（例：兩者可能干擾了細胞的抗氧化系統和粒線體功能）。"
            "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
        ),
        figure_description="圖(二)：三種處理方式第5天細胞存活率長條圖",
        chart_spec=chart_b_spec,
        case="supplies_data",
        expected_verdict="reject",
        label_reason=(
            "[2]要求分析「共同原因」，原因集合開放，圖表只提供數值不決定原因；"
            "且[2]所列的「抗氧化系統和粒線體功能」在圖上無可見標示"
        ),
    ))

    # --- Chart C: bar chart (2 temperature conditions, peak photosynthesis rate) ---
    # Note: _render_line_chart does not support the "series" key format;
    # switched to histogram so the data actually renders on screen.
    chart_c_spec = {
        "render_mode": "chart",
        "chart_type": "histogram",
        "title": "高溫與低溫下的最高光合速率比較",
        "data": {
            "bins": ["高溫（35°C）", "低溫（15°C）"],
            "counts": [20, 13],
        },
        "labels": {"x": "溫度條件", "y": "最高光合速率（μmol CO₂/m²/s）"},
    }

    # C1: read-off — figure has exactly 2 visible series; question asks about both
    items.append(FigureRouteEntry(
        key="fig|chart_C|read_off",
        question_stem=(
            "根據圖(三)，高溫和低溫哪種溫度條件下光合速率更高？"
            "請說明你從圖(三)中如何判斷。"
        ),
        rubric_level_2=(
            "[2] 正確說明圖(三)中高溫（35°C）的最高光合速率（20）高於低溫（15°C）的最高光合速率（13）；"
            "兩個成員（高溫、低溫）均取自圖(三)的長條標示。"
            "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
        ),
        figure_description="圖(三)：兩個溫度條件（高溫35°C、低溫15°C）的最高光合速率長條圖，各長條均有數值標示",
        chart_spec=chart_c_spec,
        case="read_off",
        expected_verdict="accept",
        label_reason=(
            "圖上恰好有兩個長條（高溫、低溫），集合等於全部成員；"
            "[2]指名圖(三)及兩個成員，均以長條標示形式可見"
        ),
    ))

    # C2: absent members — [2] claims a third condition "中溫" not in the chart → reject
    items.append(FigureRouteEntry(
        key="fig|chart_C|absent_members",
        question_stem=(
            "根據圖(三)，說明高溫、低溫和中溫三種條件下光合作用速率的差異。"
        ),
        rubric_level_2=(
            "[2] 正確說明圖(三)中高溫（35°C）速率最高（20），中溫（25°C）次之（約16），低溫（15°C）最低（13）；"
            "三個成員（高溫、中溫、低溫）均取自圖(三)。"
            "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
        ),
        figure_description="圖(三)：兩個長條（高溫35°C、低溫15°C），無中溫長條",
        chart_spec=chart_c_spec,
        case="absent_members",
        expected_verdict="reject",
        label_reason=(
            "「中溫（25°C）」不在圖(三)上，[2]宣告的成員有一個在圖表上無可見標示"
        ),
    ))

    # --- Chart D: pie chart (3 segments) ---
    chart_d_spec = {
        "render_mode": "chart",
        "chart_type": "pie_chart",
        "title": "校園廢棄物組成比例",
        "data": {
            "segments": [
                {"label": "廚餘 45%", "angle": 162},
                {"label": "紙類 30%", "angle": 108},
                {"label": "塑膠 25%", "angle": 90},
            ]
        },
        "labels": {},
    }

    # D1: read-off — 3 labeled segments, question asks for all 3
    items.append(FigureRouteEntry(
        key="fig|chart_D|read_off",
        question_stem=(
            "根據圖(四)，校園廢棄物由哪三種類型組成？各佔多少比例？"
        ),
        rubric_level_2=(
            "[2] 正確列出圖(四)的三種廢棄物類型：廚餘（45%）、紙類（30%）、塑膠（25%），"
            "三者均取自圖(四)的扇形標示。"
            "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
        ),
        figure_description="圖(四)：圓餅圖，三個扇形分別標示「廚餘45%」「紙類30%」「塑膠25%」",
        chart_spec=chart_d_spec,
        case="read_off",
        expected_verdict="accept",
        label_reason=(
            "三個扇形有明確標示，count = whole set；"
            "[2]指名圖(四)及三個成員，均在扇形標示上可見"
        ),
    ))

    # D2: supplies-data — asks about environmental impact (analysis, not read-off)
    items.append(FigureRouteEntry(
        key="fig|chart_D|supplies_data",
        question_stem=(
            "根據圖(四)，請說明校園廢棄物對環境的主要影響，"
            "並提出兩項最有效的減量策略。"
        ),
        rubric_level_2=(
            "[2] 能針對廚餘和塑膠各提出一項具體且可行的減量策略"
            "（廚餘：設置廚餘桶進行堆肥；塑膠：禁止一次性塑膠用品），"
            "並說明各策略對環境的改善效果。"
            "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
        ),
        figure_description="圖(四)：廢棄物組成圓餅圖（廚餘45%、紙類30%、塑膠25%）",
        chart_spec=chart_d_spec,
        case="supplies_data",
        expected_verdict="reject",
        label_reason=(
            "「兩項減量策略」需要分析推論，策略集合開放；"
            "圖表只顯示比例，不決定哪些策略有效"
        ),
    ))

    # D3: absent members — claims a 4th category not in the chart → reject
    items.append(FigureRouteEntry(
        key="fig|chart_D|absent_members",
        question_stem=(
            "根據圖(四)，請列出校園廢棄物的主要類型，包括廚餘、紙類、塑膠和金屬。"
        ),
        rubric_level_2=(
            "[2] 正確列出廚餘（45%）、紙類（30%）、塑膠（25%）和金屬（5%）四種廢棄物，"
            "均來自圖(四)。"
            "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
        ),
        figure_description="圖(四)：三個扇形（廚餘、紙類、塑膠），無金屬扇形",
        chart_spec=chart_d_spec,
        case="absent_members",
        expected_verdict="reject",
        label_reason=(
            "「金屬（5%）」在圖(四)上無可見標示，[2]宣告的成員之一不在圖表上"
        ),
    ))

    return items


def render_figure_route_images(items: list[FigureRouteEntry], image_dir: Path) -> None:
    """Render PNG images for each unique chart spec."""
    rendered: dict[str, Path] = {}
    for item in items:
        chart_key = item.key.split("|")[1]  # e.g. "chart_A"
        if chart_key not in rendered:
            img_path = image_dir / f"fig_{chart_key}.png"
            result = render_chart(item.chart_spec, img_path)
            if result:
                rendered[chart_key] = img_path
                print(f"  Rendered: {img_path}", file=sys.stderr)
            else:
                print(f"  [WARN] render_chart returned None for {chart_key}", file=sys.stderr)
        item.image_path = rendered.get(chart_key)


def run_figure_route_criterion(
    items: list[FigureRouteEntry],
    client: LLMClient,
    cache_path: Path,
    rate_limit: float = 0.3,
) -> tuple[list[FigureRouteEntry], int]:
    cache = load_cache(cache_path)
    call_count = 0

    for item in items:
        cache_key = f"fig_route|{item.key}"
        rec = cache.get(cache_key)
        if rec and "error" not in rec:
            item.llm_figure_frames_set = rec.get("figure_frames_set")
            item.llm_members_visible = rec.get("members_visible_in_figure")
            item.llm_read_off_or_analysis = rec.get("read_off_or_analysis", "")
            item.llm_verdict = rec.get("verdict", "")
            item.llm_reject_reason = rec.get("reject_reason", "")
            item.llm_raw = rec
            continue

        prompt = FIGURE_VERIFIER_USER_TEMPLATE.format(
            question_stem=item.question_stem,
            rubric_level_2=item.rubric_level_2,
            figure_description=item.figure_description,
        )

        images: list[Path] | None = None
        if item.image_path and item.image_path.exists():
            images = [item.image_path]

        try:
            result = client.generate_json(
                system=FIGURE_VERIFIER_SYSTEM,
                user=prompt,
                images=images,
                purpose="verify",
            )
            call_count += 1
            item.llm_figure_frames_set = result.get("figure_frames_set")
            item.llm_members_visible = result.get("members_visible_in_figure")
            item.llm_read_off_or_analysis = result.get("read_off_or_analysis", "")
            item.llm_verdict = result.get("verdict", "")
            item.llm_reject_reason = result.get("reject_reason", "")
            item.llm_raw = result
            save_to_cache(cache_path, cache_key, result)
        except Exception as e:
            print(f"  [ERROR] {cache_key}: {e}", file=sys.stderr)
            item.llm_raw = {"error": str(e)}
            save_to_cache(cache_path, cache_key, {"error": str(e)})

        if rate_limit > 0:
            time.sleep(rate_limit)

    return items, call_count


def compute_figure_route_matrix(items: list[FigureRouteEntry]) -> dict:
    """Compute figure-route confusion matrix, broken out by case."""
    cases = ["read_off", "supplies_data", "absent_members"]
    result: dict[str, Any] = {}
    for case in cases:
        subset = [i for i in items if i.case == case]
        correct = [i for i in subset if i.llm_verdict == i.expected_verdict]
        wrong = [i for i in subset if i.llm_verdict != i.expected_verdict and i.llm_verdict]
        errors = [i for i in subset if not i.llm_verdict]
        result[case] = {
            "total": len(subset),
            "correct": len(correct),
            "wrong": len(wrong),
            "errors": len(errors),
            "correct_entries": [(i.key, i.llm_verdict) for i in correct],
            "wrong_entries": [(i.key, i.expected_verdict, i.llm_verdict, i.llm_reject_reason) for i in wrong],
        }
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    config = Config.from_env()
    client = LLMClient(config)
    model_id = config.model_verify or config.model_execute
    rate_limit = max(config.rate_limit_delay, 0.3)
    print(f"\n=== Model: {model_id} | rate_limit: {rate_limit}s ===", file=sys.stderr)

    total_calls = 0

    # ------------------------------------------------------------------
    # Step 1: Apply relabels
    # ------------------------------------------------------------------
    print("\n[Step 1] Applying #859 relabels...", file=sys.stderr)
    relabelled = apply_relabels_859(LABELLED_SET_ORIG, LABELLED_SET_RELABELLED)
    violates = [e for e in relabelled if e.get("rule_c_verdict") == "VIOLATES"]
    print(f"  VIOLATES after relabels: {len(violates)} (expected 9)", file=sys.stderr)

    # ------------------------------------------------------------------
    # Step 2: Re-run counting check on relabelled set
    # ------------------------------------------------------------------
    print("\n[Step 2] Re-running counting check on relabelled set...", file=sys.stderr)
    cache_651 = load_cache(RESPONSES_651)
    print(f"  #651 cache size: {len(cache_651)} entries", file=sys.stderr)

    relabelled, calls_step2 = run_651_recheck_on_relabelled(
        relabelled, client, cache_651, RESPONSES_872, rate_limit
    )
    total_calls += calls_step2
    print(f"  New LLM calls in step 2: {calls_step2}", file=sys.stderr)

    recall_data = compute_counting_recall_relabelled(relabelled)
    print(f"\n  Relabelled set counting-only recall:", file=sys.stderr)
    print(f"    TP={recall_data['tp']} / {recall_data['violates_count']} VIOLATES", file=sys.stderr)
    print(f"    FN entries:", file=sys.stderr)
    for fn_item in recall_data["fn_entries"]:
        print(f"      {fn_item[0]} seq={fn_item[1]}: {str(fn_item[2])[:80]}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Step 3: counting_stem
    # ------------------------------------------------------------------
    print("\n[Step 3] Building counting_stem labelled set and running criterion...", file=sys.stderr)
    cs_entries = build_counting_stem_labelled_set()
    positives = [e for e in cs_entries if e.label]
    negatives = [e for e in cs_entries if not e.label]
    print(f"  Entries: {len(cs_entries)} total ({len(positives)} positive, {len(negatives)} negative)", file=sys.stderr)

    cs_entries, calls_step3 = run_counting_stem_criterion(
        cs_entries, client, RESPONSES_872, rate_limit
    )
    total_calls += calls_step3
    print(f"  New LLM calls in step 3: {calls_step3}", file=sys.stderr)

    cs_matrix = compute_counting_stem_matrix(cs_entries)

    # ------------------------------------------------------------------
    # Step 4: Figure route
    # ------------------------------------------------------------------
    print("\n[Step 4] Building figure-route items and running criterion...", file=sys.stderr)
    image_dir = OUT_872 / "images"
    fig_items = build_figure_route_items(image_dir)
    render_figure_route_images(fig_items, image_dir)

    fig_items, calls_step4 = run_figure_route_criterion(
        fig_items, client, RESPONSES_872, rate_limit
    )
    total_calls += calls_step4
    print(f"  New LLM calls in step 4: {calls_step4}", file=sys.stderr)

    fig_matrix = compute_figure_route_matrix(fig_items)

    # ------------------------------------------------------------------
    # Print results
    # ------------------------------------------------------------------
    print("\n\n========== RESULTS ==========")
    print(f"Model: {model_id}  effort_verify={config.effort_verify}")
    print(f"Total new LLM calls: {total_calls}")

    print("\n--- Step 2: Relabelled #651 counting recall (counting-only) ---")
    print(f"  VIOLATES: {recall_data['violates_count']}")
    print(f"  TP (caught): {recall_data['tp']}  FN (missed): {recall_data['fn']}")
    print(f"  FP on LEGAL: {recall_data['fp_legal']}  TN: {recall_data['tn_legal']}")
    tp = recall_data['tp']
    total_v = recall_data['violates_count']
    print(f"  Recall: {tp}/{total_v} = {tp/total_v:.1%}" if total_v else "  n/a")
    print(f"  TP entries: {recall_data['tp_entries']}")
    print("  FN details:")
    for fn in recall_data["fn_entries"]:
        print(f"    {fn[0]} seq={fn[1]}: {str(fn[2])[:100]}")

    print("\n--- Step 3: counting_stem confusion matrix ---")
    cs = cs_matrix
    print(f"  Total: {cs['total']}  TP={cs['tp']}  FN={cs['fn']}  FP={cs['fp']}  TN={cs['tn']}  Err={cs['errors']}")
    if cs['tp'] + cs['fn']:
        print(f"  Recall: {cs['tp']}/{cs['tp']+cs['fn']} = {cs['tp']/(cs['tp']+cs['fn']):.1%}")
    if cs['fp'] + cs['tn']:
        print(f"  FPR:    {cs['fp']}/{cs['fp']+cs['tn']} = {cs['fp']/(cs['fp']+cs['tn']):.1%}")
    if cs['fn_entries']:
        print("  FN (missed positives):")
        for e in cs['fn_entries']:
            print(f"    key={e[0]}: {e[1]} | model_reason={e[2]}")
    if cs['fp_entries']:
        print("  FP (false alarms):")
        for e in cs['fp_entries']:
            print(f"    key={e[0]}: {e[1]} | model_reason={e[2]}")

    print("\n--- Step 4: Figure-route confusion matrix ---")
    for case in ["read_off", "supplies_data", "absent_members"]:
        m = fig_matrix[case]
        print(f"  {case}: {m['correct']}/{m['total']} correct")
        if m["wrong_entries"]:
            for e in m["wrong_entries"]:
                print(f"    WRONG key={e[0]}: expected={e[1]} got={e[2]} reason={e[3]}")

    # ------------------------------------------------------------------
    # Save run summary JSON
    # ------------------------------------------------------------------
    summary = {
        "model": model_id,
        "effort_verify": config.effort_verify,
        "total_llm_calls": total_calls,
        "cache_651_size": len(cache_651),
        "relabelled_recall": {
            "tp": recall_data["tp"],
            "fn": recall_data["fn"],
            "total_violates": recall_data["violates_count"],
        },
        "counting_stem_matrix": {
            k: cs_matrix[k] for k in ["total", "tp", "fn", "fp", "tn", "errors"]
        },
        "figure_route_matrix": {
            case: {k: fig_matrix[case][k] for k in ["total", "correct", "wrong", "errors"]}
            for case in fig_matrix
        },
        "counting_stem_entries": [
            {
                "key": e.key,
                "category": e.category,
                "label": e.label,
                "llm_counting_stem": e.llm_counting_stem,
                "llm_reason": e.llm_reason,
                "question_stem": e.question_stem[:80],
            }
            for e in cs_entries
        ],
        "figure_route_entries": [
            {
                "key": item.key,
                "case": item.case,
                "expected_verdict": item.expected_verdict,
                "llm_verdict": item.llm_verdict,
                "llm_figure_frames_set": item.llm_figure_frames_set,
                "llm_members_visible": item.llm_members_visible,
                "llm_read_off_or_analysis": item.llm_read_off_or_analysis,
                "llm_reject_reason": item.llm_reject_reason,
            }
            for item in fig_items
        ],
    }
    summary_path = OUT_872 / "run_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Summary saved: {summary_path}", file=sys.stderr)

    print("\nDone.")


if __name__ == "__main__":
    main()
