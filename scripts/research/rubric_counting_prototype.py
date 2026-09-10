"""
Research #651 — 計數式規準 verifier criterion prototype (v2).

Loads all 257 rubric-bearing 小題 from ALL three NS directories, classifies
OUT_OF_SCOPE_C3 by 題型 (never by directory), attaches #648 labels, applies
manual 規則 C relabels (with framing_basis + contestable fields) for the 38
CLEAR+BORDERLINE entries, runs an LLM criterion over every entry (with JSONL
caching for crash-recovery), and prints per-bucket confusion matrices under
both the original labeling and the strict labeling (contestable → VIOLATES).

Run from the repo root (worktree):
    uv run python scripts/research/rubric_counting_prototype.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.config import Config  # noqa: E402
from src.llm_client import LLMClient  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_NS = ROOT / "data" / "natural_sciences" / "few_shot"
DATA_NS_CR = DATA_NS / "Constructed-response"
DATA_NS_CMC = DATA_NS / "Complex-multiple-choice"
DATA_NS_SMC = DATA_NS / "Simple-multiple-choice"
DATA_SS_CSV = (
    ROOT / "data" / "social_studies" / "few_shot" / "範例_few_shot_examples.csv"
)

OUT_DIR = ROOT / "docs" / "research" / "651-counting-rubric-prototype"
OUT_DIR.mkdir(parents=True, exist_ok=True)
LABELLED_SET_PATH = OUT_DIR / "labelled_set.json"
RESPONSES_PATH = OUT_DIR / "responses.jsonl"

# Bucket labels
CLEAR = "CLEAR"
BORDERLINE = "BORDERLINE"
CONFORMING = "CONFORMING"
OUT_OF_SCOPE_C3 = "OUT_OF_SCOPE_C3"

# 規則 C verdict labels
VIOLATES = "VIOLATES"
LEGAL = "LEGAL"
PASS = "pass"
FAIL = "fail"


def _is_oos(question_type: str) -> bool:
    """C3: out-of-scope if 題型 is Complex/Simple multiple-choice."""
    return "Complex multiple-choice" in question_type or \
           "Simple multiple-choice" in question_type or \
           "選擇" in question_type


def _is_constructed_response(question_type: str) -> bool:
    return "Constructed" in question_type or "開放式" in question_type


# ---------------------------------------------------------------------------
# #648 labels — (filename_stem, seq) → CLEAR or BORDERLINE
# (everything else determined by 題型 at load time)
# ---------------------------------------------------------------------------

AUDIT_648_LABELS: dict[tuple[str, int], str] = {
    # CLEAR COUNT (17)
    ("entomopathogenic-fungi", 2): CLEAR,
    ("entomopathogenic-fungi", 3): CLEAR,
    ("seawater-vertical-properties", 2): CLEAR,
    ("二氧化碳的產生與改變", 1): CLEAR,
    ("反應速率", 1): CLEAR,
    ("大氣能見度", 1): CLEAR,
    ("大氣能見度", 3): CLEAR,
    ("拉塞福散射", 2): CLEAR,
    ("果凍", 5): CLEAR,
    ("生物防治2-1", 1): CLEAR,
    ("生物防治2-1", 3): CLEAR,
    ("生物防治2-1", 5): CLEAR,
    ("筆芯電阻", 1): CLEAR,
    ("胡椒蛾的分子機制", 3): CLEAR,
    ("蛙勒", 4): CLEAR,
    ("運動與健康-糖尿病患者的健康生活", 3): CLEAR,
    ("隕石探究", 6): CLEAR,
    # BORDERLINE (21)
    ("black-white-car-heat", 5): BORDERLINE,
    ("entomopathogenic-fungi", 5): BORDERLINE,
    ("entomopathogenic-fungi", 6): BORDERLINE,
    ("fasting-method", 3): BORDERLINE,
    ("fasting-method", 4): BORDERLINE,
    ("fishing-harbor-renovation", 3): BORDERLINE,
    ("hot-pack", 2): BORDERLINE,
    ("hot-pack", 7): BORDERLINE,
    ("salt-soda", 4): BORDERLINE,
    ("sea-ice-land-ice", 3): BORDERLINE,
    ("truck-cornering", 2): BORDERLINE,
    ("typhoon-database", 3): BORDERLINE,
    ("typhoon-database", 4): BORDERLINE,
    ("washing-machine-physics", 5): BORDERLINE,
    ("weather-proverbs", 1): BORDERLINE,
    ("weather-proverbs", 2): BORDERLINE,
    ("wind-corridor-effect", 1): BORDERLINE,
    ("冰島冰河湖", 2): BORDERLINE,
    ("早餐論證A線上版", 4): BORDERLINE,
    ("胡椒蛾的分子機制", 2): BORDERLINE,
    ("蛙勒", 2): BORDERLINE,
}

# ---------------------------------------------------------------------------
# 規則 C relabels for the 38 CLEAR+BORDERLINE entries.
# Fields: (verdict, reason, framing_basis, contestable)
# framing_basis ∈ {題幹, 學習內容/科學能力, 科學概念必要環節, 圖表資料, 其他}
# contestable: True when framing rests on 圖表資料 or 其他 (not accepted by
#   the strict reading of 規則 C 判準 which only allows 題幹 narration,
#   declared 學習內容/科學能力, or scientifically necessary components)
# ---------------------------------------------------------------------------

@dataclass
class RuleCRelabel:
    verdict: str  # VIOLATES | LEGAL
    reason: str
    framing_basis: str
    contestable: bool  # True when LEGAL but framing is 圖表資料 or 其他


RULE_C_RELABELS: dict[tuple[str, int], RuleCRelabel] = {
    # --- CLEAR COUNT entries ---
    ("entomopathogenic-fungi", 2): RuleCRelabel(
        LEGAL,
        "題幹明寫「從孢子粉比例與致死效果」兩個面向，集合由題幹事前框定",
        "題幹",
        False,
    ),
    ("entomopathogenic-fungi", 3): RuleCRelabel(
        VIOLATES,
        "題幹問「有什麼好處？」，好處成分集合開放，未事前框定",
        "其他",
        False,
    ),
    ("seawater-vertical-properties", 2): RuleCRelabel(
        LEGAL,
        "題目給定固定5個海水性質項目排序，集合由題幹文字框定",
        "題幹",
        False,
    ),
    ("二氧化碳的產生與改變", 1): RuleCRelabel(
        LEGAL,
        "由附圖可知兩個影響光合速率的變因（光強度、溫度），集合由圖表資料框定",
        "圖表資料",
        True,
    ),
    ("反應速率", 1): RuleCRelabel(
        LEGAL,
        "實驗固定三支試管（A、B、C），比較集合由題幹框定",
        "題幹",
        False,
    ),
    ("大氣能見度", 1): RuleCRelabel(
        LEGAL,
        "附表框定區分霧與霾所需的觀測項目（AQI、相對溼度），集合由圖表資料固定",
        "圖表資料",
        True,
    ),
    ("大氣能見度", 3): RuleCRelabel(
        LEGAL,
        "表格欄位固定（8格），完整填寫反映公式掌握度，集合由圖表資料固定",
        "圖表資料",
        True,
    ),
    ("拉塞福散射", 2): RuleCRelabel(
        LEGAL,
        "題幹明寫「第一個及最後一個設置的投影幕位置」，兩個答案由題幹框定",
        "題幹",
        False,
    ),
    ("果凍", 5): RuleCRelabel(
        LEGAL,
        "題幹的參考資料明列「蛋白質」與「酵素」兩個關鍵字，集合由題幹文字框定",
        "題幹",
        False,
    ),
    ("生物防治2-1", 1): RuleCRelabel(
        VIOLATES,
        "題幹問「對本土生態環境的影響」，影響對象（作物、人）未在題目中事前框定",
        "其他",
        False,
    ),
    ("生物防治2-1", 3): RuleCRelabel(
        LEGAL,
        "題目引導學生「根據上述產卵歷程觀察」，歷程描述框定兩個機制",
        "題幹",
        False,
    ),
    ("生物防治2-1", 5): RuleCRelabel(
        LEGAL,
        "題幹明寫「含羽化率及雌雄比的釋放資訊」，兩個決策依據由題幹框定",
        "題幹",
        False,
    ),
    ("筆芯電阻", 1): RuleCRelabel(
        LEGAL,
        "題目給定固定組別清單，三組答案由控制單一變因原則唯一決定",
        "題幹",
        False,
    ),
    ("胡椒蛾的分子機制", 3): RuleCRelabel(
        LEGAL,
        "Hardy-Weinberg定律明定5個平衡條件，違反原因集合由科學概念必要環節固定",
        "科學概念必要環節",
        False,
    ),
    ("蛙勒", 4): RuleCRelabel(
        LEGAL,
        "附圖框定各月蛙種數，最多種月份（4、5、6月）集合由圖表資料固定",
        "圖表資料",
        True,
    ),
    ("運動與健康-糖尿病患者的健康生活", 3): RuleCRelabel(
        LEGAL,
        "題目明寫「繪出兩位的血糖變化曲線」，2條曲線集合由題幹固定",
        "題幹",
        False,
    ),
    ("隕石探究", 6): RuleCRelabel(
        LEGAL,
        "題幹明寫「撞擊坑深度、面積數值」兩個量度，集合由題幹框定",
        "題幹",
        False,
    ),
    # --- BORDERLINE entries ---
    ("black-white-car-heat", 5): RuleCRelabel(
        LEGAL,
        "實驗表格框定兩個可比較的數據面向（爆炸溫度相近、爆炸時間不同）",
        "圖表資料",
        True,
    ),
    ("entomopathogenic-fungi", 5): RuleCRelabel(
        LEGAL,
        "實驗設計框定兩個特定統計缺陷（基準不一致、忽略個別趨勢）",
        "圖表資料",
        True,
    ),
    ("entomopathogenic-fungi", 6): RuleCRelabel(
        LEGAL,
        "圖表資料結構框定兩個評估維度（單次最佳B、逐次穩定A）",
        "圖表資料",
        True,
    ),
    ("fasting-method", 3): RuleCRelabel(
        VIOLATES,
        "題幹指定「兩個結論」，但結論內容開放（【注意】：個數不等於集合）",
        "其他",
        False,
    ),
    ("fasting-method", 4): RuleCRelabel(
        VIOLATES,
        "「援引至少兩份圖表資訊」是數量要求，哪兩份圖表未由題目事前固定",
        "其他",
        False,
    ),
    ("fishing-harbor-renovation", 3): RuleCRelabel(
        LEGAL,
        "題目框定比較蓄熱與散熱兩個測量階段，集合由題幹框定",
        "題幹",
        False,
    ),
    ("hot-pack", 2): RuleCRelabel(
        VIOLATES,
        "題目問「如何選擇暖暖包」未列出三個考量向度，集合未事前框定",
        "其他",
        False,
    ),
    ("hot-pack", 7): RuleCRelabel(
        VIOLATES,
        "題目要求分析「多種做法的可行性」，具體做法集合未框定",
        "其他",
        False,
    ),
    ("salt-soda", 4): RuleCRelabel(
        LEGAL,
        "假設須包含溫度與CO2溶解度的完整因果鏈，兩個成分由科學概念必要環節固定",
        "科學概念必要環節",
        False,
    ),
    ("sea-ice-land-ice", 3): RuleCRelabel(
        LEGAL,
        "題目框定兩個具體器材選擇任務（海冰與陸地冰），集合由題幹框定",
        "題幹",
        False,
    ),
    ("truck-cornering", 2): RuleCRelabel(
        LEGAL,
        "題幹含兩個明確子問題（重心偏向何方＋力矩說明翻覆），集合由題幹框定",
        "題幹",
        False,
    ),
    ("typhoon-database", 3): RuleCRelabel(
        LEGAL,
        "颱風追蹤資料框定降雨區轉移的完整路徑序列，集合由圖表資料固定",
        "圖表資料",
        True,
    ),
    ("typhoon-database", 4): RuleCRelabel(
        LEGAL,
        "題目呈現三條特定推論供評判，集合由題幹框定",
        "題幹",
        False,
    ),
    ("washing-machine-physics", 5): RuleCRelabel(
        VIOLATES,
        "題幹問「什麼影響因素？」，答案集合開放，以個數（2點以上）分級為計數式",
        "其他",
        False,
    ),
    ("weather-proverbs", 1): RuleCRelabel(
        LEGAL,
        "題目指定五月與六月兩個月份，對應氣象系統集合由題幹固定",
        "題幹",
        False,
    ),
    ("weather-proverbs", 2): RuleCRelabel(
        LEGAL,
        "題目指定標示兩個氣象系統（北方鋒面、東方高壓），集合由題幹固定",
        "題幹",
        False,
    ),
    ("wind-corridor-effect", 1): RuleCRelabel(
        VIOLATES,
        "題目問「如何藉由實驗驗證」，提出哪些實驗類型未由題目框定",
        "其他",
        False,
    ),
    ("冰島冰河湖", 2): RuleCRelabel(
        LEGAL,
        "題文呈現競爭說法供驗證，需蒐集資料的說法集合由題幹框定",
        "題幹",
        False,
    ),
    ("早餐論證A線上版", 4): RuleCRelabel(
        LEGAL,
        "題幹明寫兩個結果（省略早餐、變胖比例高），推論路徑集合由題幹固定",
        "題幹",
        False,
    ),
    ("胡椒蛾的分子機制", 2): RuleCRelabel(
        LEGAL,
        "題幹要求「分別解釋突變前（顯性）與突變後（隱性）」，兩個等位基因由題幹固定",
        "題幹",
        False,
    ),
    ("蛙勒", 2): RuleCRelabel(
        LEGAL,
        "題幹明寫「填寫表(一)（含：生殖方式、受精方式、類似動物、大量產卵的意義）」",
        "題幹",
        False,
    ),
}

# ---------------------------------------------------------------------------
# Verifier criterion prompt
# ---------------------------------------------------------------------------

VERIFIER_SYSTEM = """\
你是108課綱自然科學／社會領域素養導向命題的評分規準稽核員。
你的任務是判斷一道小題的評分規準是否違反下列「規則 C」。

