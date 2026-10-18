# Bounded PR feedback repair pilot

This opt-in procedure delegates small feedback repairs while the lead retains
core decisions and final acceptance. It defines a collaboration contract, not a
configured model, watcher or review integration. Ordinary one-shot checks follow
[jobs-pr-finish](../.agents/skills/jobs-pr-finish/SKILL.md).

## Establish the task contract

Before handing off, record:

- The PR, head branch and starting SHA, agreed scope and definition of done,
  allowed small-repair categories and necessary checks. Use the repository's
  [verification skill](../.agents/skills/jobs-verify/SKILL.md) and
  [public test inventory](public-tests.md).
- An available repair agent/executor, its permitted files and actions, the exact
  review trigger when allowed, and a time/call or cost budget. This procedure
  alone grants no operational permission. Replies, thread resolution, merge,
  release and deployment are separate actions; do not infer them from permission
  to push repairs or request a review.
- One writer on the PR branch during the handoff. The lead does not edit the
  same repair scope concurrently. Preserve unrelated changes; unexpected head
  movement or an unsafe shared working state must be reported before writing.
- Two independent limits: by default **three review rounds in total** and
  **two actual repair attempts per issue**. The initial review, normally
  triggered when the PR opens, counts as round one; the repair agent may request
  at most two further reviews. Verify the actual integration and requests
  allowed by the task rather than assuming an automatic review is configured.

The repair agent may judge and fix clear, in-scope small issues, run affected
checks, commit and push without item-by-item preapproval when the contract
permits. It may not expand scope or completion criteria, or weaken checks to
make them pass. The lead independently accepts the final result.

## Process a bounded batch

1. Collect the complete feedback snapshot using the four sources and pagination
   required by jobs-pr-finish. Bind feedback and CI to their actual head SHA.
   An ended review with no findings ends the loop early; a pending review or
   failed/incomplete read is not zero feedback. Report outstanding CI and
   coverage separately.
2. Track each issue's disposition, evidence, repair attempts and fixed SHA.
   Recognize repeated findings even when comment IDs or SHAs change. Skip issues
   requiring escalation, continue the remaining independent small repairs, and
   collect skipped items for the lead.
3. Batch related repairs, execute the affected checks and record real outcomes.
   Push only authorized changes. After an actual repair, request at most one
   review for that batch when permitted and within the total limit. If a review
   for the new SHA is already running, do not request another one.
4. Hand back when the review has no findings, the global/budget limit is reached,
   or no independent small repairs remain. Do not wait indefinitely for merge or
   closure. If an environment or concurrency problem makes all remaining work
   unsafe, hand back immediately rather than overwriting or working around it.

### Count repair attempts separately

| Review | Issue A |
| --- | --- |
| Round 1, the initial review | A is reported; perform repair attempt 1 |
| Round 2 | A remains; perform repair attempt 2 |
| Round 3 | A remains; skip A and escalate, with no third repair attempt |

The first repair after the initial review is attempt one. An explicit increase
to the global review limit does **not** change the two-attempt issue limit;
changing the latter requires explicit approval. Keep counters across new
comments, commits and repair agents. Reassignment does not reset them. An issue
reported late does not justify exceeding the global review budget to give it
two attempts. Any remaining work goes to the lead under the agreed stop point.

## Escalate selectively

Skip the affected issue and continue other independent repairs when it involves
data models/migrations, eligibility/scoring semantics, deduplication or location
ownership, locking/transactions/async saves, permissions/credentials/privacy,
or CI/release permissions. Do the same when the agent cannot establish that the
finding is correct, necessary validation is unavailable, or repair attempts are
exhausted. A global budget or unsafe shared state may instead end the batch.

Send the lead the collected escalation list rather than interrupting the user
for every item. The lead decides core questions and assigns rework within the
existing task; product choices, scope expansion or new authority go to the user.

## Lead acceptance

Hand over the actual final SHA/diff, the complete finding ledger, checks actually
run and their results, unresolved items and budget usage. The lead independently
checks the integrated changes and arranges necessary regression, browser or
independent review. A resolved thread, green CI or the repair agent's completion
claim does not replace this acceptance. Missing required verification keeps the
result a validation-pending candidate.

Aim for a review-ready initial candidate and reserve human decisions for material
blockers, especially completion criteria. These are best-effort goals for fewer
context switches and clearer responsibility, not an added approval process or a
promised first-review pass rate.
