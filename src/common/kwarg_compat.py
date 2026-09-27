"""Single mechanism for "does this callable accept optional keyword argument X?"

All call sites that need to probe whether a hook, callback, or client method
accepts a named keyword argument (e.g. ``scope``, ``content_revision``) must
use :func:`accepts_kwarg` rather than inlining their own ``inspect.signature``
check.

Design notes
------------
*   Returns ``False`` when the signature is unobtainable (e.g. some C
    extension callables raise ``TypeError`` or ``ValueError`` from
    ``inspect.signature``).  This is the safe default: we simply omit the
    extra kwarg rather than crashing.
*   Works for regular functions, methods, lambdas, ``functools.partial``
    objects, callable class instances, and built-ins (the last group returns
    ``False`` on CPython when no ``__text_signature__`` is present).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable


def accepts_kwarg(callable_: Callable, name: str) -> bool:
    """Return ``True`` if *callable_* accepts a keyword argument named *name*.

    A callable is considered accepting when it has:

    *   an explicit parameter with the given *name*, **or**
    *   a ``**kwargs`` catch-all (``VAR_KEYWORD`` kind).

    Returns ``False`` when ``inspect.signature`` raises ``TypeError`` or
    ``ValueError`` (e.g. built-in / C callable with no introspectable
    signature).

    Args:
        callable_: Any callable object.
        name: The keyword-argument name to probe.

    Returns:
        ``True`` if the callable would accept ``name`` as a keyword argument,
        ``False`` otherwise.
    """
    try:
        parameters = inspect.signature(callable_).parameters
    except (TypeError, ValueError):
        return False
    if name in parameters:
        return True
    return any(
        p.kind is inspect.Parameter.VAR_KEYWORD
        for p in parameters.values()
    )
