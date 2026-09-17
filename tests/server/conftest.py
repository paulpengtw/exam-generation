"""Server test fixtures — issue #771.

Provides an autouse fixture that bypasses the build-admission gate for
tests that do not exercise it directly.  ``test_build_admission.py``
overrides the fixture locally so its route tests run the real check.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

_DEFAULT_POLICY = {
    "schema": "exam-generation.release-policy/1",
    "environment": "production",
    "release_revision": 1,
    "released_build_id": "test-build-x",
    "admission": "open",
    "supported_recovery_formats": [],
}

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "web" / "dist" / "release" / "policy.json"
)


@pytest.fixture(scope="session", autouse=True)
def _default_release_policy_fixture() -> None:
    """Write the default policy fixture if it doesn't already exist."""
    _FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _FIXTURE_PATH.exists():
        _FIXTURE_PATH.write_text(json.dumps(_DEFAULT_POLICY), encoding="utf-8")


@pytest.fixture(autouse=True)
def _bypass_build_admission():
    """Patch check_build_admission to a no-op for tests that don't override it.

    Tests in test_build_admission.py override this fixture locally
    (by defining a same-named fixture with scope="function") to re-enable
    the real check for their route-level assertions.
    """
    with patch("server.generate.routes.check_build_admission", return_value=None):
        yield
