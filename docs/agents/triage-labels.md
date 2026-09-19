# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo. The vocabulary is shared by both trackers (`issue-tracker.md`), but it does not mean the same thing on each:

- On **GitHub issues**, all five are triage labels, applied by `/triage` to the public tracker. `ready-for-agent` and `ready-for-human` mean a public report is ready to be worked on.
- On **Linear**, only `ready-for-agent` and `ready-for-human` are used, and they mark a build ticket as ready for an agent or for a human to implement. The other three belong to triaging a public report, which is not what an internal ticket is.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.
