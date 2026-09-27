#!/usr/bin/env bash
# Regenerate all server-side generation_v2 fixtures by running the real-publisher
# seam tests with GENERATE_V2_FIXTURE=1.
#
# Usage:
#   bash scripts/generate_v2_fixtures.sh
#
# After regeneration, run without GENERATE_V2_FIXTURE to verify (drift guard):
#   choom -n 500 -- uv run pytest tests/server/test_754_fixture_drift.py -q
#
# Related: tests/server/test_742_fixture.py (math single)
#          tests/server/test_744_social_fixture.py (social studies)
#          tests/server/test_745_adapter_fixtures.py (NS + math groups)
#          tests/server/test_747_abcd_fixture.py (A/B/C/D with images and omitted terminal)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Regenerating all generation_v2 fixtures under ${REPO_ROOT}/tests/fixtures/generation_v2/"

GENERATE_V2_FIXTURE=1 uv run pytest \
  tests/server/test_742_fixture.py::test_interleaved_fixture \
  tests/server/test_744_social_fixture.py \
  tests/server/test_745_adapter_fixtures.py::test_natural_sciences_real_publisher_fixture \
  tests/server/test_745_adapter_fixtures.py::test_math_real_publisher_fixture \
  tests/server/test_747_abcd_fixture.py::test_real_publisher_fixture_captures_transport_omitted_terminal \
  -v --tb=short 2>&1

echo ""
echo "==> Fixtures regenerated. Run without GENERATE_V2_FIXTURE to verify:"
echo "    choom -n 500 -- uv run pytest tests/server/test_754_fixture_drift.py -q"
