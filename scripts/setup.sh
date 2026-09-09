#!/usr/bin/env bash
# scripts/setup.sh — Bootstrap the Python environment and Playwright browser.
#
# Usage:
#   bash scripts/setup.sh           # Python-only (uv sync + playwright install chromium)
#   bash scripts/setup.sh --web     # Full-stack (also runs npm --prefix web install)
#
# The script is idempotent: `uv sync` is a no-op when already in sync, and
# `playwright install` skips browsers already present in the cache
# (honouring PLAYWRIGHT_BROWSERS_PATH if set).
#
# Exit codes:
#   0  — success
#   non-zero — the failing step propagates its exit code

set -euo pipefail

WEB=false
for arg in "$@"; do
    case "$arg" in
        --web) WEB=true ;;
        *)
            echo "Unknown argument: $arg" >&2
            echo "Usage: $0 [--web]" >&2
            exit 1
            ;;
    esac
done

echo "==> [1/2] Installing Python dependencies (uv sync)…"
uv sync

echo "==> [2/2] Installing Playwright Chromium binary (uv run playwright install chromium)…"
echo "    (skips automatically if the browser is already cached)"
uv run playwright install chromium

if [ "$WEB" = true ]; then
    echo "==> [3/3] Installing web dependencies (npm --prefix web install)…"
    npm --prefix web install
fi

echo "==> Setup complete."
