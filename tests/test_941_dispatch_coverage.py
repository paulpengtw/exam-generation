"""Guard-coverage test for SDK dispatch sites in src/llm_client.py (issue #941, task 2.6).

Enumerates every call site in src/llm_client.py that directly hands a request to a
provider SDK and verifies each site is either:

  - in a function that calls ``Config.dispatch_model``  (guarded), OR
  - in an explicitly exempted function with a documented reason (exempt).

Includes a negative test: verifies that the checker FAILS when the guard is removed
from ``generate_with_tools`` — the only public Anthropic dispatch path that lies
outside ``_call``.
"""
from __future__ import annotations

import ast
from pathlib import Path

# ---------------------------------------------------------------------------
# SDK call signatures to scan for.  Each tuple is the trailing attribute chain
# suffix that identifies a provider SDK dispatch call.
# ---------------------------------------------------------------------------

_SDK_SIGNATURES: tuple[tuple[str, ...], ...] = (
    ("messages", "create"),     # Anthropic SDK — messages.create(...)
    ("messages", "stream"),     # Anthropic SDK — messages.stream(...)
    ("completions", "create"),  # OpenAI / Gemini compat — chat.completions.create(...)
    ("images", "generate"),     # OpenAI images SDK — images.generate(...)
)

# ---------------------------------------------------------------------------
# Explicit exemptions — functions whose SDK dispatch does NOT require a
# dispatch_model guard, together with a mandatory documented reason.
# ---------------------------------------------------------------------------

EXEMPT: dict[str, str] = {
    "_generate_streaming": (
        "private helper — always called from guarded _call; "
        "model has already been dispatched by the caller"
    ),
    "_anthropic_call": (
        "private helper — always called from guarded _call; "
        "model has already been dispatched by the caller"
    ),
    "_openai_compat_streaming": (
        "private helper — always called from guarded _call; "
        "model has already been dispatched by the caller"
    ),
    "_openai_compat_call": (
        "private helper — always called from guarded _call; "
        "model has already been dispatched by the caller"
    ),
    "generate_image": (
        "uses IMAGE_MODEL (gpt-image2, an OpenAI model) — "
        "never a Claude/Fable id, no dispatch_model guard needed"
    ),
    "generate_with_google_search": (
        "always dispatches to the Gemini endpoint via the OpenAI-compat client; "
        "Fable is an Anthropic model id and resolve_provider would route it to Anthropic, "
        "so a Fable id cannot reach this path"
    ),
}


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _get_attr_suffix(node: ast.expr) -> tuple[str, ...]:
    """Walk an ast.Attribute chain and return the names as a tuple, innermost last.

    Example: ``self.client.messages.create`` → ``("messages", "create")``.
    """
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value  # type: ignore[assignment]
    parts.reverse()
    return tuple(parts)


class _DispatchSiteCollector(ast.NodeVisitor):
    """Collect (enclosing_fn_name, matched_signature, lineno) for each SDK dispatch call."""

    def __init__(self) -> None:
        self._fn_stack: list[str] = []
        self.sites: list[tuple[str, tuple[str, ...], int]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and self._fn_stack:
            suffix = _get_attr_suffix(node.func)
            for sig in _SDK_SIGNATURES:
                if len(suffix) >= len(sig) and suffix[-len(sig) :] == sig:
                    self.sites.append((self._fn_stack[-1], sig, node.lineno))
                    break
        self.generic_visit(node)


class _DispatchModelCallDetector(ast.NodeVisitor):
    """Detect whether a function body contains any call to Config.dispatch_model."""

    def __init__(self) -> None:
        self.found = False

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "dispatch_model":
            self.found = True
        self.generic_visit(node)


def _functions_calling_dispatch_model(tree: ast.Module) -> set[str]:
    """Return the names of all functions/methods that call dispatch_model in their body."""
    guarded: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            detector = _DispatchModelCallDetector()
            detector.visit(node)
            if detector.found:
                guarded.add(node.name)
    return guarded


# ---------------------------------------------------------------------------
# Public checker — used by both the real test and the negative "shown to fail" test
# ---------------------------------------------------------------------------


def check_dispatch_coverage(source: str) -> list[str]:
    """Return a list of violation strings for unguarded / non-exempt dispatch sites.

    Empty list means all sites are accounted for.
    """
    tree = ast.parse(source)
    guarded_fns = _functions_calling_dispatch_model(tree)

    collector = _DispatchSiteCollector()
    collector.visit(tree)

    violations: list[str] = []
    for fn_name, sig, lineno in collector.sites:
        if fn_name in guarded_fns:
            continue  # guarded — OK
        if fn_name in EXEMPT:
            continue  # explicitly exempt — OK
        sig_str = ".".join(sig)
        violations.append(
            f"Line {lineno}: {fn_name}() dispatches to SDK via .{sig_str} "
            f"but is neither guarded (calls dispatch_model) nor in EXEMPT"
        )
    return violations


_LLMCLIENT_PATH = Path(__file__).parent.parent / "src" / "llm_client.py"


# ---------------------------------------------------------------------------
# Task 2.6 — positive test: current source has no violations
# ---------------------------------------------------------------------------


def test_dispatch_coverage_passes_on_current_source() -> None:
    """All SDK dispatch sites in src/llm_client.py are either guarded or explicitly exempt."""
    source = _LLMCLIENT_PATH.read_text(encoding="utf-8")
    violations = check_dispatch_coverage(source)
    assert violations == [], (
        "Unguarded / non-exempt SDK dispatch sites found in src/llm_client.py:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Task 2.6 — negative test: checker fails when guard is removed
# ---------------------------------------------------------------------------


def test_dispatch_coverage_fails_when_generate_with_tools_guard_removed() -> None:
    """Checker catches a missing guard — shown by removing the guard from generate_with_tools.

    ``generate_with_tools`` contains both a ``dispatch_model`` call (the guard) and a
    direct ``self.client.messages.create(...)`` dispatch.  Removing the ``dispatch_model``
    call makes the function no longer guarded; the checker must report it as a violation.
    """
    source = _LLMCLIENT_PATH.read_text(encoding="utf-8")

    # Remove the dispatch_model assignment in generate_with_tools.
    # The line is unique (uses `call_model` as the lvalue, unlike the _call guard).
    guard_line = "call_model = self.config.dispatch_model(call_model)\n"
    assert source.count(guard_line) == 1, (
        f"Expected exactly one occurrence of {guard_line!r} in src/llm_client.py; "
        f"found {source.count(guard_line)}.  Update this test if the guard line changed."
    )
    modified = source.replace(guard_line, "# guard removed for coverage test\n", 1)
    assert modified != source

    # After removal, generate_with_tools should no longer be guarded
    tree = ast.parse(modified)
    guarded_after = _functions_calling_dispatch_model(tree)
    assert "generate_with_tools" not in guarded_after, (
        "generate_with_tools is still seen as guarded after guard removal — "
        "the test setup is wrong"
    )

    violations = check_dispatch_coverage(modified)
    assert any("generate_with_tools" in v for v in violations), (
        "Expected a violation naming generate_with_tools, but got:\n"
        + "\n".join(violations or ["(no violations)"])
    )