## 規則 C（完整條文）

開放式建構反應題 / Constructed response 的評分規準必須依循以下規定：

  【禁止】不得以學生列舉的項目「數量」區分級距。

  【判準】要分辨是「完整度」還是「數量」，看該小題自身的題目敘述與所宣告的
  學習內容／科學能力，能否在事前把「完整答案的成分集合」框定下來：
  - 能框定 → 依補齊幾個成分分級為合法，且 [2] 必須逐一指名該集合的成員。
    （例：題目明寫「請從甲、乙兩個面向說明」；或該科學概念本身即由數個必要環節構成。）
  - 不能框定 → 不得依數量分級；[1] 必須以推理鏈條的缺口描述，
    不得寫成「僅提及其中之一」。
    （例：題目問「有什麼好處？」「請提出建議」，可接受的答案是一群開放、獨立的項目。）

  【注意】題幹指定的「數量」不等於框定「集合」。「請寫兩個結論」只固定了個數，
  並未固定是哪兩個，因此屬於不能框定。

  【具體性】評分規準說明必須指名本小題的內容——[2] 要寫出本題該答對什麼，
  [1] 要寫出本題最可能出現的缺口。不得使用「完整正確回答／部分正確／錯誤」
  這類可套用到任何題目的字樣。

注意：
- 本規則僅適用於「Constructed response / 開放式建構反應題」。
- Complex multiple-choice 與 Simple multiple-choice 不受此規則約束。
"""

VERIFIER_USER_TEMPLATE = """\
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


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _rubric_entries_to_text(rubric: list[dict[str, Any]]) -> str:
    lines = []
    for entry in rubric:
        code = entry.get("code") or entry.get("編碼", "?")
        desc = entry.get("規準說明") or entry.get("說明", "")
        lines.append(f"[{code}] {desc}")
    return "\n".join(lines)


