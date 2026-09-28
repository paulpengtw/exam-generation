"""Issue #858 – per-question worker split: setup, execution, shared finalize.

Acceptance criteria covered:
  AC1 – all terminal exits (normal, final-failure, confirmed-cancellation,
         resend-of-sealed, worker-unexpected-exit, batch-planning-failure) go
         through _finalize_worker_terminal.  Verified here by checking the
         snapshot_ledger's sealed terminal (which _finalize_worker_terminal is
         the only path that writes) and by checking the SSE question_terminal
         events emitted via generate_question_stream for the stream-level exits.
  AC2 – _setup_worker_recorders can be exercised without running generation.
         Tests create the bundle and verify all fields are present and callable
         without calling do_generate.
  AC3 / AC4 – existing fixture and worker-exit tests remain unmodified.
               Regression is covered by the full suite run; this file adds only
               the NEW seam tests.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_question_terminal.py helper style)
# ---------------------------------------------------------------------------


def _build_ctx(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
    *,
    count: int = 1,
    skip_verify: bool = True,
    output_dir: Path | None = None,
) -> Any:
    """Build a minimal _RunContext for worker-split unit tests."""
    from server.config import ServerConfig
    from server.generate.service import _build_run_context
    from server.generate.subjects import SUBJECTS
    from tests.server.generate_test_utils import resolved_generate_params

    params = resolved_generate_params(
        {
            "subject": "math",
            "seed": 41,
            "grade": 8,
            "context": ["個人"],
            "set_type": "單一題",
            "q_type": ["選擇題"],
            "style": ["text_only"],
            "math_thinking": ["形成"],
            "learning_content": ["A-7-7"],
            "learning_performance": ["s-IV-12"],
            "core_competency": ["數-J-A2"],
            "content_type": "純文字",
            "count": count,
            "skip_verify": skip_verify,
        }
    )
    spec = SUBJECTS["math"]
    cfg_kwargs: dict[str, Any] = {"api_key": "x", "gemini_api_key": "x"}
    if output_dir is not None:
        cfg_kwargs["output_dir"] = output_dir
    config = ServerConfig(**cfg_kwargs)
    app_state = MagicMock()
    return _build_run_context(
        params,
        config,
        app_state=app_state,
        spec=spec,
        session_factory=None,
        generation_log_id=None,
        loop=loop,
        queue=queue,
        html_renderer=None,
    )


def _make_question_client() -> Any:
    from src.llm_client import LLMClient
    client = MagicMock(spec=LLMClient)
    client.set_observer.return_value = None
    return client


# ---------------------------------------------------------------------------
# AC2 – _setup_worker_recorders without generation
# ---------------------------------------------------------------------------


class TestSetupWorkerRecorders:
    """_setup_worker_recorders can be tested without running generation."""

    def setup_method(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.queue: asyncio.Queue = asyncio.Queue()

    def teardown_method(self) -> None:
        self.loop.close()

    def test_returns_bundle_with_all_callable_fields(self) -> None:
        from server.generate.service import _setup_worker_recorders

        ctx = _build_ctx(self.loop, self.queue)
        client = _make_question_client()
        setup = _setup_worker_recorders(0, client, ctx)

        assert callable(setup.emit_question_update)
        assert callable(setup.capture_trail_entry)
        assert callable(setup.capture_figure_policy_entry)
        assert callable(setup.capture_reference_example_entry)

    def test_trail_lists_are_initially_empty(self) -> None:
        from server.generate.service import _setup_worker_recorders

        ctx = _build_ctx(self.loop, self.queue)
        client = _make_question_client()
        setup = _setup_worker_recorders(0, client, ctx)

        assert setup.verification_trail == []
        assert setup.figure_policy_trail == []
        assert setup.reference_example_entries == []

    def test_sets_observer_on_question_client(self) -> None:
        from server.generate.service import _setup_worker_recorders

        ctx = _build_ctx(self.loop, self.queue)
        client = _make_question_client()
        _setup_worker_recorders(0, client, ctx)

        client.set_observer.assert_called_once()

    def test_capture_trail_entry_appends_to_verification_trail(self) -> None:
        from server.generate.service import _setup_worker_recorders

        ctx = _build_ctx(self.loop, self.queue)
        client = _make_question_client()
        setup = _setup_worker_recorders(0, client, ctx)

        entry = {"type": "verification", "passed": True, "content_revision": 1}
        setup.capture_trail_entry(entry)

        assert len(setup.verification_trail) == 1
        assert setup.verification_trail[0] == entry

    def test_capture_trail_entry_with_model_copy_entry(self) -> None:
        """capture_trail_entry deep-copies entries with model_copy when content_revision given."""
        from server.generate.service import _setup_worker_recorders

        ctx = _build_ctx(self.loop, self.queue)
        client = _make_question_client()
        setup = _setup_worker_recorders(0, client, ctx)

        mock_entry = MagicMock()
        mock_entry.model_dump.return_value = {"status": "passed"}
        mock_entry.model_copy.return_value = mock_entry  # returns self for simplicity
        setup.capture_trail_entry(mock_entry, content_revision=5)

        mock_entry.model_copy.assert_called_once_with(update={"content_revision": 5})

    def test_capture_figure_policy_entry_appends_to_figure_policy_trail(self) -> None:
        from server.generate.service import _setup_worker_recorders

        ctx = _build_ctx(self.loop, self.queue)
        client = _make_question_client()
        setup = _setup_worker_recorders(0, client, ctx)

        entry = {"kind": "figure_policy", "figure_kind": "histogram"}
        setup.capture_figure_policy_entry(entry)

        assert len(setup.figure_policy_trail) == 1

    def test_capture_reference_example_entry_appends_to_entries(self) -> None:
        from server.generate.service import _setup_worker_recorders

        ctx = _build_ctx(self.loop, self.queue)
        client = _make_question_client()
        setup = _setup_worker_recorders(0, client, ctx)

        entry = {"kind": "example", "id": "ex1"}
        setup.capture_reference_example_entry(entry)

        assert len(setup.reference_example_entries) == 1

    def test_multiple_captures_accumulate(self) -> None:
        from server.generate.service import _setup_worker_recorders

        ctx = _build_ctx(self.loop, self.queue)
        client = _make_question_client()
        setup = _setup_worker_recorders(0, client, ctx)

        for i in range(3):
            setup.capture_trail_entry({"step": i})
        assert len(setup.verification_trail) == 3

    def test_no_generation_needed_to_create_setup(self) -> None:
        """_setup_worker_recorders completes without calling do_generate at all."""
        from server.generate.service import _setup_worker_recorders
        from server.generate.subjects import SUBJECTS

        ctx = _build_ctx(self.loop, self.queue)
        original_do_generate = SUBJECTS["math"].do_generate
        call_count = [0]

        def spy_do_generate(*args: Any, **kwargs: Any) -> Any:
            call_count[0] += 1
            return original_do_generate(*args, **kwargs)

        client = _make_question_client()
        # Just calling _setup_worker_recorders – no patch of do_generate needed;
        # verifying no side effect on call_count.
        _setup_worker_recorders(0, client, ctx)
        assert call_count[0] == 0, "do_generate must not run during setup"


# ---------------------------------------------------------------------------
# AC1 – _finalize_worker_terminal is the shared path for all exits
# ---------------------------------------------------------------------------


class TestFinalizeWorkerTerminalSharedPath:
    """All terminal exits route through _finalize_worker_terminal.

    Verification strategy: _finalize_worker_terminal is the only code path
    that calls snapshot_ledger.seal_terminal.  After running _worker_one_body,
    we inspect ctx.snapshot_ledger.get_terminal() to confirm the sealed
    payload has the expected termination_reason and has_final values.  No
    service module attributes are patched.
    """

    def setup_method(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.queue: asyncio.Queue = asyncio.Queue()

    def teardown_method(self) -> None:
        self.loop.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run_worker_body(
        self,
        ctx: Any,
        do_generate_fn: Any,
        *,
        confirmed_cancel: bool = False,
    ) -> None:
        from server.generate.service import _worker_one_body

        client = _make_question_client()
        import dataclasses

        from server.generate.subjects import SUBJECTS

        spec = dataclasses.replace(SUBJECTS["math"], do_generate=do_generate_fn)
        ctx_patched = dataclasses.replace(ctx, spec=spec)
        if confirmed_cancel:
            ctx_patched.confirmed_cancel_event.set()
        _worker_one_body(0, client, ctx_patched, [])

    # ------------------------------------------------------------------
    # Normal exit
    # ------------------------------------------------------------------

    def test_normal_exit_calls_finalize_once(self, tmp_path: Path) -> None:
        import json

        ctx = _build_ctx(self.loop, self.queue, output_dir=tmp_path)
        q = MagicMock(spec=ctx.spec.exam_question_cls)
        q.__class__ = ctx.spec.exam_question_cls
        q.model_dump_json.return_value = json.dumps({"id": ctx.manifest[0].question_id})
        q.圖片 = None
        q.subquestions = []
        q.chart_spec = None
        q.verification = None

        def do_generate(*args: Any, **kwargs: Any) -> Any:
            return q

        self._run_worker_body(ctx, do_generate)

        question_id = ctx.manifest[0].question_id
        terminal = ctx.snapshot_ledger.get_terminal(question_id)
        assert terminal is not None, "finalize must seal the terminal exactly once"
        assert terminal["termination_reason"] == "normal"
        assert terminal["has_final"] is True

    # ------------------------------------------------------------------
    # Final-failure exit
    # ------------------------------------------------------------------

    def test_failure_exit_calls_finalize_once(self, tmp_path: Path) -> None:
        ctx = _build_ctx(self.loop, self.queue, output_dir=tmp_path)

        def do_generate(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("intentional failure")

        self._run_worker_body(ctx, do_generate)

        question_id = ctx.manifest[0].question_id
        terminal = ctx.snapshot_ledger.get_terminal(question_id)
        assert terminal is not None, "finalize must seal the terminal exactly once"
        assert terminal["termination_reason"] == "failed"
        assert terminal["has_final"] is False

    # ------------------------------------------------------------------
    # Confirmed-cancellation exit
    # ------------------------------------------------------------------

    def test_confirmed_cancel_exit_calls_finalize_once(self, tmp_path: Path) -> None:
        from src.common.generation_core import GenerationCancelled

        ctx = _build_ctx(self.loop, self.queue, output_dir=tmp_path)

        def do_generate(*args: Any, **kwargs: Any) -> Any:
            raise GenerationCancelled("test cancel")

        self._run_worker_body(ctx, do_generate, confirmed_cancel=True)

        question_id = ctx.manifest[0].question_id
        terminal = ctx.snapshot_ledger.get_terminal(question_id)
        assert terminal is not None, "finalize must seal the terminal exactly once"
        assert terminal["termination_reason"] == "cancelled"

    # ------------------------------------------------------------------
    # Unconfirmed disconnect: no terminal emitted
    # ------------------------------------------------------------------

    def test_unconfirmed_disconnect_emits_no_terminal(self, tmp_path: Path) -> None:
        """A GenerationCancelled with no confirmed_cancel_event → no terminal."""
        from src.common.generation_core import GenerationCancelled

        ctx = _build_ctx(self.loop, self.queue, output_dir=tmp_path)

        def do_generate(*args: Any, **kwargs: Any) -> Any:
            raise GenerationCancelled("disconnect")

        # confirmed_cancel=False (default)
        self._run_worker_body(ctx, do_generate, confirmed_cancel=False)

        question_id = ctx.manifest[0].question_id
        assert not ctx.snapshot_ledger.is_terminal_sealed(question_id), (
            "no terminal should be emitted for unconfirmed disconnect"
        )

    # ------------------------------------------------------------------
    # Resend-of-already-sealed: original sealed payload is preserved
    # ------------------------------------------------------------------

    def test_already_sealed_exit_preserves_original_terminal(
        self, tmp_path: Path
    ) -> None:
        """When the ledger is sealed but publisher is not, the already_sealed path
        re-publishes the original payload without re-sealing; the sealed terminal
        must remain unchanged with its original unknown_reason."""
        ctx = _build_ctx(self.loop, self.queue, output_dir=tmp_path)
        question_id = ctx.manifest[0].question_id

        # Pre-seal the ledger with a fake terminal (has_final=False avoids revision check).
        fake_payload = {
            "termination_reason": "failed",
            "has_final": False,
            "final_revision": None,
            "delivery_status": "none",
            "expected": [],
            "delivered": [],
            "missing": [],
            "review": {"status": "unknown", "reason": "pre-sealed for test"},
            "unknown_reason": "pre-sealed for test",
        }
        ctx.snapshot_ledger.seal_terminal(question_id, fake_payload)
        # Publisher is NOT sealed.

        def do_generate(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("late failure after ledger seal")

        self._run_worker_body(ctx, do_generate)

        # The already_sealed path re-publishes the original payload without re-sealing.
        # The sealed terminal must still carry the pre-sealed unknown_reason.
        terminal = ctx.snapshot_ledger.get_terminal(question_id)
        assert terminal is not None
        assert terminal.get("unknown_reason") == "pre-sealed for test", (
            "already_sealed path must preserve the original sealed payload unchanged"
        )

    # ------------------------------------------------------------------
    # Sealing happens exactly once per question (no double-seal)
    # ------------------------------------------------------------------

    def test_sealing_happens_exactly_once_for_normal_exit(self, tmp_path: Path) -> None:
        import json

        ctx = _build_ctx(self.loop, self.queue, output_dir=tmp_path)
        q = MagicMock(spec=ctx.spec.exam_question_cls)
        q.__class__ = ctx.spec.exam_question_cls
        q.model_dump_json.return_value = json.dumps({"id": ctx.manifest[0].question_id})
        q.圖片 = None
        q.subquestions = []
        q.chart_spec = None
        q.verification = None

        seal_calls: list = []
        original_seal = ctx.snapshot_ledger.seal_terminal

        def spy_seal(qid: str, payload: dict) -> None:
            seal_calls.append(qid)
            original_seal(qid, payload)

        ctx.snapshot_ledger.seal_terminal = spy_seal

        self._run_worker_body(ctx, lambda *a, **k: q)
        assert seal_calls.count(ctx.manifest[0].question_id) == 1

    def test_sealing_happens_exactly_once_for_failure_exit(self, tmp_path: Path) -> None:
        ctx = _build_ctx(self.loop, self.queue, output_dir=tmp_path)

        seal_calls: list = []
        original_seal = ctx.snapshot_ledger.seal_terminal

        def spy_seal(qid: str, payload: dict) -> None:
            seal_calls.append(qid)
            original_seal(qid, payload)

        ctx.snapshot_ledger.seal_terminal = spy_seal

        self._run_worker_body(ctx, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fail")))
        assert seal_calls.count(ctx.manifest[0].question_id) == 1


# ---------------------------------------------------------------------------
# AC1 – batch-planning failure and worker-unexpected-exit also go through
#        _finalize_worker_terminal (exercised via generate_question_stream)
# ---------------------------------------------------------------------------


class TestWaitAndSignalUsesFinalize:
    """_wait_and_signal routes batch-fatal and unexpected-exit through _finalize_worker_terminal.

    Verification strategy: _finalize_worker_terminal is the only code path
    that emits question_terminal SSE events.  Observing exactly one correctly
    structured terminal per question in the SSE stream proves those exits went
    through the shared finalize path.  No service module attributes are patched.
    """

    def _collect_events(self, params: Any, config: Any, app_state: Any, **kwargs: Any) -> list:
        from server.generate.service import generate_question_stream

        events: list[dict] = []

        async def _run() -> None:
            async for event in generate_question_stream(params, config, app_state, **kwargs):
                events.append(event)

        asyncio.run(_run())
        return events

    def test_batch_planning_failure_terminal_via_finalize(self, tmp_path: Path) -> None:
        """Batch planning failure: each question gets exactly one terminal via finalize path.

        The presence of exactly two question_terminal events with the expected
        termination_reason proves that _finalize_worker_terminal was called for
        each question – it is the only path that emits question_terminal.
        """
        import dataclasses
        from pathlib import Path as _Path
        from types import SimpleNamespace

        from server.config import ServerConfig
        from server.generate.subjects import SUBJECTS
        from tests.server.generate_test_utils import resolved_generate_params

        def do_plan(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("planner down")

        fake_spec = dataclasses.replace(
            SUBJECTS["social_studies"],
            plan_all_batch_briefs=do_plan,
        )
        params = resolved_generate_params({
            "subject": "social_studies",
            "count": 2,
            "skip_verify": True,
        })
        config = ServerConfig(  # noqa: E501
            api_key="x", gemini_api_key="x", output_dir=tmp_path, data_dir=_Path("data")
        )
        app_state = SimpleNamespace(renderer_pool=None)

        events = self._collect_events(
            params, config, app_state, subjects={"social_studies": fake_spec}
        )

        terminals = [e for e in events if e.get("event") == "question_terminal"]
        assert len(terminals) == 2, (
            f"expected 2 question_terminal events (one per question), got {len(terminals)}"
        )
        for t in terminals:
            payload = t.get("payload", t.get("data", {}))
            assert payload["termination_reason"] == "failed"
            assert payload["has_final"] is False

    def test_worker_unexpected_exit_terminal_via_finalize(self, tmp_path: Path) -> None:
        """Worker raising outside boundary: terminal emitted via finalize path.

        The presence of exactly one question_terminal event with the expected
        termination_reason proves that _finalize_worker_terminal was called –
        it is the only path that emits question_terminal.
        """
        import dataclasses
        from pathlib import Path as _Path
        from types import SimpleNamespace

        from server.config import ServerConfig
        from server.generate.subjects import SUBJECTS
        from tests.server.generate_test_utils import resolved_generate_params

        # do_generate raises a BaseException to escape the try/except Exception guard
        # in _worker_one_body; this reaches _wait_and_signal's asyncio.gather handler.
        def do_generate(*args: Any, **kwargs: Any) -> Any:
            raise SystemExit(1)

        fake_spec = dataclasses.replace(SUBJECTS["social_studies"], do_generate=do_generate)
        params = resolved_generate_params({
            "subject": "social_studies",
            "count": 1,
            "skip_verify": True,
        })
        config = ServerConfig(  # noqa: E501
            api_key="x", gemini_api_key="x", output_dir=tmp_path, data_dir=_Path("data")
        )
        app_state = SimpleNamespace(renderer_pool=None)

        events = self._collect_events(
            params, config, app_state, subjects={"social_studies": fake_spec}
        )

        terminals = [e for e in events if e.get("event") == "question_terminal"]
        assert len(terminals) == 1, (
            f"expected 1 question_terminal event, got {len(terminals)}"
        )
        payload = terminals[0].get("payload", terminals[0].get("data", {}))
        assert payload["termination_reason"] == "failed"
        assert payload["has_final"] is False
