import random
from pathlib import Path

from src.context_builder import _math_group_few_shot_text
from src.data_loader import load_few_shot_examples


def test_math_group_few_shot_is_loaded_from_an_isolated_style_directory() -> None:
    few_shot_dir = Path("data/few_shot")

    grouped = load_few_shot_examples(few_shot_dir, "grouped")
    flat = load_few_shot_examples(few_shot_dir, "text_only")

    assert grouped
    assert "題組示例" in _math_group_few_shot_text(
        few_shot_dir,
        random.Random(3),
    )
    assert all(
        "subquestions" not in example.get("question", example)
        for loaded in flat
        for example in (loaded if isinstance(loaded, list) else [loaded])
    )