def _learning_content_str(lc: object) -> str:
    if isinstance(lc, list):
        parts = []
        for item in lc:
            if isinstance(item, dict):
                code = item.get("編碼", "")
                desc = item.get("說明", "")
                parts.append(f"{code} {desc}".strip())
            else:
                parts.append(str(item))
        return "；".join(p for p in parts if p)
    if isinstance(lc, str):
        return lc
    return str(lc)


def _science_ability_str(sa: object) -> str:
    if isinstance(sa, list):
        return "；".join(str(x) for x in sa)
    if isinstance(sa, str):
        return sa
    return str(sa)


@dataclass
class Entry:
    file_stem: str
    item_idx: int
    seq: int
    question_type: str
    question_stem: str
    learning_content: str
    science_ability: str
    rubric_raw: list[dict]
    rubric_text: str

    # Classification
    label_648: str  # CLEAR / BORDERLINE / CONFORMING / OUT_OF_SCOPE_C3
    rule_c_verdict: str | None  # VIOLATES / LEGAL / None
    rule_c_reason: str | None
    rule_c_framing_basis: str | None
    rule_c_contestable: bool  # True → LEGAL but based on 圖表資料/其他

    @property
    def cache_key(self) -> str:
        return f"{self.file_stem}|{self.item_idx}|{self.seq}"

    @property
    def expected_pass(self) -> bool:
        """Standard labeling: VIOLATES → expected fail."""
        return self.rule_c_verdict != VIOLATES

    @property
    def strict_expected_pass(self) -> bool:
        """Strict labeling: contestable LEGAL also counts as VIOLATES."""
        if self.rule_c_verdict == VIOLATES:
            return False
        if self.rule_c_contestable:
            return False
        return True

    # LLM output (filled after running)
    llm_set_framed: bool | None = None
    llm_counting_violation: bool | None = None
    llm_specificity_violation: bool | None = None
    llm_verdict: str | None = None
    llm_details: str | None = None
    llm_framing_evidence: str | None = None
    llm_raw: dict | None = None

    @property
    def llm_passed(self) -> bool | None:
        if self.llm_verdict is None:
            return None
        return self.llm_verdict == PASS

    @property
    def llm_counting_pass(self) -> bool | None:
        """Pass/fail based on counting_violation only (ignores specificity)."""
        if self.llm_counting_violation is None:
            return None
        return not self.llm_counting_violation

    def to_dict(self) -> dict:
        d = asdict(self)
        d["cache_key"] = self.cache_key  # property not captured by asdict
        d["expected_pass"] = self.expected_pass
        d["strict_expected_pass"] = self.strict_expected_pass
        d["llm_passed"] = self.llm_passed
        d["llm_counting_pass"] = self.llm_counting_pass
        return d


