"""Pytest configuration for exam-generation tests."""

import os
import sys
from pathlib import Path

# A TestClient lifespan must never start a real 生成執行 host loop: route tests
# create queued runs that no test expects to execute. Tests that need the loop
# drive run_host_loop directly.
os.environ.setdefault("GENERATION_HOST_ENABLED", "0")

# Add project root to sys.path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

pytest_plugins = [
    "tests.plugins.playwright_browser",
    "tests.plugins.postgres_db",
]
