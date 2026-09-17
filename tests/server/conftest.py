"""Server test fixtures — issue #771.

Provides an autouse fixture that bypasses the build-admission gate for
tests that do not exercise it directly.  ``test_build_admission.py``
overrides the fixture locally so its route tests run the real check.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _bypass_build_admission():
    """Patch check_build_admission to a no-op for tests that don't override it.

    Tests in test_build_admission.py override this fixture locally
    (by defining a same-named fixture with scope="function") to re-enable
    the real check for their route-level assertions.
    """
    with patch(
        "server.generate.routes.check_build_admission",
        new=AsyncMock(return_value=None),
    ):
        yield
