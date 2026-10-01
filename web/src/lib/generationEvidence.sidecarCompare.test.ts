/**
 * Issue #932: sidecar-only differences at an unchanged content revision must
 * not produce a content conflict.
 *
 * The server strips the same set of keys (verification, verification_trail,
 * figure_policy_trail, reference_example_record, image_base64, metadata,
 * review, progress, export, _export) at every depth before computing the
 * content signature.  The browser's questionContentFingerprint must use the
 * same rule so a draft→final promotion that adds sidecar fields does not
 * wrongly fire same_revision_different_content.
 *
 * Covers both the v2 stream decoder path and the runSnapshot poll path.
 *
 * Contract drift test: a companion pytest (tests/test_932_sidecar_contract.py)
 * asserts that CONTENT_SIGNATURE_EXCLUDED_KEYS in the Python source matches
 * contracts/content-sidecar-keys.json.  This vitest file imports the same
 * JSON to guarantee the TS module also matches.
 */
import { describe, expect, it } from "vitest";
import {
  applyV2Event,
  createRunEvidence,
  selectEndedCount,
  selectFinalReceivedCount,
  type RunEvidenceState,
} from "./generationEvidence";
import {
  applyRunSnapshot,
  type RunSnapshot,
} from "./runSnapshot";
import CONTRACT from "../../../contracts/content-sidecar-keys.json";

// ---------------------------------------------------------------------------
// Contract drift guard: TS side
// ---------------------------------------------------------------------------

