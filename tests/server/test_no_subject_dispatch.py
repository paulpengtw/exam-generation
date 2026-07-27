"""Structural guard: no subject-string if/elif chains may exist in server/.

Issue #156 eliminates all ``if subject == "math"`` / ``== "social_studies"`` /
``== "natural_sciences"`` comparisons from the server tier and routes every
dispatch through the SubjectSpec registry in server/generate/subjects.py.

This test enforces that constraint so a future addition cannot sneak a new
if/elif chain past code review.

The allowlist names the ONE file that legitimately contains the subject string
literals (the registry).  Any other file that introduces a comparison against
these literals will fail this test.
"""
from __future__ import annotations

import re
from pathlib import Path

# Absolute path to the server directory under test.
SERVER_DIR = Path(__file__).parent.parent.parent / "server"

# The single file permitted to contain subject-key string literals.
REGISTRY_FILE = SERVER_DIR / "generate" / "subjects.py"

# Literals to look for — these are the canonical subject keys.
_SUBJECT_LITERALS = frozenset({"math", "social_studies", "natural_sciences"})

# Regex that matches a string comparison of the form:
#   == "math"   != "social_studies"   == 'natural_sciences'   etc.
# This catches ``subject == "math"`` without false-positives on dict-key
# literals such as ``{"math": ...}`` or function-call arguments.
_COMPARISON_RE = re.compile(
    r"""[!=]=\s*['"](?:math|social_studies|natural_sciences)['"]"""
    r"""|['"](?:math|social_studies|natural_sciences)['"]\s*[!=]=""",
    re.VERBOSE,
)


def _find_comparison_violations(path: Path) -> list[int]:
    """Return 1-based line numbers where a subject-string comparison is found."""
    source = path.read_text(encoding="utf-8")
    violations: list[int] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        if _COMPARISON_RE.search(line):
            violations.append(lineno)
    return violations


def test_no_subject_comparisons_outside_registry() -> None:
    """All server/*.py files except subjects.py must have zero subject-string
    comparisons."""
    py_files = sorted(SERVER_DIR.rglob("*.py"))
    assert py_files, "No .py files found under server/ — check SERVER_DIR path"

    violations: dict[str, list[int]] = {}
    for py_file in py_files:
        if py_file == REGISTRY_FILE:
            continue  # The registry itself is allowed to contain subject keys.
        lines = _find_comparison_violations(py_file)
        if lines:
            rel = py_file.relative_to(SERVER_DIR.parent)
            violations[str(rel)] = lines

    if violations:
        detail = "\n".join(
            f"  {path}: lines {lines}" for path, lines in sorted(violations.items())
        )
        raise AssertionError(
            "Subject-string comparisons found outside the registry file "
            f"({REGISTRY_FILE.relative_to(SERVER_DIR.parent)}):\n{detail}\n"
            "Move dispatch logic into SUBJECTS[key] instead of if/elif chains."
        )


def test_registry_file_contains_all_three_subjects() -> None:
    """The registry module must define a key for each canonical subject."""
    source = REGISTRY_FILE.read_text(encoding="utf-8")
    for subject in _SUBJECT_LITERALS:
        assert f'"{subject}"' in source or f"'{subject}'" in source, (
            f"Registry file missing subject key '{subject}'"
        )


def test_allowed_subjects_derived_from_registry() -> None:
    """ALLOWED_SUBJECTS in models.py must match the SUBJECTS registry keys."""
    from server.generate.models import ALLOWED_SUBJECTS
    from server.generate.subjects import SUBJECTS

    assert ALLOWED_SUBJECTS == frozenset(SUBJECTS.keys()), (
        f"ALLOWED_SUBJECTS {ALLOWED_SUBJECTS!r} does not match "
        f"SUBJECTS keys {set(SUBJECTS.keys())!r}"
    )


def test_unknown_subject_raises_via_registry() -> None:
    """SUBJECTS[unknown] must raise KeyError — no silent fall-through to math."""
    from server.generate.subjects import SUBJECTS

    try:
        _ = SUBJECTS["unknown_subject"]
        raise AssertionError("Expected KeyError for unknown subject key")
    except KeyError:
        pass
