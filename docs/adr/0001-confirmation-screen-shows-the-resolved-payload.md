# 發送前確認 shows the resolved payload, not the form's inputs

Parameters the user leaves blank were previously chosen by the backend sampler at generation time, so 發送前確認 displayed 「（無）」 for values that would in fact be set — the supervisor could not see what reached the model. We now 預抽 those values in the frontend, one independent set per question in a batch, 釘選 them onto the request, and display them alongside the 提示詞預覽 built from them.

## Considered Options

Labelling blank fields as "the backend will decide" was simpler and needed no wire change, but it still leaves the supervisor unable to see or intervene on the actual value. Pre-drawing a single set shared by the whole batch was rejected because it collapses per-question variety, which the batch-dedup design depends on.

## Consequences

Randomness for these parameters now originates in the frontend, and the backend sampler is bypassed whenever a value is supplied. Reproducibility rests on a seed resolved at confirmation time and sent with the request, so any future randomness added to prompt assembly must derive from that seed or it will silently break the guarantee that what is shown is what is sent.
