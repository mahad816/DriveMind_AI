# Issue tracker: version-controlled Markdown

Specs and tickets are Markdown files committed to this repository. Do not use GitHub Issues or `.scratch/`.
The repository is public: never put secrets, credentials, private Google Drive contents or sensitive user information in a spec or ticket.

## Conventions

- One feature per slug: `<feature-slug>`
- Spec: `docs/specs/<feature-slug>.md`
- Tickets: one file each at `docs/tickets/<feature-slug>/NN-<slug>.md`, numbered from `01` in dependency order, never a combined file. Template: `docs/tickets/README.md`
- Each ticket has `Spec:`, `Blocked by:`, `Status:` and `Progress:` lines near the top. `Status:` is the **triage** role (one of the strings in `triage-labels.md`: what the ticket is for). `Progress:` is the **execution** state (`open`, `claimed` or `resolved`: what is happening to it). The two are independent: never put a triage role in `Progress:` or an execution state in `Status:`. A ticket with no `Progress:` line is `open`.
- A ticket is finished when it has `Progress: resolved`. A `wontfix` ticket also gets `Progress: resolved`; "close" in any skill means this.
- Comments and progress append to the bottom under `## Comments`
- Skills create or edit these files but do not commit them. The owner commits.

## Path overrides: this repo never uses `.scratch/`

Some of Matt Pocock's skills name `.scratch/` paths in their own text (for example `/to-tickets` under "Local files", `/ask-matt`, and the plugin's seed `issue-tracker-local.md`). They describe a generic local layout. In this repo always use the paths below instead, and never create a `.scratch/` directory:

| The skill text says | Use instead |
|---|---|
| `.scratch/<feature>/spec.md` | `docs/specs/<feature>.md` |
| `.scratch/<feature>/issues/<NN>-<slug>.md` | `docs/tickets/<feature>/<NN>-<slug>.md` |
| `.scratch/<effort>/map.md` | `docs/tickets/<effort>/map.md` |
| `.scratch/<effort>/issues/NN-<slug>.md` | `docs/tickets/<effort>/NN-<slug>.md` |

Where a skill or template sets a ticket's `Status:` to `claimed` or `resolved` (wayfinding), set `Progress:` instead. `Status:` keeps only the triage roles.

## When a skill says "publish to the issue tracker"

Create the file at the path above (creating the directory if needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user normally passes the path or the ticket number.

## Wayfinding operations (`/wayfinder`)

- **Map**: `docs/tickets/<effort>/map.md` (Notes / Decisions-so-far / Fog).
- **Child ticket**: `docs/tickets/<effort>/NN-<slug>.md` with the question in the body, a `Type:` line (`research`/`prototype`/`grilling`/`task`) and a `Progress:` line (`open`, `claimed`, `resolved`).
- **Blocking**: a `Blocked by: NN, NN` line. A ticket is unblocked when every file it lists has `Progress: resolved`.
- **Frontier**: tickets with `Progress: open` whose blockers are all resolved; lowest number first.
- **Claim**: set `Progress: claimed` and save before any work.
- **Resolve**: append the answer under `## Answer`, set `Progress: resolved`, then add a gist and link to Decisions-so-far in `map.md`.
