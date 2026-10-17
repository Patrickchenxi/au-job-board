---
name: jobs-verify
description: Plan and perform AU Job Board implementation acceptance, targeted offline regressions and UI/UX walkthroughs. Use for product changes or their verification; documentation-only edits use the lightweight branch. Does not deploy or monitor PRs.
---

# Verify a Job Board change

## Establish the evidence boundary

Confirm the repository root, base/head, local diff and relevant user task. Read root AGENTS and only affected code/docs. Trace changed inputs through their consumers before choosing checks. Use synthetic fixtures and an isolated DB/port; record the source revision, environment and any mock/image revision. Uncommitted acceptance evidence must identify the tested diff as well as HEAD.

For documentation-only work, check facts, links, instruction consistency and skill frontmatter where relevant. Do not start product services or reinstall runtime dependencies just to edit prose. The existing PR CI still runs.

## Put UX before full implementation

For a substantial UI addition/restructure, describe one representative journey in user terms, then build a small clickable slice with realistic-length synthetic content before full integration. Show start, action and outcome, plus relevant failure/recovery. Self-review the slice first; ask the user only for meaningful unresolved product choices. A spacing fix does not require a prototype approval cycle.

Job Board's daily journey is finding a role, understanding it, deciding and recording the outcome. Place low-frequency maintenance and advanced settings according to context. Each new control needs a current task, a clear consequence and a reason to be persistent, contextual or advanced. Avoid equal-weight control walls, duplicate explanations and implementation jargon; replacing every label with an icon is not a remedy.

For settings, reading should be quiet and editing on demand. Preserve the current/next-run meaning and explain the consequence at confirmation. Do not add unrelated features while simplifying the surface.

## Choose checks by the changed boundary

Use [public-tests.md](../../../docs/public-tests.md) for actual coverage and requirements. These pairs are useful starting points, not a mandatory test list:

| Changed boundary | Start with | Add a scenario that exercises |
|---|---|---|
| YAML/settings | `tools/test_config_edit.py`, `tools/test_panel_update_http.py` | save → reload → edit again → revert; explicit vs inherited values, conflict/failure, valid large input through HTTP |
| Async UI/navigation | `tools/test_panel_note_separators.mjs` plus real browser | A → B/close/settings/ordinary URL with dirty or in-flight notes/skills; deferred generation during a pending request; repeat the operation |
| Run lifecycle | `tools/test_panel_update.py`, `tools/test_run_state.py` | controlled failure/termination near final persistence, competing generations and lock handoff |
| Vocabulary/config paths | `tools/test_skills_and_search.py` and affected integration tests | selected paths from outside repo cwd through CLI/worker/report/panel; rename/remove/re-add without changing canonical identity |
| Layout/copy | relevant panel logic/i18n tests, browser | real-length Chinese/English text, relevant desktop/mobile widths, keyboard/focus, loading/error state and task hierarchy |

Run scripts with the project interpreter; Node behavior checks use Node:

```bash
.venv/bin/python tools/test_config_edit.py
node tools/test_panel_note_separators.mjs
.venv/bin/python tools/run_public_tests.py --list
.venv/bin/python tools/run_public_tests.py
```

The runner has an explicit inventory; new regression scripts need deliberate inclusion when they belong in the public suite. Add durable tests for actual failure modes, not wording mirrors. For a defect, reproduce the old failure when practical, then confirm the fix. Explain if a race/failure could not be reproduced.

Run affected checks during development and the full applicable public entry once on the integrated code candidate. Later fixes require affected checks; repeat the whole suite only for new integration risk or a project requirement. CI verifies its own revision. Do not call script counts test-case counts.

Docker is opt-in when that boundary changes: `tools/test_docker.py` and [docker.md](../../../docs/docker.md). Match claims to the tested architecture. macOS retains source installation as the preferred path.

## Exercise UI behavior and usability separately

Use an available browser tool (such as playwright-cli) after a capability probe. Start a synthetic normal panel/mock environment for editing/update flows; [standalone demo](../../../docs/demo.md) has safety restrictions and cannot prove disabled product flows. Browser absence is a reported gap, not permission to label a static inspection browser acceptance.

Verify the served revision before using screenshots. Execute the journey and inspect requests/state, not only whether a button clicks. Check navigation destination, unsaved work, repeated operations, slow/failed responses and recoverability as relevant. Screenshots assess spacing, alignment, hierarchy, overflow and labels; they do not prove persistence or race handling.

For a substantial UI change, arrange a separate read-only UX pass with the task goal, necessary context and the actual candidate. Ask whether the next step and outcome are clear, which choices are irrelevant, and what can be removed, merged or demoted. Keep code review focused on correctness. Agent walkthroughs are not real-user usability studies.

## Deliver bounded evidence

Before claiming a fix/passing result, read fresh command outputs and exit codes. Reuse verification-before-completion if installed; the evidence requirement does not depend on that global skill being present.

Report tested revision/diff, executed checks, key journey outcomes and unresolved boundaries. Separate implementation, independent review, user acceptance and deployment. Keep private screenshots/logs out of public Git; reusable synthetic regression code belongs in the repo. Do not merge, publish or operate production as part of verification.
