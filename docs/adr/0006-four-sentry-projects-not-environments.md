# Staging and production use separate Sentry projects per service

Both staging and production sites are deployed, and the conventional arrangement is one project per service with the sites separated by the environment tag. Although event quota is pooled at organisation level, the controls that cap consumption — rate limits, inbound filters, and spike protection — belong to a project and cannot be scoped to an environment tag. Staging deliberately provokes failures, making the least important events the most likely to spike, but a shared project provides no lever to cap them independently. We therefore use four projects: `exam-generation-web-prod`, `exam-generation-web-staging`, `exam-generation-api-prod`, and `exam-generation-api-staging`, with tighter rate limits and spike protection on the staging projects. Each project still receives the environment tag because the code already computes it and it keeps releases readable.

## Considered Options

Two projects divided by environment tag were rejected because their rate limits cannot distinguish staging from production, not because two deployed sites inherently require separate projects. One project for both frontend and backend was rejected because a project carries one platform's stack-trace processing and source-map handling; combining minified JavaScript frames with Python tracebacks makes grouping and symbolication conflict.

## Consequences

This requires four DSNs, four sets of alert rules, and a `SENTRY_PROJECT` build variable that differs by service and environment, a marginal cost because per-environment build arguments already exist. Issues cannot be moved between Sentry projects, so later consolidation loses history. Source-map upload targets a project, so each environment uploads its own copy of the maps under the same organisation token.