it("contract file lists exactly the server CONTENT_SIGNATURE_EXCLUDED_KEYS", () => {
  // The actual set is asserted against the Python source by
  // tests/test_932_sidecar_contract.py. Here we only check structural
  // consistency so a future edit that touches only one copy fails loudly.
  const expected = new Set([
    "verification",
    "verification_trail",
    "figure_policy_trail",
    "reference_example_record",
    "image_base64",
    "metadata",
    "review",
    "progress",
    "export",
    "_export",
  ]);
  const actual = new Set(CONTRACT.keys);
  expect(actual).toEqual(expected);
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const RUN_ID = "RUN932";
const Q_ID = "q_RUN932_001";

function freshRun(): RunEvidenceState {
  return createRunEvidence({
    runId: RUN_ID,
    total: 1,
    manifest: [{ index: 0, questionId: Q_ID }],
  });
}

function update(rev: number, question: unknown) {
  return {
    kind: "v2" as const,
    event: {
      name: "question_update",
      context: { run_id: RUN_ID, question_id: Q_ID, content_revision: rev },
      payload: { phase: "draft", question },
    },
  };
}

function result(rev: number, question: unknown) {
  return {
    kind: "v2" as const,
    event: {
      name: "result",
      context: { run_id: RUN_ID, question_id: Q_ID, content_revision: rev },
      payload: question,
    },
  };
}

function terminal(rev: number) {
  return {
    kind: "v2" as const,
    event: {
      name: "question_terminal",
      context: { run_id: RUN_ID, question_id: Q_ID },
      payload: {
        termination_reason: "normal",
        has_final: true,
        final_revision: rev,
        delivery_status: "complete",
        expected: [],
        delivered: [],
        missing: [],
        review: { status: "passed", content_revision: rev },
      },
    },
  };
}

/** The question content that the execute model produced (no verification yet). */
const BASE_QUESTION = {
  id: Q_ID,
  情境: ["個人"],
  題型種類: "單一題",
  題型: "選擇題",
  題目: ["Sample question?", "A) 1", "B) 2", "C) 3", "D) 4"],
  正確解題分析: ["Answer is A"],
  核心素養: ["數-J-A2"],
  學習內容: [{ 編碼: "N-7-1", 說明: "整數的四則運算" }],
  學習表現: [{ 編碼: "n-IV-1", 說明: "解題" }],
};

/** The same content after the verifier ran: adds verification + trail but
 *  keeps all other fields byte-identical.  The server sees this as the same
 *  content revision because it strips the sidecar fields before signing. */
const VERIFIED_QUESTION = {
  ...BASE_QUESTION,
  verification: {
    passed: true,
    answer_match: true,
    details: "All correct.",
    my_answer: "A",
    provided_answer: "A",
  },
  verification_trail: [
    {
      passed: true,
      answer_match: true,
      details: "All correct.",
      my_answer: "A",
      provided_answer: "A",
      content_revision: 1,
    },
  ],
  metadata: {
    reporting_scales: {},
  },
  review: {
    status: "passed",
    content_revision: 1,
  },
};

// ---------------------------------------------------------------------------
// v2 stream path
// ---------------------------------------------------------------------------

describe("v2 stream path — sidecar-only draft→final promotion", () => {
  it("question_update then result with sidecar fields at same rev → no conflict, final received", () => {
    let state = freshRun();
    // Step 1: post-generate draft (no verification yet)
    state = applyV2Event(state, update(1, BASE_QUESTION));
    expect(state.questions[Q_ID].content.receipt).toBe("draft");

    // Step 2: post-verification result at same revision (adds verification, metadata, review)
    state = applyV2Event(state, result(1, VERIFIED_QUESTION));

    // Must adopt the final result — no conflict
    expect(state.questions[Q_ID].contentConflict).toBe(false);
    expect(state.questions[Q_ID].content.receipt).toBe("final");

    // Step 3: terminal with review passed
    state = applyV2Event(state, terminal(1));
    expect(state.questions[Q_ID].terminal).not.toBeNull();
    expect(state.questions[Q_ID].review.status).toBe("passed");
    expect(selectFinalReceivedCount(state)).toBe(1);
    expect(selectEndedCount(state)).toBe(1);
  });

  it("draft→draft at same rev with sidecar-only change → no conflict (idempotent or update)", () => {
    let state = freshRun();
    state = applyV2Event(state, update(1, BASE_QUESTION));

    // Post-verification draft update at same rev (sidecar-only addition)
    const verifiedDraft = { ...VERIFIED_QUESTION };
    state = applyV2Event(state, update(1, verifiedDraft));

    expect(state.questions[Q_ID].contentConflict).toBe(false);
    expect(state.questions[Q_ID].content.receipt).toBe("draft");
  });

  it("a second result at same rev with different actual content → still a conflict", () => {
    let state = freshRun();
    state = applyV2Event(state, result(1, BASE_QUESTION));
    expect(state.questions[Q_ID].content.receipt).toBe("final");

    const altQuestion = {
      ...BASE_QUESTION,
      題目: ["DIFFERENT question?", "A) 5", "B) 6", "C) 7", "D) 8"],
    };
    state = applyV2Event(state, result(1, altQuestion));

    expect(state.questions[Q_ID].contentConflict).toBe(true);
    expect(state.questions[Q_ID].contentConflictReason).toBe("same_revision_different_content");
  });

  it("draft at rev 1 then result at rev 1 with different question text → conflict", () => {
    let state = freshRun();
    state = applyV2Event(state, update(1, BASE_QUESTION));

    const altQuestion = {
      ...BASE_QUESTION,
      題目: ["DIFFERENT question?"],
    };
    state = applyV2Event(state, result(1, altQuestion));

    expect(state.questions[Q_ID].contentConflict).toBe(true);
    expect(state.questions[Q_ID].contentConflictReason).toBe("same_revision_different_content");
  });

  it("sidecar fields at every depth are stripped (nested verification in subquestions)", () => {
    const baseSubquestion = {
      id: `${Q_ID}-sq001`,
      序號: 1,
      年級: 7,
      題型: "選擇題",
      題目: "Part 1?",
      答案: "A",
      答案解析: "Because...",
    };
    // Draft has subquestion without sidecar fields
    const baseWithSubs = { ...BASE_QUESTION, subquestions: [baseSubquestion] };
    // Result at same rev has same subquestion but with nested sidecar fields
    const verifiedWithSubs = {
      ...BASE_QUESTION,
      subquestions: [
        {
          ...baseSubquestion,
          verification: { passed: true }, // nested sidecar — must be stripped
          metadata: { something: "extra" }, // nested sidecar — must be stripped
        },
      ],
    };
    let state = freshRun();
    // Draft at rev 1 with subquestions (no sidecar)
    state = applyV2Event(state, update(1, baseWithSubs));
    expect(state.questions[Q_ID].content.receipt).toBe("draft");
    // Result at rev 1: same subquestion content but with nested sidecar added
    state = applyV2Event(state, result(1, verifiedWithSubs));
    // No conflict because nested verification/metadata are sidecar
    expect(state.questions[Q_ID].contentConflict).toBe(false);
    expect(state.questions[Q_ID].content.receipt).toBe("final");
  });

  it("all sidecar keys independently produce no conflict when added at same rev", () => {
    const sidecarKeys = CONTRACT.keys;
    for (const key of sidecarKeys) {
      let state = freshRun();
      state = applyV2Event(state, update(1, BASE_QUESTION));
      const withSidecar = { ...BASE_QUESTION, [key]: { something: "extra" } };
      state = applyV2Event(state, result(1, withSidecar));
      expect(state.questions[Q_ID].contentConflict).toBe(false);
      expect(state.questions[Q_ID].content.receipt).toBe("final");
    }
  });

  it("verification: null vs omitted key → no conflict (both treated as absent)", () => {
    let state = freshRun();
    // Draft without verification key
    state = applyV2Event(state, update(1, BASE_QUESTION));
    // Result with verification: null
    const withNullVerification = { ...BASE_QUESTION, verification: null };
    state = applyV2Event(state, result(1, withNullVerification));
    expect(state.questions[Q_ID].contentConflict).toBe(false);
    expect(state.questions[Q_ID].content.receipt).toBe("final");
  });
});

// ---------------------------------------------------------------------------
// runSnapshot path
// ---------------------------------------------------------------------------

describe("runSnapshot path — sidecar-only final result from poll", () => {
  function snapshotWith(
    question: unknown,
    terminalPayload: Record<string, unknown> | null = null,
    finalRevision: number | null = 1,
  ): RunSnapshot {
    const t = terminalPayload ?? {
      termination_reason: "normal",
      has_final: true,
      final_revision: finalRevision,
      delivery_status: "complete",
      expected: [],
      delivered: [],
      missing: [],
      review: { status: "passed", content_revision: finalRevision },
    };
    return {
      run_id: RUN_ID,
      status: "completed",
      subject: "math",
      total: 1,
      started_at: null,
      completed_at: null,
      error: null,
      questions: [
        {
          index: 0,
          question_id: Q_ID,
          processing: "ended",
          current_step: null,
          termination_reason: "normal",
          terminal: t,
          error: null,
          result: {
            record_id: "rec_001",
            question: question as never,
            verification_trail: null,
            figure_policy_trail: null,
            reference_example_record: null,
          },
        },
      ],
    };
  }

  it("polled final result with verification at rev 1, prior draft at rev 1 without it → no conflict", () => {
    // Seed state with a draft at rev 1 (from a live stream update)
    let state = freshRun();
    state = applyV2Event(state, {
      kind: "v2",
      event: {
        name: "question_update",
        context: { run_id: RUN_ID, question_id: Q_ID, content_revision: 1 },
        payload: { phase: "draft", question: BASE_QUESTION },
      },
    });
    expect(state.questions[Q_ID].content.receipt).toBe("draft");

    // Now poll: result at rev 1 has verification sidecar fields
    const snap = snapshotWith(VERIFIED_QUESTION, null, 1);
    state = applyRunSnapshot(state, snap);

    expect(state.questions[Q_ID].contentConflict).toBe(false);
    expect(state.questions[Q_ID].content.receipt).toBe("final");
    expect(state.questions[Q_ID].review.status).toBe("passed");
    expect(selectFinalReceivedCount(state)).toBe(1);
    expect(selectEndedCount(state)).toBe(1);
  });

  it("first snapshot (no prior state) with verified result → no conflict", () => {
    const snap = snapshotWith(VERIFIED_QUESTION, null, 1);
    const state = applyRunSnapshot(null, snap);
    expect(state.questions[Q_ID].contentConflict).toBe(false);
    expect(state.questions[Q_ID].content.receipt).toBe("final");
    expect(state.questions[Q_ID].review.status).toBe("passed");
    expect(selectFinalReceivedCount(state)).toBe(1);
  });
});
