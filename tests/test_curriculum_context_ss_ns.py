"""Acceptance tests for CurriculumContext threading in SS and NS (issue #158).

Acceptance criteria:
  AC5 — For each subject (SS, NS), the verifier receives non-empty curriculum
         text on the normal path, and the system prompt contains a known string
         from that subject's corpus.
  AC6 — No underscore-prefixed names are imported from the subject's
         ``context_builder`` in its verifier or corrector (AST check).
         Additionally, importing SS verifier/corrector triggers no curriculum
         file I/O (subprocess check).  NS verifier/corrector cannot satisfy the
         subprocess check because ``src.natural_sciences.curriculum_codes``
         loads ``learning_content.json`` / ``learning_performance.json`` at
         import time as a pre-existing concern (code-validation lookup table);
         that module is out-of-scope for this refactor.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _fake_verifier_client(captures: dict):
    """Return a fake client that records the system prompt from generate_with_image."""

    class FakeClient:
        def generate_with_image(
            self,
            system_prompt: str,
            user_prompt: str,
            image_path=None,
            purpose="verify",
        ) -> str:
            captures.setdefault("system_prompts", []).append(system_prompt)
            return json.dumps({
                "my_answer": "foo",
                "provided_answer": "foo",
                "answer_match": True,
                "passed": True,
                "details": "ok",
            })

        def get_observer(self):
            return None

    return FakeClient()


# ---------------------------------------------------------------------------
# AC5 — curriculum text reaches SS verifier
# ---------------------------------------------------------------------------

def _make_ss_question():
    from src.social_studies.schemas import (
        ExamQuestion,
        LearningContentRef,
        SubQuestion,
    )
    sq = SubQuestion(
        id="sq1",
        序號=1,
        年級=8,
        科目=["歷史"],
        核心素養=[],
        學習內容=[LearningContentRef(編碼="歷Ka-Ⅳ-1", 說明="台灣史")],
        學習表現=[LearningContentRef(編碼="歷1a-Ⅳ-1", 說明="閱讀理解")],
        出題概念="認識台灣近代史",
        題型="選擇題",
        題目="下列何者是…？(A) A (B) B (C) C (D) D",
        答案="A",
        答案解析="選A",
        評分規準=[],
    )
    return ExamQuestion(
        id="ac5-ss",
        核心問題="台灣近代歷史發展",
        文本="台灣在近代歷史上的變遷…",
        取材來源=["教科書"],
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        閱讀歷程=["擷取訊息"],
        文本形式="連續文本—敘事文",
        題目=["請閱讀以下文本後作答"],
        正確解題分析=["選A"],
        subquestions=[sq],
    )


def test_ss_verifier_receives_curriculum_text() -> None:
    """SS verify_question must embed curriculum text in the system prompt."""
    from src.curriculum_context import build_curriculum_section, load_curriculum_context
    from src.social_studies.verifier import VERIFICATION_SYSTEM_PROMPT, verify_question

    ctx = load_curriculum_context(
        _REPO_ROOT / "data" / "social_studies" / "curriculum"
    )
    section = build_curriculum_section(ctx)
    assert section, "SS curriculum section must be non-empty"
    # "公1c-Ⅳ-1" is the first LP code in the SS learning_performance.json
    assert "公1c-Ⅳ-1" in section, "SS curriculum section must contain a known LP code"

    captures: dict = {}
    verify_question(
        _fake_verifier_client(captures),
        _make_ss_question(),
        curriculum_context=ctx,
    )
    system_prompt = captures["system_prompts"][0]
    assert section in system_prompt, (
        "SS verifier system prompt does not contain the expected curriculum section"
    )
    assert system_prompt != VERIFICATION_SYSTEM_PROMPT, (
        "SS verifier system prompt must differ from the bare VERIFICATION_SYSTEM_PROMPT "
        "when curriculum_context is provided"
    )


# ---------------------------------------------------------------------------
# AC5 — curriculum text reaches NS verifier
# ---------------------------------------------------------------------------

def _make_ns_question():
    from src.natural_sciences.schemas import (
        ExamQuestion,
        LearningContentRef,
        SubQuestion,
    )
    _competency = "能力一：以科學的角度解釋現象"
    sq = SubQuestion(
        id="sq1",
        序號=1,
        年級=8,
        科目=["自然科學"],
        科學能力=[_competency],
        核心素養=[],
        學習內容=[LearningContentRef(編碼="INc-IV-1", 說明="物質分類")],
        學習表現=[LearningContentRef(編碼="tr-IV-1", 說明="推理")],
        出題概念="物質特性",
        題型="Simple multiple-choice",
        題目="下列何者是金屬？(A) 木頭 (B) 鐵 (C) 塑膠 (D) 玻璃",
        答案="B",
        答案解析="鐵是金屬",
        評分規準=[],
    )
    return ExamQuestion(
        id="ac5-ns",
        核心問題="物質的基本性質",
        文本="物質由原子組成…",
        取材來源=["教科書"],
        情境=["Personal"],
        情境子類別=None,
        題型種類="題組題",
        題型="Simple multiple-choice",
        科學能力=[_competency],
        題目=["請閱讀以下科學情境後作答"],
        正確解題分析=["B"],
        subquestions=[sq],
    )


def test_ns_verifier_receives_curriculum_text() -> None:
    """NS verify_question must embed curriculum text in the system prompt."""
    from src.curriculum_context import build_curriculum_section, load_curriculum_context
    from src.natural_sciences.verifier import VERIFICATION_SYSTEM_PROMPT, verify_question

    ctx = load_curriculum_context(
        _REPO_ROOT / "data" / "natural_sciences" / "curriculum"
    )
    section = build_curriculum_section(ctx)
    assert section, "NS curriculum section must be non-empty"
    # "ti-Ⅱ-1" is the first LP code in the NS learning_performance.json
    assert "ti-Ⅱ-1" in section, "NS curriculum section must contain a known LP code"

    captures: dict = {}
    verify_question(
        _fake_verifier_client(captures),
        _make_ns_question(),
        curriculum_context=ctx,
    )
    system_prompt = captures["system_prompts"][0]
    assert section in system_prompt, (
        "NS verifier system prompt does not contain the expected curriculum section"
    )
    assert system_prompt != VERIFICATION_SYSTEM_PROMPT, (
        "NS verifier system prompt must differ from the bare VERIFICATION_SYSTEM_PROMPT "
        "when curriculum_context is provided"
    )


# ---------------------------------------------------------------------------
# AC6 — AST: no private context_builder imports in SS or NS verifier/corrector
# ---------------------------------------------------------------------------

def _collect_private_subject_context_builder_imports(
    source_path: Path, subject_module: str
) -> list[str]:
    """Return names imported from ``{subject_module}.context_builder`` that start with '_'."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    bad: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if module != f"{subject_module}.context_builder":
            continue
        for alias in node.names:
            if alias.name.startswith("_"):
                bad.append(alias.name)
    return bad


