# workspace participation is declared by each surface

The updater work in issues #770–#779 needs to know whether the 出題 and History surfaces are ready, hold editable input or received results, and have work in flight before it can offer a safe update. Issue #769 makes each mounted surface declare its 工作區參與 in `web/src/lib/workspace/workspaceStore.ts`: readiness, editable state, received results and an export seam backed by the pure workspace adapters. Operations begin and end explicitly at their call sites, where completion, failure, abortion and supersession already have meaning. The registry observes these declarations without changing existing guards, 發送前確認 timing or the SSE protocol; this slice adds no persistence or refresh behaviour.

## Considered Options

Inferring activity from the router or DOM was rejected because a mounted page can still be hydrating, waiting for a draft-vs-History choice, or holding work inside a child component. Its route and visible controls do not establish that its workspace is safe to leave, and an unregistered surface must not be mistaken for an empty one.

A wrapper that owns AbortControllers was rejected because deciding whether an update is safe must not acquire authority to interrupt generation, 人工審題修正, planning, 預抽, 提示詞預覽 or exports. The store accepts operation metadata and idempotent end notifications; it never receives an AbortController, promise or callback that can cancel work. Cancellation remains with the existing operation owner.

## Consequences

Zero registered surfaces is unsafe. `isRefreshSafe` reports every blocker: no surface, hydration or restoration still pending, editable state, received results and active operations. Consumers can explain a refusal without reconstructing component internals; #769 itself never acts on that answer.

受理 lives beside `status` and never replaces it. Generation is admitted at the SSE `started` event; 人工審題修正 is admitted when submission returns a `run_id`. Submitting alone is not admission, and failures after admission leave that fact intact. Existing status transitions and guards remain authoritative, including synchronously closing 發送前確認 on send.

Issues #770–#779 consume these participation, operation, export/import and admission seams. They can add update policy and recovery without moving state ownership into the registry; wiring imports into mounted form, confirmation and modification surfaces remains downstream work.