def load_all_ns_entries(
    cr_dir: pathlib.Path,
    cmc_dir: pathlib.Path,
    smc_dir: pathlib.Path,
) -> list[Entry]:
    """Load ALL rubric-bearing NS 小題 from all three directories.

    Classification is by 題型 (never by directory):
    - OOS if Complex/Simple multiple-choice
    - CLEAR/BORDERLINE from AUDIT_648_LABELS if Constructed response
    - CONFORMING otherwise (Constructed response not in the 38-entry list)
    """
    entries: list[Entry] = []
    seen_keys: set[str] = set()

    for data_dir in [cr_dir, cmc_dir, smc_dir]:
        for fpath in sorted(data_dir.glob("*.json")):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception as e:
                print(
                    f"  [WARN] cannot load {fpath.name}: {e}", file=sys.stderr
                )
                continue
            for item_idx, item in enumerate(data):
                q = item.get("question", {})
                for sq in q.get("subquestions", []):
                    rubric = sq.get("評分規準")
                    if not rubric:
                        continue
                    seq = sq.get("序號")
                    q_type = sq.get("題型", "")

                    # Dedup across directories (same file may appear in multiple)
                    dedup_key = f"{fpath.stem}|{item_idx}|{seq}"
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)

                    # Classify by 題型
                    if _is_oos(q_type):
                        label_648 = OUT_OF_SCOPE_C3
                        rc = None
                    else:
                        # Constructed response (or 開放式)
                        audit_key = (fpath.stem, seq)
                        label_648 = AUDIT_648_LABELS.get(audit_key, CONFORMING)
                        rc = RULE_C_RELABELS.get(audit_key)

                    entries.append(
                        Entry(
                            file_stem=fpath.stem,
                            item_idx=item_idx,
                            seq=seq,
                            question_type=q_type,
                            question_stem=sq.get("題目", ""),
                            learning_content=_learning_content_str(
                                sq.get("學習內容", "")
                            ),
                            science_ability=_science_ability_str(
                                sq.get("科學能力", "")
                            ),
                            rubric_raw=rubric,
                            rubric_text=_rubric_entries_to_text(rubric),
                            label_648=label_648,
                            rule_c_verdict=rc.verdict if rc else None,
                            rule_c_reason=rc.reason if rc else None,
                            rule_c_framing_basis=rc.framing_basis if rc else None,
                            rule_c_contestable=rc.contestable if rc else False,
                        )
                    )
    return entries


