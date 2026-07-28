"""Acceptance tests for the CurriculumContext refactor (issue #154).

Acceptance criteria:
  AC1 — Generator, verifier, and corrector receive the SAME curriculum text
         within one run.
  AC2 — No underscore-prefixed names are imported from ``src.context_builder``
         in ``src/verifier.py`` or ``src/corrector.py``.
  AC3 — Importing ``src.verifier`` / ``src.corrector`` triggers NO curriculum
         file I/O (tested via subprocess so the modules are always freshly
         imported).
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# AC1 — all three pipeline stages receive the identical curriculum section
# ---------------------------------------------------------------------------

def _make_fake_client(captures: dict):
    """Return a fake LLMClient that records what system prompt it receives."""
    class FakeClient:
        def generate_with_image(
            self,
            system_prompt: str,
            user_prompt: str,
            image_path=None,
            purpose="generate",
        ) -> str:
            captures.setdefault("system_prompts", []).append(system_prompt)
            return json.dumps({
                "my_answer": "D",
                "provided_answer": "D",
                "answer_match": True,
                "passed": True,
                "details": "ok",
            })

        def generate_json(
            self,
            system_prompt: str,
            user_prompt: str,
            purpose: str = "generate",
        ) -> dict:
            captures.setdefault("system_prompts", []).append(system_prompt)
            return {
                "題目": ["Q"],
                "正確解題分析": ["A"],
            }

        def get_observer(self):
            return None

    return FakeClient()


def test_same_curriculum_section_in_generator_verifier_corrector() -> None:
    """A single CurriculumContext must produce the same curriculum section
    string in the system prompts of build_system_prompt, verify_question,
    and correct_question."""
    from src.context_builder import build_system_prompt
    from src.corrector import correct_question
    from src.curriculum_context import build_curriculum_section, load_curriculum_context
    from src.schemas import ExamQuestion, LearningContentItem, VerificationResult
    from src.verifier import verify_question

    # Build ONE context for the whole run.
    ctx = load_curriculum_context()
    expected_section = build_curriculum_section(ctx)

    # 1. Generator — build_system_prompt must embed expected_section
    gen_prompt = build_system_prompt(curriculum_context=ctx)
    assert expected_section in gen_prompt, (
        "Generator system prompt does not contain the expected curriculum section"
    )

    # 2. Verifier — verify_question must embed expected_section
    question = ExamQuestion(
        id="ac1-test",
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="整數")],
        題目=["(A) 1 (B) 2 (C) 3 (D) 4"],
        正確解題分析=["選D"],
    )
    verifier_captures: dict = {}
    fake_client = _make_fake_client(verifier_captures)
    verify_question(fake_client, question, curriculum_context=ctx)
    verifier_system = verifier_captures["system_prompts"][0]
    assert expected_section in verifier_system, (
        "Verifier system prompt does not contain the expected curriculum section"
    )

    # 3. Corrector — correct_question must embed expected_section
    verification = VerificationResult(
        passed=False,
        answer_match=False,
        details="計算錯誤",
    )
    corrector_captures: dict = {}
    fake_corrector_client = _make_fake_client(corrector_captures)
    correct_question(
        fake_corrector_client, question, verification, curriculum_context=ctx
    )
    corrector_system = corrector_captures["system_prompts"][0]
    assert expected_section in corrector_system, (
        "Corrector system prompt does not contain the expected curriculum section"
    )


# ---------------------------------------------------------------------------
# AC2 — no underscore imports from src.context_builder in verifier / corrector
# ---------------------------------------------------------------------------

def _collect_private_context_builder_imports(source_path: Path) -> list[str]:
    """Return names imported from ``src.context_builder`` that start with '_'."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    bad: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if module not in ("src.context_builder", "src.context_builder"):
            continue
        for alias in node.names:
            name = alias.name
            if name.startswith("_"):
                bad.append(name)
    return bad


def test_verifier_has_no_private_context_builder_imports() -> None:
    """src/verifier.py must import no underscore-prefixed names from
    src.context_builder."""
    src_dir = Path(__file__).parent.parent / "src"
    bad = _collect_private_context_builder_imports(src_dir / "verifier.py")
    assert bad == [], (
        f"src/verifier.py imports private names from src.context_builder: {bad}"
    )