def test_ss_verifier_no_private_context_builder_imports() -> None:
    """src/social_studies/verifier.py must not import private names from context_builder."""
    path = _REPO_ROOT / "src" / "social_studies" / "verifier.py"
    bad = _collect_private_subject_context_builder_imports(path, "src.social_studies")
    assert bad == [], (
        f"src/social_studies/verifier.py imports private names from context_builder: {bad}"
    )


def test_ss_corrector_no_private_context_builder_imports() -> None:
    """src/social_studies/corrector.py must not import private names from context_builder."""
    path = _REPO_ROOT / "src" / "social_studies" / "corrector.py"
    bad = _collect_private_subject_context_builder_imports(path, "src.social_studies")
    assert bad == [], (
        f"src/social_studies/corrector.py imports private names from context_builder: {bad}"
    )


def test_ns_verifier_no_private_context_builder_imports() -> None:
    """src/natural_sciences/verifier.py must not import private names from context_builder."""
    path = _REPO_ROOT / "src" / "natural_sciences" / "verifier.py"
    bad = _collect_private_subject_context_builder_imports(path, "src.natural_sciences")
    assert bad == [], (
        f"src/natural_sciences/verifier.py imports private names from context_builder: {bad}"
    )


def test_ns_corrector_no_private_context_builder_imports() -> None:
    """src/natural_sciences/corrector.py must not import private names from context_builder."""
    path = _REPO_ROOT / "src" / "natural_sciences" / "corrector.py"
    bad = _collect_private_subject_context_builder_imports(path, "src.natural_sciences")
    assert bad == [], (
        f"src/natural_sciences/corrector.py imports private names from context_builder: {bad}"
    )


# ---------------------------------------------------------------------------
# AC6 — subprocess: importing SS verifier/corrector triggers no curriculum I/O
# (NS verifier/corrector are excluded: curriculum_codes loads at import time
# as a pre-existing concern unrelated to issue #158)
# ---------------------------------------------------------------------------

_CORPUS_FILES = (
    "learning_content.json",
    "learning_performance.json",
    "learning_performance_intro.md",
)

