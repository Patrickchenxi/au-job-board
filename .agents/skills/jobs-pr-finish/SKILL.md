---
name: jobs-pr-finish
description: Collect and triage all AU Job Board PR feedback, verify authorized fixes and prepare a bounded handoff. Use for checking auto review, independent PR review or updating a PR after fixes; continuous monitoring, external replies and merging require current-task authorization.
---

# Finish a PR review round

## Establish the round and stop point

Confirm repository, PR number, base/head SHA, branch diff and CI revision. Attach the PR to the current task when the app attachment tool is available. Read root AGENTS and the user's current constraints.

“Check the latest/all issues” means one complete snapshot of the PR's published feedback, including older unresolved items, followed by the authorized fixes and verification. Record the snapshot time/head. It is not permission for a watcher, new review request, public reply or merge. Reuse existing authorization; do not ask again for an already-authorized action.

## Collect every feedback channel

Read all of these, with pagination:

- Conversation/issue comments.
- Inline review comments.
- Review submissions, including their bodies even when no inline comment exists.
- Review threads and resolution/outdated metadata.

GitHub MCP's `fetch_pr_comments` provides a merged timeline; `list_pull_request_review_threads` supplies thread metadata. Confirm completeness/pagination from the actual tool response. If a tool cannot establish complete coverage, use GitHub REST/GraphQL via `gh` instead; do not infer that the final visible item is the whole review.

For the three REST feeds, run from the intended checkout with the confirmed PR number:

```bash
gh api --paginate 'repos/SkywingJam/au-job-board/issues/NUMBER/comments?per_page=100'
gh api --paginate 'repos/SkywingJam/au-job-board/pulls/NUMBER/comments?per_page=100'
gh api --paginate 'repos/SkywingJam/au-job-board/pulls/NUMBER/reviews?per_page=100'
```

Replace NUMBER with the confirmed number. For GraphQL `reviewThreads`, request `pageInfo { hasNextPage endCursor }`, advance `after` until complete, and paginate comments within each thread too. REST inline comments alone do not provide resolved state. Preserve feed types and stable IDs when normalizing/deduplicating; comments copied into review summaries are not automatically separate defects.

If an API fails or output is truncated, say which coverage is incomplete and retry that read or use the alternate path. Never report “all clear” from a partial snapshot.

## Judge the findings against the candidate

Keep a compact local ledger: source/type + ID/URL, reviewed SHA (if supplied), affected behavior, disposition/evidence and fixed SHA when applicable. Do not invent a reviewed SHA for an issue comment. Resolved/outdated is metadata, not proof that the current code is correct.

Read the relevant call chain and reproduce plausible defects. Classify confirmed, already fixed, not applicable/unsupported, duplicate, or unresolved. Batch common-root fixes; do not patch every suggestion automatically or manufacture findings. Leave genuinely uncertain product choices for the user, with the evidence needed to decide.

Use [jobs-verify](../jobs-verify/SKILL.md) for affected tests and relevant UI journeys. Independently review lock/persistence changes; review substantial UI changes for UX separately from code correctness. Check the integrated diff yourself after delegated fixes.

## Update and hand off

For an authorized PR creation/update, describe the final problem/behavior and actual validation, bound to the candidate. Stable delivery uses `dev` → `main` with CI; use a scoped task branch from dev when isolation is needed. Verify actual base/head/diff rather than branch names alone. Use draft status while unfinished if requested; set ready only after the agreed local acceptance/review. Inspect checks on the latest candidate instead of reusing an older green run.

External replies, resolving GitHub threads, requesting another review (including `@codex review`), merging, tagging and deployment must follow current-task authorization. “Fix review issues” alone does not authorize those messages/actions. A no-new-review instruction remains in effect after a push; platform-triggered reviews are distinct from a manual request.

Default stop: this snapshot's actionable findings have been handled or explicitly left unresolved, affected checks are reported, the authorized PR update is complete, and the user receives the remaining CI/acceptance status. Do not silently wait indefinitely for another round.

Only if continuous care is explicitly requested, use an available watcher such as babysit-pr; inspect its instructions and honor the user's narrower limits on duration, budget, replies, review triggers and merging. A one-shot `--once` script can help collect a snapshot when available; neither that installation nor a one-time check starts background monitoring.
