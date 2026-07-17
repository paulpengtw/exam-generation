"""Every context_builder.py must cite the figure-rendering policy doc."""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_POLICY_ANCHOR = "docs/figure-rendering-policy.md"

_TARGETS = [
    _ROOT / "src" / "context_builder.py",
    _ROOT / "src" / "social_studies" / "context_builder.py",
    _ROOT / "src" / "natural_sciences" / "context_builder.py",
]


@pytest.mark.parametrize("path", _TARGETS, ids=lambda p: p.relative_to(_ROOT).as_posix())
def test_module_docstring_cites_figure_rendering_policy(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    # The policy anchor must appear inside the first module-level docstring block.
    head = text.split('"""', 3)
    assert len(head) >= 3, f"{path} has no module docstring"
    docstring = head[1]
    assert _POLICY_ANCHOR in docstring, (
        f"{path.relative_to(_ROOT).as_posix()} module docstring must cite "
        f"{_POLICY_ANCHOR}"
    )


def test_claude_md_links_figure_rendering_policy() -> None:
    text = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert _POLICY_ANCHOR in text
