# Contributor and agent guidance

## Working here

- Start code/version work from `dev`; stable delivery reaches `main` through a PR and CI, including documentation. Preserve unrelated changes.
- Establish the task scope and definition of done before implementation. Keep them fixed unless the user explicitly approves expansion; correcting promised behavior or basic usability stays within the task.
- At task start, read current open issues and relevant discussions in `SkywingJam/au-job-board`. Identify authors by login; prioritize maintainer-reported defects, record disposition and minimal acceptance, and explain deferrals. Say when access is unavailable.
- Use hand-written synthetic inputs, isolated databases and loopback test ports. Never use personal configuration, real listings/notes or a production database for testing. See [data policy](docs/test-data-policy.md).
- Existing rules and explainable evidence are the product baseline. Do not restore the removed candidate parser or broaden eligibility/scoring semantics without agreed scope.
- The lead agent owns basic usability: task flow, information hierarchy, action naming and continuity. User feedback chooses goals and tradeoffs; it is not a substitute for checking ordinary UX quality before delivery.
- Implementation or acceptance: read [jobs-verify](.agents/skills/jobs-verify/SKILL.md) and select its documentation/product branch. Existing PR feedback or handoff: read [jobs-pr-finish](.agents/skills/jobs-pr-finish/SKILL.md). General contributor guidance is in [docs/contributing.md](docs/contributing.md).
- Delegate when independent work helps. Give implementers file ownership; give reviewers the target revision and minimal task context. The lead owns core-boundary decisions and independently accepts integrated results. Small edits need no agent queue; lock/persistence changes need independent review.
- Follow the current task's authorization for push, external comments, review requests, merge, release and deployment. Checking feedback does not authorize triggering another review or continuous monitoring.

## Review guidelines

Report actionable defects with a concrete trigger, observable impact and code evidence; a clean review is acceptable. Fix regressions and small affected edge cases; give an evidenced disposition to unrelated low-impact issues and preferences without silently expanding the task. Escalate material data, safety or core-workflow risks. In addition to ordinary correctness, protect these cross-layer invariants:

1. **Configuration and identity keep their meaning.** Draft edits, saved next-run configuration and the last successful analysis snapshot are distinct. Saving never recomputes results; missing historical snapshots remain unknown. Preserve explicit overrides and unknown YAML fields, detect conflicting writes, and carry the selected config/vocabulary paths through CLI, worker, report and panel. Vocabulary display names never replace canonical identities.
2. **Async UI preserves the user's work and destination.** Refresh applies a new result version once and defers while a JD is open, without losing filters, scroll anchors, labels, notes or the intended next URL/JD. In-flight saves and repeated edits remain safe across ordinary links and relevant alternate navigation paths. A deferred/in-flight refresh signal must not disappear.
3. **Completion follows durable facts owned by the right run.** Child exit zero or a run row alone does not prove full-pipeline success. Keep required locks through terminal persistence, retain completion evidence across layers, and prevent stale workers from overwriting newer generations. Publish derived-result changes coherently and preserve human labels/notes.
