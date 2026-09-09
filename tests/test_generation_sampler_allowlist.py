"""Static guards for the full-pre-draw sampler and RNG boundary."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

ALLOWLIST_LOCATION = "tests/test_generation_sampler_allowlist.py:RNG_ALLOWLIST"

# These are the only modules that are allowed to implement resolver sampling.
# Every random stream or draw anywhere else must be an explicitly justified
# prompt-only 參考範例 use below.
RESOLVER_MODULES = frozenset(
    {
        "src/common/resolver.py",
        "src/common/randomness.py",
        "src/sampler.py",
        "src/social_studies/sampler.py",
        "src/natural_sciences/sampler.py",
    }
)


@dataclass(frozen=True)
class RngAllowlistEntry:
    file: str
    symbol: str
    line_pattern: str
    reason: str

    def matches(self, use: "RngUse") -> bool:
        return (
            self.file == use.file
            and self.symbol == use.symbol
            and re.search(self.line_pattern, use.source_line.strip()) is not None
        )


@dataclass(frozen=True)
class RngUse:
    file: str
    lineno: int
    symbol: str
    expression: str
    source_line: str


# Each entry names one prompt-only 參考範例 draw.  These are the sole deliberate
# non-resolver RNG uses under ADR 0018; the line patterns are intentionally
# narrow so a new draw in the same function is not silently covered.
RNG_ALLOWLIST: tuple[RngAllowlistEntry, ...] = (
    RngAllowlistEntry(
        "src/context_builder.py",
        "build_user_prompt",
        r"selected = rng\.sample\(flat_examples, sample_count\)",
        "seeded prompt-only 參考範例 pick; it is not an item parameter (ADR 0018); disclosed as 參考範例紀錄",
    ),
    RngAllowlistEntry(
        "src/context_builder.py",
        "_math_group_few_shot_text",
        r"selected = rng\.sample\(flattened, min\(2, len\(flattened\)\)\)",
        "seeded prompt-only 參考範例 pick; it is not an item parameter (ADR 0018); disclosed as 參考範例紀錄",
    ),
    RngAllowlistEntry(
        "src/social_studies/context_builder.py",
        "build_user_prompt",
        r"selected_groups = rng\.sample\(example_groups, sample_count\)",
        "seeded prompt-only 參考範例 group pick; it is not an item parameter (ADR 0018); disclosed as 參考範例紀錄",
    ),
    RngAllowlistEntry(
        "src/social_studies/context_builder.py",
        "build_user_prompt",
        r"selected = \[rng\.choice\(group\) for group in selected_groups\]",
        "seeded prompt-only 參考範例 pick; it is not an item parameter (ADR 0018); disclosed as 參考範例紀錄",
    ),
    RngAllowlistEntry(
        "src/social_studies/context_builder.py",
        "build_subquestion_user_prompt",
        r"ex = rng\.choice\(matching_examples or fallback_examples\)",
        "seeded prompt-only 參考範例 pick; it is not an item parameter (ADR 0018); disclosed as 參考範例紀錄",
    ),
    RngAllowlistEntry(
        "src/social_studies/context_builder.py",
        "build_subquestion_user_prompt",
        r"rng\.choice\(process_exemplars\)",
        "seeded prompt-only 參考範例 pick; it is not an item parameter (ADR 0018); disclosed as 參考範例紀錄",
    ),
    RngAllowlistEntry(
        "src/natural_sciences/context_builder.py",
        "build_user_prompt",
        r"selected_groups = rng\.sample\(example_groups, sample_count\)",
        "seeded prompt-only 參考範例 group pick; it is not an item parameter (ADR 0018); disclosed as 參考範例紀錄",
    ),
    RngAllowlistEntry(
        "src/natural_sciences/context_builder.py",
        "build_user_prompt",
        r"selected = \[rng\.choice\(group\) for group in selected_groups\]",
        "seeded prompt-only 參考範例 pick; it is not an item parameter (ADR 0018); disclosed as 參考範例紀錄",
    ),
    RngAllowlistEntry(
        "src/natural_sciences/context_builder.py",
        "build_subquestion_user_prompt",
        r"selected_group = rng\.choice\(example_groups\)",
        "seeded prompt-only 參考範例 group pick; it is not an item parameter (ADR 0018); disclosed as 參考範例紀錄",
    ),
    RngAllowlistEntry(
        "src/natural_sciences/context_builder.py",
        "build_subquestion_user_prompt",
        r"ex = rng\.choice\(selected_group\)",
        "seeded prompt-only 參考範例 pick; it is not an item parameter (ADR 0018); disclosed as 參考範例紀錄",
    ),
)


def _project_sources(root: Path) -> list[tuple[str, str, ast.AST]]:
    sources: list[tuple[str, str, ast.AST]] = []
    for source_root_name in ("src", "server"):
        source_root = root / source_root_name
        if not source_root.exists():
            continue
        for path in sorted(source_root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            relative_path = path.relative_to(root).as_posix()
            sources.append((relative_path, source, ast.parse(source, filename=relative_path)))
    return sources


def _root_name(node: ast.AST) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


class _RngVisitor(ast.NodeVisitor):
    """Find actual random draws, retaining only source facts needed by the guard."""

    def __init__(self, source: str) -> None:
        self._source_lines = source.splitlines()
        self._function_stack: list[str] = []
        self._rng_names: set[str] = {"rng"}
        self._random_module_names: set[str] = {"random"}
        self._random_constructor_names: set[str] = {"Random"}
        self.uses: list[RngUse] = []

    def _symbol(self) -> str:
        return self._function_stack[-1] if self._function_stack else "<module>"

    def _line(self, node: ast.Call) -> str:
        if 1 <= node.lineno <= len(self._source_lines):
            return self._source_lines[node.lineno - 1]
        return ""

    def _record(self, node: ast.Call, expression: str) -> None:
        self.uses.append(
            RngUse(
                file="",
                lineno=node.lineno,
                symbol=self._symbol(),
                expression=expression,
                source_line=self._line(node),
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "random":
                self._random_module_names.add(alias.asname or "random")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "random":
            for alias in node.names:
                if alias.name == "Random":
                    self._random_constructor_names.add(alias.asname or "Random")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _is_random_annotation(self, node: ast.AST | None) -> bool:
        return (
            isinstance(node, ast.Name)
            and node.id in self._random_constructor_names
        ) or (
            isinstance(node, ast.Attribute)
            and node.attr == "Random"
            and isinstance(node.value, ast.Name)
            and node.value.id in self._random_module_names
        )

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for argument in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            if argument.arg == "rng" or argument.arg.endswith("_rng") or self._is_random_annotation(
                argument.annotation
            ):
                self._rng_names.add(argument.arg)
        if node.args.vararg and node.args.vararg.arg == "rng":
            self._rng_names.add(node.args.vararg.arg)
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def _targets(self, node: ast.AST) -> list[str]:
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, (ast.Tuple, ast.List)):
            return [name for item in node.elts for name in self._targets(item)]
        return []

    def _is_rng_factory(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        if isinstance(node.func, ast.Name):
            return node.func.id in self._random_constructor_names or node.func.id == "draw_rng"
        return (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "Random"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in self._random_module_names
        )

    def _is_rng_expression(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self._rng_names or node.id.endswith("_rng")
        if isinstance(node, ast.Call):
            return self._is_rng_factory(node)
        if isinstance(node, ast.Attribute):
            return self._is_rng_expression(node.value)
        return False

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._is_rng_expression(node.value):
            self._rng_names.update(
                name for target in node.targets for name in self._targets(target)
            )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None and self._is_rng_expression(node.value):
            self._rng_names.update(self._targets(node.target))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        if isinstance(function, ast.Name):
            if function.id == "draw_rng":
                self._record(node, "draw_rng(...)")
            # Random(...) creates a stream. Its derived method calls are recorded
            # separately; constructing a stream is not itself an item draw.
        elif isinstance(function, ast.Attribute):
            root = _root_name(function.value)
            if root in self._random_module_names and function.attr != "Random":
                self._record(node, f"{root}.{function.attr}(...)")
            elif self._is_rng_expression(function.value):
                expression = (
                    f"{root}.{function.attr}(...)"
                    if root is not None
                    else f"{ast.unparse(function)}(...)"
                )
                self._record(node, expression)
        self.generic_visit(node)


def _rng_uses(root: Path) -> list[RngUse]:
    uses: list[RngUse] = []
    for relative_path, source, tree in _project_sources(root):
        if relative_path in RESOLVER_MODULES:
            continue
        visitor = _RngVisitor(source)
        visitor.visit(tree)
        uses.extend(
            RngUse(
                file=relative_path,
                lineno=use.lineno,
                symbol=use.symbol,
                expression=use.expression,
                source_line=use.source_line,
            )
            for use in visitor.uses
        )
    return uses


def _unallowlisted_rng_uses(
    root: Path,
    allowlist: tuple[RngAllowlistEntry, ...] = RNG_ALLOWLIST,
) -> list[RngUse]:
    return [use for use in _rng_uses(root) if not any(entry.matches(use) for entry in allowlist)]


def _allowlist_integrity_failures(
    root: Path,
    allowlist: tuple[RngAllowlistEntry, ...] = RNG_ALLOWLIST,
) -> list[str]:
    """Reject stale, duplicate, or multiply-covered allowlist entries."""
    uses = _rng_uses(root)
    failures: list[str] = []
    for entry in allowlist:
        matches = [use for use in uses if entry.matches(use)]
        if not matches:
            failures.append(f"stale entry {entry!r} in {ALLOWLIST_LOCATION}")
        elif len(matches) > 1:
            locations = ", ".join(f"{use.file}:{use.lineno}" for use in matches)
            failures.append(
                f"entry {entry!r} in {ALLOWLIST_LOCATION} matches multiple uses: {locations}"
            )
    for use in uses:
        matches = [entry for entry in allowlist if entry.matches(use)]
        if len(matches) > 1:
            failures.append(
                f"{use.file}:{use.lineno} is covered by multiple entries in {ALLOWLIST_LOCATION}"
            )
    return failures


def _format_rng_failures(uses: list[RngUse]) -> str:
    return "\n".join(
        f"{use.file}:{use.lineno} ({use.symbol}) {use.expression} has no matching "
        f"entry in {ALLOWLIST_LOCATION}"
        for use in uses
    )


def _assert_rng_allowlist(
    root: Path,
    allowlist: tuple[RngAllowlistEntry, ...] = RNG_ALLOWLIST,
) -> None:
    violations = _unallowlisted_rng_uses(root, allowlist)
    integrity_failures = _allowlist_integrity_failures(root, allowlist)
    messages = [_format_rng_failures(violations), *integrity_failures]
    assert not violations and not integrity_failures, "\n".join(
        message for message in messages if message
    )


@dataclass(frozen=True)
class SampleParamsCall:
    file: str
    lineno: int
    symbol: str
    name: str
    in_resolve_scope: bool


class _SampleParamsVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self._function_stack: list[str] = []
        self.calls: list[tuple[int, str, str, bool]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        name = (
            function.id
            if isinstance(function, ast.Name)
            else function.attr
            if isinstance(function, ast.Attribute)
            else ""
        )
        if (
            name == "sample_params"
            or name.endswith("sample_params")
            or (name.startswith("sample_") and name.endswith("params"))
        ):
            symbol = ".".join(self._function_stack) if self._function_stack else "<module>"
            in_resolve_scope = any(
                function_name == "resolve" or function_name.startswith("_resolve")
                for function_name in self._function_stack
            )
            self.calls.append((node.lineno, symbol, name, in_resolve_scope))
        self.generic_visit(node)


def _sample_params_calls(root: Path) -> list[SampleParamsCall]:
    calls: list[SampleParamsCall] = []
    for relative_path, _source, tree in _project_sources(root):
        visitor = _SampleParamsVisitor()
        visitor.visit(tree)
        calls.extend(
            SampleParamsCall(relative_path, lineno, symbol, name, in_resolve_scope)
            for lineno, symbol, name, in_resolve_scope in visitor.calls
        )
    return calls


def _sample_params_call_violations(root: Path) -> list[SampleParamsCall]:
    violations: list[SampleParamsCall] = []
    for call in _sample_params_calls(root):
        in_resolver = call.file == "src/common/resolver.py"
        if not (in_resolver and call.in_resolve_scope):
            violations.append(call)
    return violations


def _sampler_call_files(root: Path) -> list[str]:
    """Compatibility helper retained from #608, now rooted for synthetic tests."""
    return [call.file for call in _sample_params_calls(root)]