def load_ss_entries(csv_path: pathlib.Path) -> list[Entry]:
    """Load social studies entries from CSV (2 rows with 評分規準)."""
    import csv

    entries: list[Entry] = []
    try:
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=1):
                rubric_raw_str = row.get("評分規準", "").strip()
                if not rubric_raw_str:
                    continue
                try:
                    rubric_raw = json.loads(rubric_raw_str)
                    if not isinstance(rubric_raw, list):
                        rubric_raw = [{"code": "?", "規準說明": rubric_raw_str}]
                except json.JSONDecodeError:
                    rubric_raw = [{"code": "?", "規準說明": rubric_raw_str}]

                q_type = row.get("題型", "開放式建構反應題")
                entries.append(
                    Entry(
                        file_stem=f"社會領域_row{i}",
                        item_idx=0,
                        seq=i,
                        question_type=q_type,
                        question_stem=row.get("題目", ""),
                        learning_content=row.get("學習內容", ""),
                        science_ability=row.get("認知歷程", ""),
                        rubric_raw=rubric_raw,
                        rubric_text=_rubric_entries_to_text(rubric_raw),
                        label_648=CONFORMING,
                        rule_c_verdict=None,
                        rule_c_reason=None,
                        rule_c_framing_basis=None,
                        rule_c_contestable=False,
                    )
                )
    except Exception as e:
        print(f"  [WARN] cannot load SS CSV: {e}", file=sys.stderr)
    return entries


# ---------------------------------------------------------------------------
# LLM criterion runner
# ---------------------------------------------------------------------------


def build_user_prompt(entry: Entry) -> str:
    return VERIFIER_USER_TEMPLATE.format(
        question_type=entry.question_type,
        question_stem=entry.question_stem[:600],
        learning_content=entry.learning_content[:200],
        science_ability=entry.science_ability[:200],
        rubric_text=entry.rubric_text[:600],
    )


def load_cache(path: pathlib.Path) -> dict[str, dict]:
    """Load cached responses.

    Handles both v1 keys (file_stem|seq) and v2 keys (file_stem|item_idx|seq).
    v1 keys are migrated by assuming item_idx=0.
    """
    cache: dict[str, dict] = {}
    if not path.exists():
        return cache
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            key = rec["_key"]
            # Migrate v1 key (file_stem|seq) → v2 key (file_stem|0|seq)
            parts = key.split("|")
            if len(parts) == 2:
                key = f"{parts[0]}|0|{parts[1]}"
                rec["_key"] = key
            cache[key] = rec
        except Exception:
            pass
    return cache


def save_to_cache(path: pathlib.Path, key: str, response: dict) -> None:
    record = {"_key": key, **response}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_criterion(
    entries: list[Entry],
    client: LLMClient,
    cache_path: pathlib.Path,
    rate_limit: float = 0.5,
) -> tuple[list[Entry], int]:
    """Run the LLM criterion, using cache for already-seen entries."""
    cache = load_cache(cache_path)
    call_count = 0

    for i, entry in enumerate(entries, start=1):
        cache_key = entry.cache_key
        if cache_key in cache:
            rec = cache[cache_key]
            if "error" not in rec:
                entry.llm_set_framed = rec.get("set_framed")
                entry.llm_counting_violation = rec.get("counting_violation")
                entry.llm_specificity_violation = rec.get("specificity_violation")
                entry.llm_verdict = rec.get("verdict")
                entry.llm_details = rec.get("details", "")
                entry.llm_framing_evidence = rec.get("framing_evidence", "")
                entry.llm_raw = rec
                continue

        user_prompt = build_user_prompt(entry)
        try:
            result = client.generate_json(
                system=VERIFIER_SYSTEM,
                user=user_prompt,
                purpose="verify",
            )
            call_count += 1
            entry.llm_set_framed = result.get("set_framed")
            entry.llm_counting_violation = result.get("counting_violation")
            entry.llm_specificity_violation = result.get("specificity_violation")
            entry.llm_verdict = result.get("verdict")
            entry.llm_details = result.get("details", "")
            entry.llm_framing_evidence = result.get("framing_evidence", "")
            entry.llm_raw = result
            save_to_cache(cache_path, cache_key, result)
        except Exception as e:
            print(
                f"  [ERROR] entry {i}/{len(entries)} {cache_key}: {e}",
                file=sys.stderr,
            )
            entry.llm_verdict = None
            entry.llm_raw = {"error": str(e)}
            save_to_cache(cache_path, cache_key, {"error": str(e)})

        if rate_limit > 0:
            time.sleep(rate_limit)

        if i % 20 == 0:
            print(
                f"  [{i}/{len(entries)}] calls so far: {call_count}",
                file=sys.stderr,
            )

    return entries, call_count


