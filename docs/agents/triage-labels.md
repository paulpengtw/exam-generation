# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Labels outside this table are repo-local rather than skill roles; reuse them instead of coining a synonym. `blocked` means an issue is fully specified but waiting on another issue to be resolved first — pair it with a native GitHub issue dependency so the blocker is machine-readable, and swap it for `ready-for-agent` once that blocker closes.

`headed environment` marks an issue whose acceptance cannot be completed headlessly: the agent must drive a real browser through the **ego-browser** skill against a live staging-like deployment, and that environment only exists where the user provides it. It is a prerequisite marker, not a triage state, so it sits alongside the triage label (typically `ready-for-agent` or `blocked`) rather than replacing it. An agent picking up such an issue must stop before the browser step, ask the user to run it in an environment where ego-browser is installed and reachable, and ask the user for the login credentials that environment needs; it must never search the tree or env for credentials, and must not report the browser verification as passed without having run it. Apply the label at triage time whenever the acceptance criteria call for ego-browser, a headed or real-browser session on staging, or supervisor login credentials. An issue that merely points at such a ticket (for example "the final ticket verifies this in ego-browser") does not carry the label itself. The tracker description for this label is "Needs the user to run the agent with ego-browser (headed browser) and provide login credentials"; keep it and this paragraph in agreement.

Edit the right-hand column to match whatever vocabulary you actually use.