def _format_sample_params_failures(calls: list[SampleParamsCall]) -> str:
    return "\n".join(
        f"{call.file}:{call.lineno} ({call.symbol}) calls {call.name}; "
        "sample_params may only be called from the resolver's resolve path"
        for call in calls
    )


def _assert_sample_params_call_sites(root: Path) -> None:
    violations = _sample_params_call_violations(root)
    assert not violations, _format_sample_params_failures(violations)


def _write_synthetic_source(root: Path, relative_path: str, source: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_generation_path_only_resolver_calls_sample_params() -> None:
    """Generation must consume the resolver payload without drawing again."""
    _assert_sample_params_call_sites(Path("."))
    assert _sampler_call_files(Path("."))


def test_rng_uses_are_allowlisted() -> None:
    """All non-resolver random draws must be justified by the ADR carve-out."""
    _assert_rng_allowlist(Path("."))


def test_allowlist_entries_are_live_and_have_one_line_reasons() -> None:
    integrity_failures = _allowlist_integrity_failures(Path("."))
    malformed = [
        entry
        for entry in RNG_ALLOWLIST
        if (
            entry.file in RESOLVER_MODULES
            or not entry.reason.strip()
            or "\n" in entry.reason
        )
    ]

    assert not integrity_failures, "\n".join(integrity_failures)
    assert not malformed, f"entries in {ALLOWLIST_LOCATION} need one-line reasons: {malformed!r}"


def test_synthetic_unallowlisted_rng_call_names_file_line_and_allowlist(tmp_path: Path) -> None:
    _write_synthetic_source(
        tmp_path,
        "src/context_builder.py",
        "import random\n\n"
        "def build_user_prompt(rng):\n"
        "    return rng.choice(['an item parameter'])\n",
    )

    with pytest.raises(AssertionError) as exc_info:
        _assert_rng_allowlist(tmp_path)

    message = str(exc_info.value)
    assert "src/context_builder.py:4" in message
    assert "tests/test_generation_sampler_allowlist.py:RNG_ALLOWLIST" in message


def test_synthetic_random_derived_stream_is_checked(tmp_path: Path) -> None:
    _write_synthetic_source(
        tmp_path,
        "src/context_builder.py",
        "from random import Random\n\n"
        "def build_prompt():\n"
        "    stream = Random(7)\n"
        "    return stream.shuffle([])\n",
    )

    with pytest.raises(AssertionError) as exc_info:
        _assert_rng_allowlist(tmp_path)

    assert "stream.shuffle(...)" in str(exc_info.value)


def test_synthetic_sample_params_call_outside_resolve_is_reported(tmp_path: Path) -> None:
    _write_synthetic_source(
        tmp_path,
        "src/generator.py",
        "from src.sampler import sample_params\n\n"
        "def generate():\n"
        "    return sample_params()\n",
    )

    with pytest.raises(AssertionError) as exc_info:
        _assert_sample_params_call_sites(tmp_path)

    message = str(exc_info.value)
    assert "src/generator.py:4" in message
    assert "sample_params" in message
