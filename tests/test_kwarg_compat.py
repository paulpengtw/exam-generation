"""Unit tests for src.common.kwarg_compat.accepts_kwarg.

Acceptance criteria (issue #856):
  - Explicit parameter -> True
  - **kwargs catch-all  -> True
  - Not accepted        -> False
  - Signature unobtainable (builtins / C callables that raise ValueError/TypeError) -> False
  - Nested-binding: a functools.partial that already bound 'scope' does NOT receive
    it a second time when passed through _callback_with_optional_scope.
"""
from __future__ import annotations

import functools

from src.common.kwarg_compat import accepts_kwarg

# ---------------------------------------------------------------------------
# Four core cases
# ---------------------------------------------------------------------------

def test_accepts_kwarg_explicit_param() -> None:
    """Function with an explicit named parameter -> True."""

    def fn(x: int, scope=None) -> None:
        pass

    assert accepts_kwarg(fn, "scope") is True


def test_accepts_kwarg_var_keyword() -> None:
    """Function that accepts **kwargs -> True for any name."""

    def fn(**kwargs: object) -> None:
        pass

    assert accepts_kwarg(fn, "scope") is True
    assert accepts_kwarg(fn, "content_revision") is True


def test_accepts_kwarg_not_accepted() -> None:
    """Function with no matching parameter -> False."""

    def fn(x: int) -> None:
        pass

    assert accepts_kwarg(fn, "scope") is False


def test_accepts_kwarg_signature_unobtainable_value_error() -> None:
    """When inspect.signature raises ValueError -> False (no crash)."""
    import src.common.kwarg_compat as mod

    original_sig = mod.inspect.signature  # type: ignore[attr-defined]

    def _raise_value_error(*args: object, **kwargs: object) -> None:
        raise ValueError("no signature available")

    mod.inspect.signature = _raise_value_error  # type: ignore[attr-defined]
    try:

        def fn(x: int) -> None:
            pass

        assert accepts_kwarg(fn, "scope") is False
    finally:
        mod.inspect.signature = original_sig  # type: ignore[attr-defined]


def test_accepts_kwarg_signature_unobtainable_type_error() -> None:
    """When inspect.signature raises TypeError -> False (no crash)."""
    import src.common.kwarg_compat as mod

    original_sig = mod.inspect.signature  # type: ignore[attr-defined]

    def _raise_type_error(*args: object, **kwargs: object) -> None:
        raise TypeError("unsupported callable")

    mod.inspect.signature = _raise_type_error  # type: ignore[attr-defined]
    try:

        def fn(x: int) -> None:
            pass

        assert accepts_kwarg(fn, "scope") is False
    finally:
        mod.inspect.signature = original_sig  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Nested-binding: scope must NOT be passed twice
# ---------------------------------------------------------------------------

def test_nested_binding_does_not_pass_scope_twice() -> None:
    """_callback_with_optional_scope must not inject scope when already bound.

    _scoped_callback wraps a callback and pops any inherited 'scope' kwarg
    before forwarding.  Applying _scoped_callback twice must result in exactly
    one scope reaching the leaf callback.
    """
    from src.common.generation_core import _scoped_callback
    from src.common.generation_events import QuestionContext, new_operation_scope

    received: list[object] = []

    def leaf(entry: object, *, scope=None) -> None:
        received.append(scope)

    question = QuestionContext(run_id="RUN", question_id="q-1", index=0)
    scope = new_operation_scope(question, kind="image")

    # Double-wrap: outer binding over an already-scoped inner wrapper
    inner = _scoped_callback(leaf, scope)
    outer = _scoped_callback(inner, scope)

    outer("entry")

    # The leaf should have seen exactly one scope, not two bindings
    assert received == [scope]


def test_nested_partial_binding_does_not_pass_scope_twice() -> None:
    """A functools.partial that already binds scope= must not receive it again.

    If a caller wraps a callback with functools.partial(cb, scope=s) and then
    _callback_with_optional_scope tries to inject scope again, Python raises
    TypeError for duplicate keyword argument.  accepts_kwarg must detect that
    the partial's underlying __wrapped__/func already has scope bound.
    """
    from src.common.generation_core import _callback_with_optional_scope
    from src.common.generation_events import QuestionContext, new_operation_scope

    question = QuestionContext(run_id="RUN", question_id="q-2", index=1)
    scope = new_operation_scope(question, kind="subquestion", subquestion_index=0)

    received: list[object] = []

    def leaf(entry: object, *, scope=None) -> None:
        received.append(scope)

    # Partial that already supplies scope -> calling _callback_with_optional_scope
    # should not inject scope a second time (that would be a TypeError).
    already_bound = functools.partial(leaf, scope=scope)

    # Should not raise; leaf receives exactly the bound scope
    _callback_with_optional_scope(already_bound, "entry", scope=scope)

    assert received == [scope]