def test_corrector_has_no_private_context_builder_imports() -> None:
    """src/corrector.py must import no underscore-prefixed names from
    src.context_builder."""
    src_dir = Path(__file__).parent.parent / "src"
    bad = _collect_private_context_builder_imports(src_dir / "corrector.py")
    assert bad == [], (
        f"src/corrector.py imports private names from src.context_builder: {bad}"
    )


def test_verifier_does_not_import_context_builder_at_all() -> None:
    """Ideally src/verifier.py should not import src.context_builder at all."""
    src_dir = Path(__file__).parent.parent / "src"
    tree = ast.parse((src_dir / "verifier.py").read_text(encoding="utf-8"))
    imports_from_cb = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("src.context_builder")
    ]
    assert imports_from_cb == [], (
        "src/verifier.py should not import from src.context_builder at all"
    )


def test_corrector_does_not_import_context_builder_at_all() -> None:
    """Ideally src/corrector.py should not import src.context_builder at all."""
    src_dir = Path(__file__).parent.parent / "src"
    tree = ast.parse((src_dir / "corrector.py").read_text(encoding="utf-8"))
    imports_from_cb = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("src.context_builder")
    ]
    assert imports_from_cb == [], (
        "src/corrector.py should not import from src.context_builder at all"
    )


# ---------------------------------------------------------------------------
# AC3 — importing verifier / corrector triggers NO curriculum file I/O
# ---------------------------------------------------------------------------

def _build_io_sentinel_script(module_dotpath: str) -> str:
    """Return a Python snippet that imports *module_dotpath* under a patched
    ``open`` and fails if any of the three curriculum *corpus* files that
    ``context_builder`` used to load at import time are read.

    ``core_competencies.json`` is intentionally excluded: it has always been
    loaded at import time by ``src.schemas`` (independent of this issue) and
    is not part of the curriculum corpus threaded into prompts.
    """
    return f"""\
import sys, builtins, pathlib

# Only the three files that context_builder used to load transitively.
# core_competencies.json is excluded — it is always loaded by src.schemas
# at import time and is a pre-existing concern unrelated to this refactor.
_CORPUS_FILES = (
    "learning_content.json",
    "learning_performance.json",
    "learning_performance_intro.md",
)
_READS: list[str] = []
_orig_open = builtins.open
_orig_path_open = pathlib.Path.open

def _patched_open(file, *args, **kwargs):
    path_str = str(file).replace("\\\\", "/")
    if any(path_str.endswith(f) for f in _CORPUS_FILES):
        _READS.append(str(file))
    return _orig_open(file, *args, **kwargs)

def _patched_path_open(self, *args, **kwargs):
    path_str = str(self).replace("\\\\", "/")
    if any(path_str.endswith(f) for f in _CORPUS_FILES):
        _READS.append(str(self))
    return _orig_path_open(self, *args, **kwargs)

builtins.open = _patched_open
pathlib.Path.open = _patched_path_open

import {module_dotpath}  # noqa: E402

if _READS:
    print("CURRICULUM_IO_DETECTED:" + repr(_READS), file=sys.stderr)
    sys.exit(1)
"""


def _run_io_sentinel(module_dotpath: str) -> tuple[bool, str]:
    """Run the sentinel script in a fresh interpreter.

    Returns (ok, stderr).  ok=True means no curriculum I/O was detected.
    """
    repo_root = str(Path(__file__).parent.parent)
    result = subprocess.run(
        [sys.executable, "-c", _build_io_sentinel_script(module_dotpath)],
        capture_output=True,
        text=True,
        cwd=repo_root,
        timeout=30,
    )
    ok = result.returncode == 0
    return ok, result.stderr


def test_importing_verifier_triggers_no_curriculum_io() -> None:
    """Importing src.verifier must not read any curriculum files."""
    ok, stderr = _run_io_sentinel("src.verifier")
    assert ok, (
        f"Importing src.verifier triggered curriculum file I/O:\n{stderr}"
    )


def test_importing_corrector_triggers_no_curriculum_io() -> None:
    """Importing src.corrector must not read any curriculum files."""
    ok, stderr = _run_io_sentinel("src.corrector")
    assert ok, (
        f"Importing src.corrector triggered curriculum file I/O:\n{stderr}"
    )
