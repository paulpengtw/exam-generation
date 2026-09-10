"""
Research #651 — 計數式規準 verifier criterion prototype.

Loads all 257 rubric-bearing subquestions, attaches #648 labels, applies
manual 規則 C relabels for the 38 CLEAR+BORDERLINE entries, runs an LLM
criterion over every entry (with JSONL caching for crash-recovery), and
prints per-bucket confusion matrices plus the false-negative / false-positive
verbatim lists.

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
# Path setup — allow running from repo root without installing
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.config import Config  # noqa: E402
from src.llm_client import LLMClient  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_NS = ROOT / "data" / "natural_sciences" / "few_shot" / "Constructed-response"
DATA_NS_CMC = ROOT / "data" / "natural_sciences" / "few_shot" / "Complex-multiple-choice"
DATA_NS_SMC = ROOT / "data" / "natural_sciences" / "few_shot" / "Simple-multiple-choice"
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

# ---------------------------------------------------------------------------
# #648 labels — (filename_stem, 序號) → CLEAR or BORDERLINE
# (everything else is classified by 題型 at load time)
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
# Each entry: (label_648, rule_c_verdict, reason_fragment)
# rule_c_verdict: VIOLATES | LEGAL
# ---------------------------------------------------------------------------

RULE_C_RELABELS: dict[tuple[str, int], tuple[str, str]] = {
    # --- CLEAR COUNT entries ---
    # Legal: 題幹明寫「請從孢子粉比例與致死效果說明」— 兩個面向由題幹框定
    ("entomopathogenic-fungi", 2): (
        LEGAL,
        "題幹明寫「從孢子粉比例與致死效果」兩個面向，集合由題幹事前框定",
    ),
    # Violates: 題幹問「有什麼好處？」— 開放式，成分集合未框定
    ("entomopathogenic-fungi", 3): (
        VIOLATES,
        "題幹問「有什麼好處？」，好處成分集合開放，未事前框定",
    ),
    # Legal: 固定5個項目依深度排列，集合由題目本身框定
    ("seawater-vertical-properties", 2): (
        LEGAL,
        "題目給定固定5個海水性質項目，學生任務是依深度排列，集合已框定",
    ),
    # Legal: 圖中固定兩個變因（光強度、溫度），集合由圖表框定
    ("二氧化碳的產生與改變", 1): (
        LEGAL,
        "由附圖可知影響光合速率的兩個變因為光強度與溫度，集合由圖表資料框定",
    ),
    # Legal: 固定三支試管，觀察集合已框定
    ("反應速率", 1): (
        LEGAL,
        "實驗固定A、B、C三支試管，比較三者差異的集合由試管設計框定",
    ),
    # Legal: 附表框定分辨霧/霾所需的兩個觀測資料（AQI、相對溼度）
    ("大氣能見度", 1): (
        LEGAL,
        "附表框定區分霧與霾所需的觀測項目（AQI、相對溼度），集合由表格事前固定",
    ),
    # Legal: 表格欄位固定，填表完整度即為正確性標準
    ("大氣能見度", 3): (
        LEGAL,
        "表格欄位固定（8格），填答完整度反映轉換公式掌握度，集合由表格結構框定",
    ),
    # Legal: 題幹明寫「第一個及最後一個設置的投影幕位置」，兩個答案由題目框定
    ("拉塞福散射", 2): (
        LEGAL,
        "題幹明寫「第一個及最後一個設置的投影幕位置」，兩個特定答案由題目框定",
    ),
    # Legal: 參考資料已給定「蛋白質」與「酵素」兩個關鍵字
    ("果凍", 5): (
        LEGAL,
        "參考資料明列「明膠含蛋白質」與「新鮮木瓜含酵素」，兩個關鍵字由資料框定",
    ),
    # Violates: 「對本土生態環境的影響」未明列影響對象集合
    ("生物防治2-1", 1): (
        VIOLATES,
        "題幹問「對本土生態環境的影響」，影響對象（作物、人）未在題目中事前框定",
    ),
    # Legal: 產卵歷程描述框定兩個生物機制（在卵中產卵＋吸食卵液）
    ("生物防治2-1", 3): (
        LEGAL,
        "題目引導學生「根據上述產卵歷程觀察」，歷程描述框定兩個機制",
    ),
    # Legal: 題幹明寫「含羽化率及雌雄比」兩個條件
    ("生物防治2-1", 5): (
        LEGAL,
        "題幹明寫「含羽化率及雌雄比的釋放資訊」，兩個決策依據由題幹框定",
    ),
    # Legal: 給定組別清單，選三組符合控制變因原則
    ("筆芯電阻", 1): (
        LEGAL,
        "題目給定固定組別清單，三組答案由控制單一變因原則唯一決定",
    ),
    # Legal: Hardy-Weinberg定律明定5個條件，違反集合由科學理論框定
    ("胡椒蛾的分子機制", 3): (
        LEGAL,
        "Hardy-Weinberg定律明定5個平衡條件，違反原因集合由理論固定",
    ),
    # Legal: 圖形資料框定出現最多種蛙類的月份集合
    ("蛙勒", 4): (
        LEGAL,
        "附圖框定各月出現的蛙種數，最多種的月份（4、5、6月）集合由資料固定",
    ),
    # Legal: 題目明寫繪出兩位的折線，集合固定
    ("運動與健康-糖尿病患者的健康生活", 3): (
        LEGAL,
        "題目明寫「繪出兩位的血糖變化曲線」，2條曲線的集合由題目固定",
    ),
    # Legal: 題幹明寫「深度、面積數值」兩個量度
    ("隕石探究", 6): (
        LEGAL,
        "題幹明寫「撞擊坑深度、面積數值」兩個量度，集合由題幹框定",
    ),
    # --- BORDERLINE entries ---
    # Legal: 實驗資料框定兩個面向（爆炸溫度、爆炸時間）
    ("black-white-car-heat", 5): (
        LEGAL,
        "實驗表格框定兩個可比較的數據面向（爆炸溫度相近、爆炸時間不同）",
    ),
    # Legal: 實驗設計框定兩個統計缺陷（基準不一致、忽略個別趨勢）
    ("entomopathogenic-fungi", 5): (
        LEGAL,
        "加總分析設計框定兩個特定統計問題，缺陷集合由實驗設計固定",
    ),
    # Legal: 資料結構框定兩個評估維度（單次最佳B組、逐次穩定A組）
    ("entomopathogenic-fungi", 6): (
        LEGAL,
        "圖表資料結構框定兩個評估維度（單次最佳B、逐次穩定A），集合由資料固定",
    ),
    # Violates: 題幹要求「兩個結論」但未框定是哪兩個
    ("fasting-method", 3): (
        VIOLATES,
        "題幹指定「兩個結論」，但結論內容開放（【注意】：個數不等於集合）",
    ),
    # Violates: 「至少兩份圖表」是數量限制，非集合框定
    ("fasting-method", 4): (
        VIOLATES,
        "「援引至少兩份圖表資訊」是數量要求，哪兩份圖表未由題目事前固定",
    ),
    # Legal: 實驗兩個測量階段（蓄熱、散熱）由題目框定
    ("fishing-harbor-renovation", 3): (
        LEGAL,
        "題目框定比較蓄熱與散熱兩個測量階段，集合由實驗設計固定",
    ),
    # Violates: 評估問題未明列三項考量（升溫效率、保溫時間、成本）
    ("hot-pack", 2): (
        VIOLATES,
        "題目問「如何選擇暖暖包」未列出三個考量向度，集合未事前框定",
    ),
    # Violates: 「兩項以上做法」未框定具體集合
    ("hot-pack", 7): (
        VIOLATES,
        "題目要求分析「多種做法的可行性」，具體做法集合未框定",
    ),
    # Legal: 科學因果鏈（鹽→溫度→CO2溶解度）固定推理成分
    ("salt-soda", 4): (
        LEGAL,
        "假設必須包含溫度與CO2溶解度的完整因果鏈，兩個成分由科學機制固定",
    ),
    # Legal: 題幹框定兩個具體器材選擇任務
    ("sea-ice-land-ice", 3): (
        LEGAL,
        "題目框定兩個具體器材選擇任務（海冰與陸地冰），集合由題目固定",
    ),
    # Legal: 題幹兩個子問題（重心偏移＋力矩說明）明確框定
    ("truck-cornering", 2): (
        LEGAL,
        "題幹含兩個明確子問題（重心偏向何方＋力矩如何說明翻覆），集合由題目固定",
    ),
    # Legal: 颱風路徑資料框定完整的降雨區轉移階段序列
    ("typhoon-database", 3): (
        LEGAL,
        "颱風追蹤資料框定降雨區轉移的完整路徑序列，階段集合由資料固定",
    ),
    # Legal: 題目呈現三條特定推論，評判集合固定
    ("typhoon-database", 4): (
        LEGAL,
        "題目呈現三條特定推論供評判，集合由題目固定",
    ),
    # Violates: 典型計數式規準，「有什麼影響因素」答案集合開放
    ("washing-machine-physics", 5): (
        VIOLATES,
        "題幹問「什麼影響因素？」，答案集合開放，以個數（2點以上）分級為計數式規準",
    ),
    # Legal: 梅雨鋒面（5月）與太平洋高壓（6月）由月份框定
    ("weather-proverbs", 1): (
        LEGAL,
        "題目指定五月與六月兩個月份，對應的氣象系統集合由月份固定",
    ),
    # Legal: 兩個氣象系統已在題目中命名（北方鋒面、東方高壓）
    ("weather-proverbs", 2): (
        LEGAL,
        "題目指定標示兩個氣象系統（北方鋒面、東方高壓），集合由題目固定",
    ),
    # Violates: 實驗設計題，具體實驗集合未框定
    ("wind-corridor-effect", 1): (
        VIOLATES,
        "題目問「如何藉由實驗驗證」，提出哪些實驗類型未由題目框定",
    ),
    # Legal: 題目呈現多個競爭說法，驗證集合由題目固定
    ("冰島冰河湖", 2): (
        LEGAL,
        "題文呈現競爭說法供驗證，需蒐集資料的說法集合由題目固定",
    ),
    # Legal: 題幹明寫兩條推論路徑（省略早餐、變胖）
    ("早餐論證A線上版", 4): (
        LEGAL,
        "題幹明寫兩個結果（省略早餐、變胖比例高），推論路徑集合由題目固定",
    ),
    # Legal: 題幹要求「分別解釋」兩個等位基因，角度已框定
    ("胡椒蛾的分子機制", 2): (
        LEGAL,
        "題幹要求「分別解釋突變前（顯性）與突變後（隱性）」，兩個等位基因集合由題目固定",
    ),
    # Legal: 題幹明寫4項表格欄位，集合固定
    ("蛙勒", 2): (
        LEGAL,
        "題幹明寫「填寫表(一)（含：生殖方式、受精方式、類似動物、大量產卵的意義）」4項",
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
- Complex multiple-choice 與 Simple multiple-choice 的評分規準不受此規則約束。
- 【具體性】違反指「完整正確回答、部分正確、錯誤」等空泛語句，不指名本題內容。

你的判斷依據是小題的「題目（題幹）」、「學習內容」、「科學能力」、「題型」，以及每一級距的「規準說明」。
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
  "details": "<str: verdict 為 fail 時，一句說明修正方向，以「[評分規準檢核]」開頭，指示 corrector
    如何改寫（不得說「計數少一點」）；verdict 為 pass 時輸出空字串>"
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
    seq: int
    question_type: str
    question_stem: str
    learning_content: str
    science_ability: str
    rubric_raw: list[dict]
    rubric_text: str

    # Classification
    label_648: str  # CLEAR / BORDERLINE / CONFORMING / OUT_OF_SCOPE_C3
    rule_c_verdict: str | None  # VIOLATES / LEGAL / None (not applicable)
    rule_c_reason: str | None

    # Ground truth for confusion matrix
    # True label for pass/fail expected from the criterion:
    # VIOLATES → expected fail
    # LEGAL / CONFORMING / OUT_OF_SCOPE_C3 → expected pass
    @property
    def expected_pass(self) -> bool:
        return self.rule_c_verdict != VIOLATES

    # LLM output (filled in after running)
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

    def to_dict(self) -> dict:
        d = asdict(self)
        d["expected_pass"] = self.expected_pass
        d["llm_passed"] = self.llm_passed
        return d


def load_ns_entries(data_dir: pathlib.Path) -> list[Entry]:
    """Load all Constructed-response NS entries."""
    entries: list[Entry] = []
    for fpath in sorted(data_dir.glob("*.json")):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [WARN] cannot load {fpath.name}: {e}", file=sys.stderr)
            continue
        for item in data:
            q = item.get("question", {})
            for sq in q.get("subquestions", []):
                rubric = sq.get("評分規準")
                if not rubric:
                    continue
                seq = sq.get("序號")
                q_type = sq.get("題型", "")

                # Only Constructed response in this directory, but check anyway
                if "Constructed" not in q_type and "開放式" not in q_type:
                    continue

                key = (fpath.stem, seq)
                label_648 = AUDIT_648_LABELS.get(key, CONFORMING)
                rc = RULE_C_RELABELS.get(key)

                entries.append(
                    Entry(
                        file_stem=fpath.stem,
                        seq=seq,
                        question_type=q_type,
                        question_stem=sq.get("題目", ""),
                        learning_content=_learning_content_str(sq.get("學習內容", "")),
                        science_ability=_science_ability_str(sq.get("科學能力", "")),
                        rubric_raw=rubric,
                        rubric_text=_rubric_entries_to_text(rubric),
                        label_648=label_648,
                        rule_c_verdict=rc[0] if rc else None,
                        rule_c_reason=rc[1] if rc else None,
                    )
                )
    return entries


def load_ns_oos_entries(cmc_dir: pathlib.Path, smc_dir: pathlib.Path) -> list[Entry]:
    """Load Complex/Simple multiple-choice (OUT_OF_SCOPE_C3)."""
    entries: list[Entry] = []
    for data_dir in [cmc_dir, smc_dir]:
        for fpath in sorted(data_dir.glob("*.json")):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  [WARN] cannot load {fpath.name}: {e}", file=sys.stderr)
                continue
            for item in data:
                q = item.get("question", {})
                for sq in q.get("subquestions", []):
                    rubric = sq.get("評分規準")
                    if not rubric:
                        continue
                    seq = sq.get("序號")
                    q_type = sq.get("題型", "")
                    entries.append(
                        Entry(
                            file_stem=fpath.stem,
                            seq=seq,
                            question_type=q_type,
                            question_stem=sq.get("題目", ""),
                            learning_content=_learning_content_str(sq.get("學習內容", "")),
                            science_ability=_science_ability_str(sq.get("科學能力", "")),
                            rubric_raw=rubric,
                            rubric_text=_rubric_entries_to_text(rubric),
                            label_648=OUT_OF_SCOPE_C3,
                            rule_c_verdict=None,
                            rule_c_reason=None,
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
                # SS CSV entries are both 開放式建構反應題 and conforming per #648
                entries.append(
                    Entry(
                        file_stem=f"社會領域_row{i}",
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
    """Load cached responses keyed by 'filestem|seq'."""
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
    """Run the LLM criterion over all entries, using cache for already-seen ones.

    Returns (entries_with_results, call_count).
    """
    cache = load_cache(cache_path)
    call_count = 0

    for i, entry in enumerate(entries, start=1):
        cache_key = f"{entry.file_stem}|{entry.seq}"
        if cache_key in cache:
            rec = cache[cache_key]
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
                f"  [ERROR] entry {i}/{len(entries)} {cache_key}: {e}", file=sys.stderr
            )
            entry.llm_verdict = None
            entry.llm_raw = {"error": str(e)}
            save_to_cache(cache_path, cache_key, {"error": str(e)})

        if rate_limit > 0:
            time.sleep(rate_limit)

        if i % 20 == 0:
            print(
                f"  [{i}/{len(entries)}] calls so far: {call_count}", file=sys.stderr
            )

    return entries, call_count


# ---------------------------------------------------------------------------
# Confusion matrix and reporting
# ---------------------------------------------------------------------------


@dataclass
class ConfusionMatrix:
    bucket: str
    tp: int = 0  # expected fail, predicted fail (correctly caught violation)
    fn: int = 0  # expected fail, predicted pass (missed violation)
    fp: int = 0  # expected pass, predicted fail (false alarm)
    tn: int = 0  # expected pass, predicted pass (correct pass)
    errors: int = 0  # LLM call failed

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
        """False positive rate = FP / (FP + TN)."""
        denom = self.fp + self.tn
        return self.fp / denom if denom else None

    def summary(self) -> str:
        r = self.recall()
        p = self.precision()
        fpr = self.fpr()
        return (
            f"Bucket={self.bucket}  n={self.total}  "
            f"TP={self.tp} FN={self.fn} FP={self.fp} TN={self.tn} Err={self.errors}\n"
            f"  recall={r:.0%} if r is not None else 'n/a'  "
            f"precision={p:.0%} if p is not None else 'n/a'  "
            f"FPR={fpr:.0%} if fpr is not None else 'n/a'"
        ).replace(
            "recall=r:.0% if r is not None else 'n/a'",
            f"recall={r:.0%}" if r is not None else "recall=n/a",
        )


def compute_matrices(
    entries: list[Entry],
) -> tuple[dict[str, ConfusionMatrix], list[Entry], list[Entry]]:
    """Compute per-bucket confusion matrices.

    Returns (matrices_by_bucket, false_negatives, false_positives).
    False negatives: bucket CLEAR or BORDERLINE, expected fail but got pass.
    False positives: bucket OUT_OF_SCOPE_C3, expected pass but got fail.
    """
    buckets = [CLEAR, BORDERLINE, CONFORMING, OUT_OF_SCOPE_C3]
    matrices: dict[str, ConfusionMatrix] = {b: ConfusionMatrix(bucket=b) for b in buckets}
    false_negatives: list[Entry] = []
    false_positives: list[Entry] = []

    for entry in entries:
        cm = matrices[entry.label_648]
        expected_pass = entry.expected_pass
        predicted_pass = entry.llm_passed

        if predicted_pass is None:
            cm.errors += 1
            continue

        if not expected_pass and not predicted_pass:
            cm.tp += 1
        elif not expected_pass and predicted_pass:
            cm.fn += 1
            false_negatives.append(entry)
        elif expected_pass and not predicted_pass:
            cm.fp += 1
            if entry.label_648 == OUT_OF_SCOPE_C3:
                false_positives.append(entry)
        else:
            cm.tn += 1

    return matrices, false_negatives, false_positives


def _pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:.0%}"


def print_matrix(cm: ConfusionMatrix) -> None:
    print(f"\n{'='*60}")
    print(f"Bucket: {cm.bucket}  (n={cm.total})")
    print(f"{'='*60}")
    print(f"  TP={cm.tp}  FN={cm.fn}  FP={cm.fp}  TN={cm.tn}  Err={cm.errors}")
    print(f"  Recall(catch rate) = {_pct(cm.recall())}")
    print(f"  Precision          = {_pct(cm.precision())}")
    print(f"  False positive rate= {_pct(cm.fpr())}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Loading entries...", file=sys.stderr)
    ns_entries = load_ns_entries(DATA_NS)
    oos_entries = load_ns_oos_entries(DATA_NS_CMC, DATA_NS_SMC)
    ss_entries = load_ss_entries(DATA_SS_CSV)

    all_entries = ns_entries + oos_entries + ss_entries

    # --- Cross-check bucket totals vs #648 expected: 17/21/149/70 ---
    bucket_counts = {CLEAR: 0, BORDERLINE: 0, CONFORMING: 0, OUT_OF_SCOPE_C3: 0}
    for e in all_entries:
        bucket_counts[e.label_648] += 1
    expected = {CLEAR: 17, BORDERLINE: 21, CONFORMING: 149, OUT_OF_SCOPE_C3: 70}
    total = sum(bucket_counts.values())
    print(f"\n=== Bucket totals (total={total}, expected 257) ===")
    for b in [CLEAR, BORDERLINE, CONFORMING, OUT_OF_SCOPE_C3]:
        match = "OK" if bucket_counts[b] == expected[b] else f"MISMATCH (expected {expected[b]})"
        print(f"  {b}: {bucket_counts[b]}  {match}")
    if any(bucket_counts[b] != expected[b] for b in expected):
        print(
            "\n  [WARN] Bucket counts do not match #648. Proceeding with loaded data.",
            file=sys.stderr,
        )

    # --- Save labelled set ---
    labelled = [e.to_dict() for e in all_entries]
    LABELLED_SET_PATH.write_text(
        json.dumps(labelled, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nLabelled set saved to {LABELLED_SET_PATH}", file=sys.stderr)

    # --- Print 38 relabels ---
    print("\n=== 38 relabels under 規則 C ===")
    relabelled = [e for e in all_entries if e.label_648 in (CLEAR, BORDERLINE)]
    print(f"{'File':40s} {'Seq':4s} {'648':12s} {'RuleC':10s} Reason")
    print("-" * 120)
    for e in relabelled:
        verdict = e.rule_c_verdict or "N/A"
        reason = (e.rule_c_reason or "")[:60]
        print(f"{e.file_stem:40s} {str(e.seq):4s} {e.label_648:12s} {verdict:10s} {reason}")

    violates_count = sum(1 for e in relabelled if e.rule_c_verdict == VIOLATES)
    legal_count = sum(1 for e in relabelled if e.rule_c_verdict == LEGAL)
    print(f"\n  VIOLATES: {violates_count}  LEGAL: {legal_count}")

    # --- LLM run ---
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
    print(f"\n  Total LLM calls made: {call_count}", file=sys.stderr)

    # --- Confusion matrices ---
    matrices, false_negatives, false_positives = compute_matrices(all_entries)

    print("\n\n========== PER-BUCKET CONFUSION MATRICES ==========")
    for b in [CLEAR, BORDERLINE, CONFORMING, OUT_OF_SCOPE_C3]:
        print_matrix(matrices[b])

    # --- False negatives on CLEAR (most critical) ---
    clear_fns = [e for e in false_negatives if e.label_648 == CLEAR]
    print(f"\n=== False Negatives on CLEAR bucket ({len(clear_fns)} entries) ===")
    for e in clear_fns:
        print(f"  {e.file_stem} Seq {e.seq}")
        print(f"    規準: {e.rubric_text[:120]}")
        print(f"    model details: {e.llm_details}")

    # --- All false negatives ---
    borderline_fns = [e for e in false_negatives if e.label_648 == BORDERLINE]
    print(f"\n=== False Negatives on BORDERLINE bucket ({len(borderline_fns)} entries) ===")
    for e in borderline_fns:
        print(f"  {e.file_stem} Seq {e.seq}")
        print(f"    規準: {e.rubric_text[:120]}")
        print(f"    model details: {e.llm_details}")

    # --- False positives on OUT_OF_SCOPE_C3 (dangerous) ---
    print(f"\n=== False Positives on OUT_OF_SCOPE_C3 ({len(false_positives)} entries) ===")
    for e in false_positives:
        print(f"  {e.file_stem} Seq {e.seq}")
        print(f"    題型: {e.question_type}")
        print(f"    規準: {e.rubric_text[:120]}")
        print(f"    model details: {e.llm_details}")

    # --- Also show FP on CONFORMING and LEGAL CLEAR/BORDERLINE ---
    other_fps = [
        e for e in all_entries
        if e.llm_passed is False
        and e.expected_pass
        and e.label_648 != OUT_OF_SCOPE_C3
    ]
    print(f"\n=== False Positives on CONFORMING/LEGAL entries ({len(other_fps)} entries) ===")
    for e in other_fps[:10]:
        print(f"  {e.file_stem} Seq {e.seq} [{e.label_648}, RuleC={e.rule_c_verdict}]")
        print(f"    規準: {e.rubric_text[:120]}")
        print(f"    model details: {e.llm_details}")

    # --- Spot-check: run 3 VIOLATES entries through corrector-shaped prompt ---
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
    print(f"LLM calls: {call_count}  Model: {model_id}")
    print(f"Responses cached to: {RESPONSES_PATH}")
    print(f"Labelled set saved to: {LABELLED_SET_PATH}")

    cm_clear = matrices[CLEAR]
    cm_bl = matrices[BORDERLINE]
    cm_conf = matrices[CONFORMING]
    cm_oos = matrices[OUT_OF_SCOPE_C3]
    print(
        f"\nCLEAR recall={_pct(cm_clear.recall())}  "
        f"BORDERLINE recall={_pct(cm_bl.recall())}  "
        f"CONFORMING FPR={_pct(cm_conf.fpr())}  "
        f"OOS FPR={_pct(cm_oos.fpr())}"
    )


def _run_corrector_spotcheck(entries: list[Entry], client: LLMClient) -> None:
    """Feed up to 3 failed entries to the corrector system prompt shape and show output."""
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

        corrector_user = f"""\
審核意見：{entry.llm_details}

待修正的評分規準（小題 {entry.seq}，題型：{entry.question_type}）：
題目：{entry.question_stem[:300]}
現有評分規準：
{entry.rubric_text}

請輸出修正後的評分規準（JSON 陣列，每項含 code, 規準說明），不要輸出其他文字。
"""
        try:
            result = client.generate_json(
                system=CORRECTOR_SYSTEM,
                user=corrector_user,
                purpose="correct",
            )
            print(f"  Corrector output: {json.dumps(result, ensure_ascii=False)[:300]}")
        except Exception as e:
            print(f"  Corrector error: {e}")


if __name__ == "__main__":
    main()