# ---------------------------------------------------------------------------
# Confusion matrix helpers
# ---------------------------------------------------------------------------


@dataclass
class ConfusionMatrix:
    bucket: str
    label_scheme: str  # "standard" | "strict" | "counting_only_standard" | etc.
    tp: int = 0
    fn: int = 0
    fp: int = 0
    tn: int = 0
    errors: int = 0

    @property
    def total(self) -> int:
        return self.tp + self.fn + self.fp + self.tn + self.errors

    def recall(self) -> float | None:
        denom = self.tp + self.fn
        return self.tp / denom if denom else None

    def precision(self) -> float | None:
        denom = self.tp + self.fp
        return self.tp / denom if denom else None

    def fpr(self) -> float | None:
        denom = self.fp + self.tn
        return self.fp / denom if denom else None


def _pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:.0%}"


def compute_bucket_matrix(
    entries: list[Entry],
    bucket: str,
    use_strict: bool,
    counting_only: bool,
) -> ConfusionMatrix:
    """Compute confusion matrix for a single bucket."""
    cm = ConfusionMatrix(
        bucket=bucket,
        label_scheme=(
            ("strict" if use_strict else "standard")
            + ("_counting_only" if counting_only else "_combined")
        ),
    )
    for entry in entries:
        if entry.label_648 != bucket:
            continue
        expected_pass = (
            entry.strict_expected_pass if use_strict else entry.expected_pass
        )
        predicted_pass = (
            entry.llm_counting_pass if counting_only else entry.llm_passed
        )
        if predicted_pass is None:
            cm.errors += 1
            continue
        if not expected_pass and not predicted_pass:
            cm.tp += 1
        elif not expected_pass and predicted_pass:
            cm.fn += 1
        elif expected_pass and not predicted_pass:
            cm.fp += 1
        else:
            cm.tn += 1
    return cm


def print_matrix_row(cm: ConfusionMatrix, header: str = "") -> None:
    if header:
        print(f"  {header}")
    r = _pct(cm.recall())
    p = _pct(cm.precision())
    fpr = _pct(cm.fpr())
    print(
        f"  Bucket={cm.bucket} n={cm.total} "
        f"TP={cm.tp} FN={cm.fn} FP={cm.fp} TN={cm.tn} Err={cm.errors} "
        f"| recall={r} FPR={fpr} precision={p}"
    )


