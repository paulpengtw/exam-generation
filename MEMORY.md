# Project Memory

Durable gotchas and decisions for all agents and developers working on this repo.

---

## Gotchas

1. **Playwright browser binary is not installed by `uv sync`.**
   `playwright` is a Python package dependency, but its Chromium binary is a
   separate download that `uv sync` does not perform.  Running the test suite or
   the server without it causes every renderer construction to fail.
   Use `bash scripts/setup.sh` to install both (added in issue #659).
   See also: `scripts/setup.sh`, `README.md` Option A.

2. **After `git worktree move`, `.venv` shebangs break.**
   When a worktree is relocated with `git worktree move`, the virtual environment
   at `.venv/` retains scripts with shebangs pointing at the old path.
   `uv run pytest` (and similar commands) then fail with:
   `Failed to spawn: pytest / No such file or directory`.
   Fix: `rm -rf .venv && uv sync` (or `bash scripts/setup.sh`).
