# ruff: noqa: E501
"""Shared open-response rubric constants and shape checker (issue #866).

A single source of truth for:
- The verbatim rule block injected into every rubric-authoring prompt.
- The fixed sentence that must appear in every [2] 規準說明.
- The counting-stem corrector routing line (#650 amendment).
- Expected 學生作答實例 counts per level.
- The open-response 題型 predicate.
- The pure shape-check function (D3).

Amendments:
- #859: 【判準】 wording amended (图表框定 clause added).
- #650: Counting-stem ban + corrector routing line.
- #871: 【額外項目】 fixed-sentence requirement + EXTRA_ITEMS_FIXED_SENTENCE constant.
"""

from __future__ import annotations

# #871: the fixed sentence that MUST appear verbatim in every [2] 規準說明.
# It is interpolated into OPEN_RESPONSE_RUBRIC_RULE so the block remains
# byte-identical to the approved text while the constant stays single-source.
EXTRA_ITEMS_FIXED_SENTENCE = (
    "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
)

# #650: routing line added to the 自然科學 corrector's 修正原則 list.
# Defined here so #868 (社會領域) can reuse it.
COUNTING_STEM_CORRECTION_ROUTING_LINE = (
    "- 若問題在小題以數字或「有哪些」要求學生從開放集合列舉（計數式提問）→ 改寫該小題題目為\n"
    "  逐一點名各項或只要求一項，並同步修改答案/答案解析/評分規準。"
)