def print_four_matrices(entries: list[Entry], bucket: str) -> None:
    """Print combined and counting-only matrices, standard and strict."""
    print(f"\n--- {bucket} ---")
    for use_strict in [False, True]:
        for counting_only in [False, True]:
            scheme = ("strict" if use_strict else "standard") + \
                     (", counting-only" if counting_only else ", combined")
            cm = compute_bucket_matrix(entries, bucket, use_strict, counting_only)
            print_matrix_row(cm, f"[{scheme}]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Loading entries from all three NS directories...", file=sys.stderr)
    ns_entries = load_all_ns_entries(DATA_NS_CR, DATA_NS_CMC, DATA_NS_SMC)
    ss_entries = load_ss_entries(DATA_SS_CSV)
    all_entries = ns_entries + ss_entries

    # --- Cross-check bucket totals vs #648 expected: 17/21/149/70 = 257 ---
    bucket_counts: dict[str, int] = {
        CLEAR: 0, BORDERLINE: 0, CONFORMING: 0, OUT_OF_SCOPE_C3: 0
    }
    for e in all_entries:
        bucket_counts[e.label_648] += 1
    expected = {CLEAR: 17, BORDERLINE: 21, CONFORMING: 149, OUT_OF_SCOPE_C3: 70}
    total = sum(bucket_counts.values())

    print(f"\n=== Bucket totals (total={total}, expected 257) ===")
    all_match = True
    for b in [CLEAR, BORDERLINE, CONFORMING, OUT_OF_SCOPE_C3]:
        ok = bucket_counts[b] == expected[b]
        all_match = all_match and ok
        match = "OK" if ok else f"MISMATCH (expected {expected[b]})"
        print(f"  {b}: {bucket_counts[b]}  {match}")

    if not all_match:
        # Name the residual mismatches
        print(
            "\n  [WARN] Residual mismatch — listing entries not in any expected bucket:",
            file=sys.stderr,
        )
        for b in [CLEAR, BORDERLINE, CONFORMING, OUT_OF_SCOPE_C3]:
            if bucket_counts[b] != expected[b]:
                print(
                    f"    {b}: got {bucket_counts[b]}, "
                    f"expected {expected[b]}, diff={bucket_counts[b]-expected[b]}",
                    file=sys.stderr,
                )
                if bucket_counts[b] < expected[b]:
                    print(
                        "    (too few — check if files are missing from data/)",
                        file=sys.stderr,
                    )

    # --- Print 38 relabels ---
    print("\n=== 38 relabels under 規則 C ===")
    relabelled = [e for e in all_entries if e.label_648 in (CLEAR, BORDERLINE)]
    contestable = [e for e in relabelled if e.rule_c_contestable]
    violates = [e for e in relabelled if e.rule_c_verdict == VIOLATES]
    legal = [e for e in relabelled if e.rule_c_verdict == LEGAL]
    print(
        f"  VIOLATES={len(violates)}  LEGAL={len(legal)}  "
        f"Contestable (LEGAL but 圖表資料)={len(contestable)}"
    )
    print(
        f"\n  {'File':35s} {'Seq':4s} {'648':12s} {'RuleC':10s} "
        f"{'Basis':20s} {'Ctst':5s} Reason"
    )
    print("-" * 130)
    for e in relabelled:
        verdict = e.rule_c_verdict or "N/A"
        basis = e.rule_c_framing_basis or ""
        ctst = "Y" if e.rule_c_contestable else ""
        reason = (e.rule_c_reason or "")[:50]
        print(
            f"  {e.file_stem:35s} {str(e.seq):4s} {e.label_648:12s} "
            f"{verdict:10s} {basis:20s} {ctst:5s} {reason}"
        )

    print(f"\n  Strict labeling adds {len(contestable)} more VIOLATES entries.")

    # --- LLM run (cache-first; re-running with a warm cache makes 0 new calls) ---
    print("\nStarting LLM criterion run...", file=sys.stderr)
    config = Config.from_env()
    client = LLMClient(config)
    model_id = config.model_verify or config.model_execute
    print(f"  Model: {model_id}", file=sys.stderr)

    all_entries, call_count = run_criterion(
        all_entries,
        client,
        RESPONSES_PATH,
        rate_limit=config.rate_limit_delay if config.rate_limit_delay > 0 else 0.3,
    )
    print(f"\n  Total new LLM calls: {call_count}", file=sys.stderr)

    # Assert all entries received LLM results (all must be in cache or fetched now)
    null_verdicts = [e.cache_key for e in all_entries if e.llm_verdict is None]
    if null_verdicts:
        raise AssertionError(
            f"{len(null_verdicts)} entries missing LLM verdict: {null_verdicts[:5]}"
        )
    print(
        f"  All {len(all_entries)} entries matched from cache/LLM.",
        file=sys.stderr,
    )

    # --- Save labelled set (after LLM run so llm_* fields are populated) ---
    labelled = [e.to_dict() for e in all_entries]
    LABELLED_SET_PATH.write_text(
        json.dumps(labelled, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  Labelled set saved to {LABELLED_SET_PATH}", file=sys.stderr)

    # --- Per-bucket confusion matrices (all 4 combinations) ---
    print("\n\n========== PER-BUCKET CONFUSION MATRICES ==========")
    print("Columns: TP FN FP TN Err | recall FPR precision")
    for bucket in [CLEAR, BORDERLINE, CONFORMING, OUT_OF_SCOPE_C3]:
        print_four_matrices(all_entries, bucket)

    # --- Pooled recall on all rule-C violations (standard labeling) ---
    violates_entries = [e for e in all_entries if e.rule_c_verdict == VIOLATES]
    caught_combined = [
        e for e in violates_entries if e.llm_passed is False
    ]
    caught_counting = [
        e for e in violates_entries if e.llm_counting_pass is False
    ]
    print("\n=== Pooled recall (all 8 VIOLATES, standard labeling) ===")
    print(
        f"  Combined (counting+specificity): {len(caught_combined)}/{len(violates_entries)}"
        f" = {_pct(len(caught_combined)/len(violates_entries) if violates_entries else None)}"
    )
    print(
        f"  Counting-only:                  {len(caught_counting)}/{len(violates_entries)}"
        f" = {_pct(len(caught_counting)/len(violates_entries) if violates_entries else None)}"
    )

    # --- FN and FP verbatim lists ---
    _print_fn_fp_lists(all_entries)

    # --- Spot-check: corrector repair feasibility ---
    print("\n=== Spot-check: corrector repair feasibility ===")
    violates_detected = [
        e for e in all_entries
        if e.rule_c_verdict == VIOLATES and e.llm_verdict == FAIL and e.llm_details
    ]
    _run_corrector_spotcheck(violates_detected[:3], client)

    # --- Summary ---
    print("\n\n========== SUMMARY ==========")
    print(f"Total entries: {total}")
    print(f"Bucket counts: {bucket_counts}")
    print(f"New LLM calls: {call_count}  Model: {model_id}")
    print(f"Responses cached to: {RESPONSES_PATH}")
    print(f"Labelled set: {LABELLED_SET_PATH}")

    # Compact matrix summary
    print("\nCompact matrix (standard, combined):")
    for bucket in [CLEAR, BORDERLINE, CONFORMING, OUT_OF_SCOPE_C3]:
        cm = compute_bucket_matrix(all_entries, bucket, False, False)
        print_matrix_row(cm)
    print("\nCompact matrix (standard, counting-only):")
    for bucket in [CLEAR, BORDERLINE, CONFORMING, OUT_OF_SCOPE_C3]:
        cm = compute_bucket_matrix(all_entries, bucket, False, True)
        print_matrix_row(cm)
    print("\nCompact matrix (strict, combined):")
    for bucket in [CLEAR, BORDERLINE, CONFORMING, OUT_OF_SCOPE_C3]:
        cm = compute_bucket_matrix(all_entries, bucket, True, False)
        print_matrix_row(cm)
    print("\nCompact matrix (strict, counting-only):")
    for bucket in [CLEAR, BORDERLINE, CONFORMING, OUT_OF_SCOPE_C3]:
        cm = compute_bucket_matrix(all_entries, bucket, True, True)
        print_matrix_row(cm)


def _print_fn_fp_lists(all_entries: list[Entry]) -> None:
    print("\n=== False Negatives on CLEAR + BORDERLINE ===")
    for bucket in [CLEAR, BORDERLINE]:
        fns = [
            e for e in all_entries
            if e.label_648 == bucket
            and e.rule_c_verdict == VIOLATES
            and e.llm_passed is True
        ]
        print(f"  {bucket}: {len(fns)} FN")
        for e in fns:
            print(f"    {e.file_stem} Seq {e.seq}")
            print(f"      規準: {e.rubric_text[:100]}")
            print(f"      model details: {e.llm_details!r}")

    print("\n=== False Positives on OUT_OF_SCOPE_C3 (combined verdict) ===")
    fps_oos = [
        e for e in all_entries
        if e.label_648 == OUT_OF_SCOPE_C3
        and e.llm_passed is False
    ]
    for e in fps_oos:
        print(f"  {e.file_stem} Seq {e.seq} 題型={e.question_type}")
        print(f"    規準: {e.rubric_text[:100]}")
        print(f"    model details: {e.llm_details!r}")

    print(
        "\n=== False Positives on CONFORMING / LEGAL (counting-only, standard) ==="
    )
    fps_conf = [
        e for e in all_entries
        if e.label_648 in (CONFORMING, CLEAR, BORDERLINE)
        and e.expected_pass
        and e.llm_counting_pass is False
    ]
    print(f"  Total: {len(fps_conf)}")
    for e in fps_conf[:5]:
        print(
            f"  {e.file_stem} Seq {e.seq} [{e.label_648}] "
            f"RuleC={e.rule_c_verdict}"
        )
        print(f"    規準: {e.rubric_text[:80]}")


def _run_corrector_spotcheck(entries: list[Entry], client: LLMClient) -> None:
    CORRECTOR_SYSTEM = """\
你是一位 PISA Science 與108課綱自然科學領域命題教師，剛收到審核老師對一道題組的意見回饋。
請根據審核意見「最小幅度」修正題目，保留所有正確的部分。

修正原則：
- 不要重寫整題，只更正審核老師明確指出有問題的部分。
- 若問題在小題答案或評分規準，請只修改對應小題的 答案/答案解析/評分規準。
- 若問題在選項設計，請修正對應小題題目文字與答案，同步修正 正確解題分析。
- 若問題在文本素材或小題敘述歧義，請最小幅度澄清文本或小題題目，同步調整答案解析。
- 絕對不可修改：核心問題、情境、情境子類別、題型種類、題型、科學能力、id、metadata，
  以及各小題的 學習內容/學習表現/科學能力/出題概念/出題指示/Reporting Scale/科目/年級。

請輸出修正後的評分規準（JSON 格式），不要輸出其他文字。
"""
    for entry in entries:
        print(f"\n  --- Spotcheck: {entry.file_stem} Seq {entry.seq} ---")
        print(f"  Original 規準: {entry.rubric_text[:200]}")
        print(f"  Verifier details: {entry.llm_details}")

        corrector_user = (
            f"審核意見：{entry.llm_details}\n\n"
            f"待修正的評分規準（小題 {entry.seq}，題型：{entry.question_type}）：\n"
            f"題目：{entry.question_stem[:300]}\n"
            f"現有評分規準：\n{entry.rubric_text}\n\n"
            "請輸出修正後的評分規準（JSON 陣列，每項含 code, 規準說明），"
            "不要輸出其他文字。"
        )
        try:
            result = client.generate_json(
                system=CORRECTOR_SYSTEM,
                user=corrector_user,
                purpose="correct",
            )
            print(
                f"  Corrector output: "
                f"{json.dumps(result, ensure_ascii=False)[:300]}"
            )
        except Exception as e:
            print(f"  Corrector error: {e}")


if __name__ == "__main__":
    main()
