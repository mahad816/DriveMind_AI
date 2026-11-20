# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the strings used in this repo. They are written as the `Status:` value in a ticket file (see `issue-tracker.md`); there are no tracker labels to create. These roles say what a ticket is *for*. What is *happening* to it is a separate `Progress:` line (`open`, `claimed`, `resolved`); never mix the two.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding string from this table.

Edit the "Label in our tracker" column to match whatever vocabulary you actually use.