# The verbatim rule block (#871 approved, with #859 【判準】 amendment).
# Byte-identical to /tmp/…/final_block.txt; EXTRA_ITEMS_FIXED_SENTENCE is
# a substring of the 【額外項目】 clause (inside the 「」 marks).
OPEN_RESPONSE_RUBRIC_RULE = (
    "- 開放式建構反應題 / Constructed response：必須附每題專屬 `評分規準`，固定使用 2 / 1 / 0 三級。\n"
    "  級距依「該小題所宣告的認知歷程（社會領域）／科學能力（自然科學）被完成到什麼程度」區分，\n"
    "  也就是學生推理鏈條的完整度：\n"
    "  - [2] 完整走完該認知歷程／科學能力所要求的推理，且有證據支持。\n"
    "  - [1] 已進入該推理，但鏈條有缺口：依據不足、連結錯誤，或結論未回扣證據。\n"
    "  - [0] 未進入該推理，或方向錯誤。\n"
    "  【禁止】不得以學生列舉的項目「數量」區分級距。\n"
    "  【判準】要分辨是「完整度」還是「數量」，看該小題自身的題目敘述與所宣告的\n"
    "  學習內容／科學能力，能否在事前把「完整答案的成分集合」框定下來：\n"
    "  - 能框定 → 依補齊幾個成分分級為合法，且 [2] 必須逐一指名該集合的成員。\n"
    "    （例：題目明寫「請從甲、乙兩個面向說明」；或該科學概念本身即由數個必要環節構成；\n"
    "    或題目所指的圖表本身決定了成員——完整答案可直接從圖表讀出，任何人看圖即列出同一份清單。）\n"
    "    以圖表框定時，[2] 須指明每個成員取自哪一張圖表（如「圖(一)」「附表」），\n"
    "    且該成員須以該圖表上可見的標示出現（軸、欄、列、圖例或區域）。\n"
    "  - 不能框定 → 不得依數量分級；[1] 必須以推理鏈條的缺口描述，\n"
    "    不得寫成「僅提及其中之一」。\n"
    "    （例：題目問「有什麼好處？」「請提出建議」，可接受的答案是一群開放、獨立的項目；\n"
    "    或「研究員為何質疑？」這類須分析資料才能提出的項目——圖表只提供資料，不決定成員。）\n"
    "  【注意】題幹指定的「數量」不等於框定「集合」。「請寫兩個結論」只固定了個數，\n"
    "  並未固定是哪兩個，因此屬於不能框定。\n"
    "  【提問】小題要求學生寫出兩項以上時，必須逐一點名各項是什麼（「一個優點與一個缺點」\n"
    "  「從甲、乙兩個面向」「(1)…(2)…」），使完整答案的成分集合可事前框定。\n"
    "  不得要求學生從開放集合中自行產出若干項——不論以數字（「請寫兩個結論」「至少列舉三項」）\n"
    "  或以「有哪些」提問。若集合已由題目框定，所要求的個數必須等於該集合的全部成員；\n"
    "  「其中任 N 項」只固定個數、未固定是哪幾項，屬於不能框定。只要求一項時不在此限。\n"
    "  若出題指示或出題概念要求學生列出若干項，請保留其數量並逐一點名各項；\n"
    "  無法點名時，改為只要求一項。\n"
    "  【額外項目】學生可能寫出比小題要求更多的項目。級距依學生所寫最完整的一項評定\n"
    "  （能框定時，每個成分各取最完整的一項）；其餘為額外項目，不論對錯都不影響級距，\n"
    "  只有與得分的作答矛盾（兩者不可能同時成立）時，最高給 [1]。\n"
    "  - [2] 的規準說明結尾必須逐字加上這一句：\n"
    f"    「{EXTRA_ITEMS_FIXED_SENTENCE}」\n"
    "  - [2] 只能要求本題指定的成分成立，不得要求學生自行多寫的項目也成立\n"
    "    （不得寫成「所提結論皆…」「所列理由都…」）。\n"
    "  【具體性】規準說明必須指名本小題的內容——[2] 要寫出本題該答對什麼，\n"
    "  [1] 要寫出本題最可能出現的兩種缺口，與下方兩個 [1] 實例一一對應。\n"
    "  不得使用「完整正確回答／部分正確／錯誤」這類可套用到任何題目的字樣\n"
    "  （【額外項目】規定的固定句不在此限）。\n"
    "  學生作答實例必須是本小題的作答——用到本題文本中的資料、變因或名稱；\n"
    "  不得使用「例如：」「完整正確回答」「（空白）」這類可貼到任何題目的內容。\n"
    "  【學生作答實例】每一級距的實例數固定為：[2] 一個、[1] 兩個、[0] 一個。\n"
    "  實例不得包含額外項目。\n"
    "  - 實例是學生可能真的寫出的作答原文，以學生口吻書寫。實例裡不得出現對這份作答的\n"
    "    評語（如「未說明原因」「只寫一點」「部分正確」）——評分理由寫在規準說明，不寫在實例裡。\n"
    "    若本小題要求繪圖、標示或作圖，實例改為中性描述學生畫了什麼，同樣不加評語。\n"
    "  - 第一個 [1] 實例是 [2] 實例的最小對照：提出相同的主張、相同數量的要點，也附了理由，\n"
    "    差別只在理由沒有接上推理鏈（依據不足、連結錯誤，或未回扣證據）。\n"
    "    第二個 [1] 實例呈現另一種缺口。\n"
    "    若依【判準】屬「能框定」，[1] 實例可改為缺少集合中的一個具名成分。\n"
    "  - [0] 實例是本小題最可能引出的錯誤觀念或錯誤方向，須是學生合理會寫的答案；\n"
    "    不得使用空白、「不知道」、或與題目無關、荒謬的作答。\n"
)

# Expected 學生作答實例 count per rubric level for open-response questions.
EXPECTED_EXAMPLE_COUNTS: dict[str, int] = {"2": 1, "1": 2, "0": 1}

_OPEN_RESPONSE_TYPES: frozenset[str] = frozenset({"開放式建構反應題", "Constructed response"})


def is_open_response(question_type: object) -> bool:
    """Return True if *question_type* represents an open-response 題型.

    Accepts enum instances (reads ``.value``) or plain strings.
    """
    val = getattr(question_type, "value", question_type)
    return val in _OPEN_RESPONSE_TYPES