_IO_SENTINEL_TEMPLATE = """\
import sys, builtins, pathlib

_CORPUS_FILES = {corpus_files!r}
_READS: list[str] = []
_orig_open = builtins.open
_orig_path_open = pathlib.Path.open

def _patched_open(file, *args, **kwargs):
    path_str = str(file).replace("\\\\\\\\", "/")
    if any(path_str.endswith(f) for f in _CORPUS_FILES):
        _READS.append(str(file))
    return _orig_open(file, *args, **kwargs)

def _patched_path_open(self, *args, **kwargs):
    path_str = str(self).replace("\\\\\\\\", "/")
    if any(path_str.endswith(f) for f in _CORPUS_FILES):
        _READS.append(str(self))
    return _orig_path_open(self, *args, **kwargs)

builtins.open = _patched_open
pathlib.Path.open = _patched_path_open

import {module}

if _READS:
    print("CURRICULUM_IO_DETECTED:" + repr(_READS), file=sys.stderr)
    sys.exit(1)
"""


def _run_io_sentinel(module_dotpath: str) -> tuple[bool, str]:
    script = _IO_SENTINEL_TEMPLATE.format(
        corpus_files=_CORPUS_FILES,
        module=module_dotpath,
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=30,
    )
    return result.returncode == 0, result.stderr


def test_importing_ss_verifier_triggers_no_curriculum_io() -> None:
    """Importing src.social_studies.verifier must not read curriculum files."""
    ok, stderr = _run_io_sentinel("src.social_studies.verifier")
    assert ok, (
        f"Importing src.social_studies.verifier triggered curriculum I/O:\n{stderr}"
    )


def test_importing_ss_corrector_triggers_no_curriculum_io() -> None:
    """Importing src.social_studies.corrector must not read curriculum files."""
    ok, stderr = _run_io_sentinel("src.social_studies.corrector")
    assert ok, (
        f"Importing src.social_studies.corrector triggered curriculum I/O:\n{stderr}"
    )


# ---------------------------------------------------------------------------
# AC7 — CLI path: generate_with_corrections receives a non-None curriculum_context
# ---------------------------------------------------------------------------

def test_ss_cli_generate_with_corrections_receives_curriculum_context(
    monkeypatch,
) -> None:
    """SS generate_with_corrections called from main() must pass curriculum_context."""
    import src.social_studies.cli as ss_cli
    from src.curriculum_context import CurriculumContext

    captured: dict = {}

    _orig_gwc = ss_cli.generate_with_corrections

    def _fake_gwc(*args, **kwargs):
        captured["curriculum_context"] = kwargs.get("curriculum_context")
        # Return a string so main() hits the dry_run short-circuit.
        return "dry-run output"

    monkeypatch.setattr(ss_cli, "generate_with_corrections", _fake_gwc)

    test_args = [
        "ss-cli",
        "generate",
        "--dry-run",
        "--count", "1",
        "--grade", "8",
    ]
    monkeypatch.setattr("sys.argv", test_args)

    try:
        ss_cli.main()
    except SystemExit:
        pass

    assert "curriculum_context" in captured, (
        "SS main() did not call generate_with_corrections"
    )
    ctx = captured["curriculum_context"]
    assert isinstance(ctx, CurriculumContext), (
        f"SS main() passed curriculum_context={ctx!r}; expected a CurriculumContext"
    )
    assert ctx.content_text or ctx.performance_text, (
        "SS curriculum_context must have non-empty content or performance text"
    )
    # SS includes intro text (learning_performance_intro.md exists)
    assert ctx.intro_text, (
        "SS curriculum_context must have non-empty intro_text (learning_performance_intro.md)"
    )


def test_ns_cli_generate_with_corrections_receives_curriculum_context(
    monkeypatch,
) -> None:
    """NS generate_with_corrections called from main() must pass curriculum_context."""
    import src.natural_sciences.cli as ns_cli
    from src.curriculum_context import CurriculumContext

    captured: dict = {}

    def _fake_gwc(*args, **kwargs):
        captured["curriculum_context"] = kwargs.get("curriculum_context")
        # Return a string so main() hits the dry_run short-circuit.
        return "dry-run output"

    monkeypatch.setattr(ns_cli, "generate_with_corrections", _fake_gwc)

    test_args = [
        "ns-cli",
        "generate",
        "--dry-run",
        "--count", "1",
        "--grade", "8",
    ]
    monkeypatch.setattr("sys.argv", test_args)

    try:
        ns_cli.main()
    except SystemExit:
        pass

    assert "curriculum_context" in captured, (
        "NS main() did not call generate_with_corrections"
    )
    ctx = captured["curriculum_context"]
    assert isinstance(ctx, CurriculumContext), (
        f"NS main() passed curriculum_context={ctx!r}; expected a CurriculumContext"
    )
    assert ctx.content_text or ctx.performance_text, (
        "NS curriculum_context must have non-empty content or performance text"
    )
    # NS does NOT include intro text (no learning_performance_intro.md)
    assert not ctx.intro_text, (
        "NS curriculum_context must have empty intro_text (no learning_performance_intro.md)"
    )
