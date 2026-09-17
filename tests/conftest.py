"""Pytest configuration for exam-generation tests."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add project root to sys.path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

pytest_plugins = ["tests.plugins.playwright_browser"]


@pytest.fixture(autouse=True)
def _bypass_build_admission():
    """Patch check_build_admission to a no-op for tests that don't exercise it.

    Tests in tests/server/test_build_admission.py override this fixture locally
    (by defining a same-named fixture that yields without the patch) so their
    route-level assertions run the real check.
    """
    try:
        with patch("server.generate.routes.check_build_admission", return_value=None):
            yield
    except (ImportError, AttributeError):
        # server module not importable in non-web test environments
        yield
