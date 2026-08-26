"""Guard the completeness gate's generation-time sampler boundary."""

from __future__ import annotations

import ast
from pathlib import Path


def _sampler_call_files() -> list[str]:
    roots = [Path("src"), Path("server")]
    calls: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                name = (
                    function.id
                    if isinstance(function, ast.Name)
                    else function.attr
                    if isinstance(function, ast.Attribute)
                    else ""
                )
                if name == "sample_params" or (
                    name.startswith("sample_") and name.endswith("params")
                ):
                    calls.append(str(path))
    return calls


def test_generation_path_only_resolver_calls_sample_params() -> None:
    """Generation must consume the resolver payload without drawing again."""
    calls = _sampler_call_files()
    assert calls
    assert set(calls) <= {"src/common/resolver.py"}