def check_open_response_rubric_shape(
    subquestions: list,
    *,
    in_scope: list[bool] | None = None,
) -> list[str]:
    """Check rubric shape for open-response subquestions (design D3).

    For each in-scope subquestion, validates:
    1. The code set is exactly {2, 1, 0} (one entry each).
    2. Each present 2/1/0 level has the correct 學生作答實例 count.
    3. No whitespace-only examples.
    4. The [2] 規準說明 contains EXTRA_ITEMS_FIXED_SENTENCE verbatim.

    When the code set is wrong, the function still reports count issues
    for any existing 2/1/0 levels so the corrector can fix everything at once.

    Args:
        subquestions: list of SubQuestion-like objects with ``.序號`` (int),
            ``.評分規準`` (list of RubricEntry-like with ``.code``,
            ``.規準說明``, ``.學生作答實例``).
        in_scope: parallel bool list; if None every subquestion is checked;
            if provided, only indices where the value is True are checked.

    Returns:
        A list of human-readable issue strings (empty → conforming).
    """
    issues: list[str] = []

    for idx, sq in enumerate(subquestions):
        if in_scope is not None and not in_scope[idx]:
            continue

        n = getattr(sq, "序號", idx + 1)
        rubric = getattr(sq, "評分規準", [])

        # Collect codes and entries.
        entries_by_code: dict[str, object] = {}
        seen_codes: list[str] = []
        for entry in rubric:
            code = getattr(entry, "code", "")
            entries_by_code.setdefault(code, entry)
            seen_codes.append(code)

        # 1. Check level set exactly {2, 1, 0}.
        unique_codes = list(dict.fromkeys(seen_codes))  # preserves order, deduped
        expected_codes = {"2", "1", "0"}
        actual_code_set = set(seen_codes)

        if actual_code_set != expected_codes or len(seen_codes) != 3:
            # Build a readable representation of current codes.
            if seen_codes:
                try:
                    sorted_codes = " / ".join(
                        str(c) for c in sorted(seen_codes, key=lambda x: (len(x), x))
                    )
                except Exception:
                    sorted_codes = " / ".join(str(c) for c in seen_codes)
            else:
                sorted_codes = "（無）"
            issues.append(
                f"第{n}題：評分規準級距必須恰為 2 / 1 / 0 各一級（目前為 {sorted_codes}）"
            )

        # 2 & 3. Check example counts and whitespace for existing 2/1/0 levels.
        for code in ("2", "1", "0"):
            # Use the first entry with this code (entries_by_code stores first).
            entry = entries_by_code.get(code)
            if entry is None:
                continue  # missing level already reported above

            examples: list[str] = list(getattr(entry, "學生作答實例", []))

            # Check for whitespace-only examples.
            has_blank = any(ex.strip() == "" for ex in examples)
            if has_blank:
                issues.append(f"第{n}題 [{code}] 級距有空白的學生作答實例")

            # Count non-whitespace examples.
            non_blank = [ex for ex in examples if ex.strip() != ""]
            expected_count = EXPECTED_EXAMPLE_COUNTS[code]
            actual_count = len(non_blank)
            if actual_count != expected_count:
                _desc = {
                    "2": "本小題完整走完推理的學生作答原文",
                    "1": "第一個是 [2] 實例的最小對照，第二個呈現另一種缺口",
                    "0": "本小題最可能引出的錯誤觀念或錯誤方向",
                }[code]
                issues.append(
                    f"第{n}題 [{code}] 級距需要 {expected_count} 個學生作答實例"
                    f"（目前 {actual_count} 個）：{_desc}"
                )

        # 4. Check [2] 規準說明 contains EXTRA_ITEMS_FIXED_SENTENCE.
        entry_2 = entries_by_code.get("2")
        if entry_2 is not None:
            desc_2 = getattr(entry_2, "規準說明", "")
            if EXTRA_ITEMS_FIXED_SENTENCE not in desc_2:
                issues.append(
                    f"第{n}題 [2] 規準說明缺少固定句，請在結尾逐字加上："
                    f"「{EXTRA_ITEMS_FIXED_SENTENCE}」"
                )

    return issues
