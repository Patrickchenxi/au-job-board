---
name: jobs-verify
description: Verify AU Job Board product changes, UI/UX journeys or documentation-only edits, with checks and evidence matched to the changed boundary.
---

# Verify a Job Board change

## 1. Establish the candidate and choose a branch

Read root AGENTS and affected code/docs. Record repository, base/head, tested local diff, agreed task/completion criteria and environment; include the served source/image revision for browser evidence. Trace changed inputs through their consumers before selecting checks.

- **Documentation only:** check facts, local links, instruction consistency and any changed skill frontmatter. Once these pass or gaps are recorded, go directly to **4. Deliver evidence**. Keep existing PR CI; no product service or runtime dependency installation is needed.
- **Product change:** use hand-written synthetic fixtures and an isolated DB/loopback port. For substantial UI work or consequential functional uncertainty, complete **2** before full integration; otherwise proceed to **3**.

## 2. Establish the interaction direction

Use an early mockup or proof of concept for changes with substantial UX or functional uncertainty; the greater the impact or disagreement, the earlier this happens. For UI work, build a small clickable slice of one representative journey with realistic-length synthetic content. For non-UI uncertainty, exercise a representative behavior and its failure boundary in a small proof of concept. The purpose is to validate direction, not achieve pixel-perfect styling. Record the start, primary action, outcome and relevant failure/recovery, and distinguish working behavior from mocked behavior. Job Board's daily journey is finding a role, understanding it, deciding and recording the outcome; place maintenance and advanced settings in context.

For each new control, identify the current user task, consequence and reason for persistent, contextual or advanced placement. For settings, keep reading quiet, edit on demand and explain the current/next-run consequence at confirmation. Self-review hierarchy, naming, discoverability and continuity; an icon-only surface or fewer clicks alone does not establish usability.

Label this a direction preview: agreement covers what was demonstrated, not unshown behavior or final acceptance. Proceed to full integration when known basic usability defects are corrected and material product choices are settled with the user when needed. Keep any remaining limitation explicit. A spacing fix follows the product branch without a prototype approval cycle.

## 3. Verify the changed boundary

Use [public-tests.md](../../../docs/public-tests.md) to select current scripts, requirements and commands. The following are cross-state scenarios beyond that inventory; choose those affected by the diff:

| Boundary | Exercise |
|---|---|
| YAML/settings | save → reload → edit again → revert; explicit vs inherited values, conflict/failure, valid large input through HTTP |
| Async UI/navigation | A → B/close/settings/ordinary URL with dirty or in-flight notes/skills; a new generation during a pending request; repeated operations |
| Run lifecycle | controlled failure/termination near terminal persistence, competing generations and lock handoff |
| Vocabulary/config paths | selected paths from outside repo cwd through CLI/worker/report/panel; rename/remove/re-add without changing canonical identity |
| Layout/copy | realistic Chinese/English text, relevant desktop/mobile widths, keyboard/focus, loading/error state and task hierarchy |

Run affected checks during development and the full applicable public entry once on the integrated code candidate. Later fixes require affected checks; repeat the whole suite for new integration risk or a project requirement. CI verifies its own revision. The runner has an explicit inventory: deliberately register new public regression scripts. Reproduce the old defect when practical, then verify the fix; record reproduction gaps.

For Docker changes, use the opt-in smoke test and requirements in [docker.md](../../../docs/docker.md), and limit claims to the tested architecture. macOS retains source installation as the preferred path.

### UI branch: behavior and usability

Probe an available browser tool and verify the served candidate. Use a synthetic normal panel/mock for editing/update flows; [standalone demo](../../../docs/demo.md) cannot prove product flows disabled by its safety restrictions.

Execute the journey and inspect requests/state, navigation destination, unsaved work, repeated operations and relevant slow/failed responses. Screenshots supplement this with alignment, hierarchy, overflow and labels. Browser unavailability remains an acceptance gap.

For substantial UI changes, arrange a separate read-only UX pass with the task goal, necessary context and actual candidate. Check whether the next step/outcome is clear, which choices are irrelevant, and what can be removed, merged or demoted. Code review checks correctness; agent walkthroughs are not real-user usability studies.

Record observed outcomes and explicit gaps on the integrated candidate. After reasonable diagnosis or an available alternative, a missing verification capability can end in a validation-pending handoff; continue independent work rather than repeatedly debugging the tool. Keep production data and services outside this workaround. An optional part may be isolated for staged acceptance only when its boundary and reduced scope are agreed.

## 4. Deliver evidence

Read fresh outputs and exit codes before claiming a fix or pass. Report tested revision/diff, executed checks, relevant journey outcomes and unresolved boundaries; distinguish script-entry counts from test-case counts. Keep private screenshots/logs outside public Git and durable synthetic regression code in the repo.

Separate candidate preparation, verified behavior, independent review, user acceptance and deployment. If required acceptance remains unverified, call the result a validation-pending candidate and identify the missing checks; do not call the affected feature implemented, complete or merge-ready. A workflow handoff with gaps is not acceptance of the capability. After final acceptance, disclose material behavior changes and recheck the affected part. Root AGENTS governs operational authorization.
