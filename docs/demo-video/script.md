# Script and storyboard

Planning notes for the v1.3 demo (43.8 s). The direction was agreed from storyboard
frames and refined over several review rounds. Times are seconds on the 60 fps cut.

## Approach

- **Idea:** one question, asked three ways. A person in the panel, a script on the
  HTTP API and an agent over MCP ask the same thing and land on the same number. The
  board is the shared foundation; people and agents get equal screen time, and the
  person keeps the decisions.
- **Audience:** someone browsing a README or a link, often muted. Captions carry the
  story; music and sounds are optional.
- **Look:** the panel's paper / ink tokens and one rounded-card language. Three colours
  are fixed from the first shot and never reused for anything else: panel blue
  `#2357A6`, HTTP API orange `#E07A48`, MCP teal `#1F7A6B`. They come back as the three
  badges and, at the end, as the three dots of the logo.
- **Motion:** arrivals use springs; camera moves and exits use eases. Only transform,
  opacity, blur and clipping are animated. The three columns hit their key beats on
  the same frame (Enter, tool call and React click at 9.4 s; the three counters at
  13.4 s). Each action is followed by a still beat long enough to read.
- **Honesty:** everything on screen that looks like product output is real output on
  synthetic data (see [README](README.md)). Drawn elements (pointer, chat window,
  agent notes, prompts) claim nothing beyond what was run.

Left out on purpose: settings and skill vocabulary, eligibility corrections, notes,
dark theme and phone layouts. They are real, but they do not serve this story.

## Storyboard

| Time | Scene | On screen | Caption |
|---|---|---|---|
| 0.0–3.3 | **The question** | Paper background. "THE QUESTION", then *How many React jobs are there near Melbourne 3000?* types in character by character (each rises and un-blurs); highlighter marks sweep under "React" and "Melbourne 3000". The line lifts away as the header takes its place. | — |
| 3.0–11.6 | **Three ways to ask** | Three columns spring in. *Panel:* the pointer clicks Location (preset list), types `3000`, clicks Apply ("20 of 208"), opens Skills and ticks React. *HTTP API:* the curl command types with natural rhythm. *Agent:* the question bubble, thinking dots, then a `list_jobs` call with its arguments. At 9.4 s the React tick, the Enter key and "Running…" land together, with a ring and a progress bar on each column. Results follow: four cards, the JSON output, "Done · 1 page". | Three ways to ask. |
| 11.6–17.5 | **Same answer** | Column contents dim. A result block rises in each; three odometers roll from 0 and stop on **64** on the same frame (13.4 s), with a soft accent. A line draws across all three; under each number, the same query in that column's own form. Slow camera push. | Same data. Same answer. |
| 17.5–23.4 | **One answer** | Each card folds from the top down into its result block. The three blocks fly to the centre, tilt and stack, then merge into one card: **64**, "React jobs near Melbourne 3000", and the Panel / HTTP API / MCP badges. | Ask any way. One answer. |
| 23.4–31.3 | **You decide, your agent helps** | The card splits into two panels. Left: the job detail (eligibility cue, Decide). Right: the agent's short list of matching roles. The pointer clicks **To apply**, then **Priority**. The job id is highlighted in the panel address and in the report; a line connects them. The pointer clicks "Open in panel ↗"; the camera moves to the panel and a toast reads "Opened from your agent's report". | Same records. You decide. Your agent helps. |
| 31.3–36.8 | **Unlock more** | Agent chat: "Which tech stacks come up most across my board? Build me a report." `list_jobs` (5 pages), `get_job` counting up to ×412, "Writing tech-stack-report.html". A report window slides in: four figures, then ten bars growing in order; React and TypeScript highlight. | Unlock more insight with your own agent. |
| 36.8–40.3 | **Your questions** | Three prompts type in, one per colour: *Brief me every morning on new roles that fit.* · *Which jobs did my rules exclude, and why?* · *Compare React salaries in Melbourne and Sydney.* Each bubble then shrinks into a solid dot and flies to the end card. | Your board. Your questions. |
| 40.3–43.8 | **End card** | The three dots sit beside **AU Job Board** as the wordmark wipes in. "One board for you and your agent." The repository path appears as a plain pill. Fade to paper. | — |

## Caption rules

One line, centred in a band below the content, 46 px semibold ink. One caption at a
time; each fades and rises in, then fades out before the next. Captions never sit on
top of UI. Wording claims only what the shot shows: "same data" rather than "same
snapshot", because the API and MCP snapshots belong to different processes.

## Sound

- **Bed:** a slow pad with light plucks, changing chord at each scene turn (Fmaj9 →
  Dm9 → Bbmaj7 on the lock → F/C on the merge → Gm9 for the hand-off → Bbmaj9 → Csus2
  → Fmaj9 on the end card).
- **UI:** quiet keys while typing, short clicks under each pointer click, ticks as the
  counters and bars run, soft whooshes on the two big moves.
- **Accents:** a felt-piano chord at three moments only: the lock on 64, the job-id
  match and the end card. They are tuned to the bed's chord, slightly strummed and
  given a short room tail so they bloom rather than ring.
