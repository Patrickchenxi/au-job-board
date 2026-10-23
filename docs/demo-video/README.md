# v1.3 product demo video

[Watch the 44-second demo on YouTube](https://youtu.be/AAfdZ548Gao), or download
the [MP4](au-job-board-v1.3-demo.mp4). This animation and the
[direct browser screenshot library](../demo-screenshots/README.md) are separate
showcases with different synthetic datasets.

| File | What |
|---|---|
| [`au-job-board-v1.3-demo.mp4`](au-job-board-v1.3-demo.mp4) | Final cut: 1920x1080, 60 fps, 2628 frames, 43.8 s, H.264 High / yuv420p (BT.709) + AAC 48 kHz stereo, CRF 17, ~8.5 MB |
| [`cover.png`](cover.png) | Cover / poster frame (the merged answer, 0:21.6), 1920x1080 |
| [`banner-en.png`](banner-en.png) · [`banner-zh.png`](banner-zh.png) | Banners, 1600x800, English / Chinese (same design; title, short copy and the agent's sentence differ) |
| [`script.md`](script.md) | Approach, storyboard, timing and captions |

## Public description (safe to reuse)

> One question, asked three ways: in the panel, over the HTTP API, and by an AI
> agent through MCP. All three come back with the same answer from the same board.
> You decide on a job while your agent reads the same records, and your own agent
> can go further, such as building a tech-stack report or answering questions you
> come up with. All companies, roles and numbers are synthetic.

The captions, cover and this description name no release number. The end card shows
the product name and the repository path (`github.com/SkywingJam/au-job-board`) as
plain, non-clickable text.

## What is real and what is drawn

This cut is a **code-drawn animation**, not a screen recording. Every frame was
rendered from one HTML composition. The panel, terminal, agent chat and report are
redrawn to match the real UI, condensed to fit three columns. Layout follows the real
app as closely as the frame allows; where the two conflict, the content stays exact and
the layout gives way.

The content on screen was taken from the real application at `eb56c4f`
(release/v1.3.0.1), run on a generated synthetic dataset:

- **Dataset.** 468 generated postings (412 after de-duplication) with fictional
  companies and `example.invalid` links, analysed by the normal `analyze` with the
  demo rules and the default skill vocabulary. Like the v1.3.0.1 screenshot mock, the
  dataset records two synthetic fetch batches and a terminal successful pipeline run,
  so the panel reads "Last fetched … ago". These are display fields, not a real fetch.
- **Panel column.** The real flow and values: Location → `3000` → Apply
  ("20 of 208 on this page") → Skills → React ("20 of 64 on this page"). The listed
  jobs, tags, scores and skill counts match the real panel in English.
- **HTTP API column.** A runnable request against the read-only API,
  `curl -G …/api/v1/jobs -d geo=3000 -d skill=React | jq '{total, snapshot_id}'`, and
  its real output (`"total": 64` and the returned snapshot id).
- **Agent column.** The real MCP tool and arguments,
  `list_jobs {"query": {"geo": "3000", "skill": "React"}}`, which returned
  `total: 64` in one page. The chat window around it is drawn and represents no
  particular client.
- **Hand-off.** The detail is the real job `seek:SYN-0018` (eligibility cue, Decide
  buttons, Priority). The link between the two sides is the job id in the real
  `panel_url` returned by the API.
- **Report.** An agent-style report built from all 412 records over `list_jobs`
  (5 pages) and `get_job`. Every figure is counted from the same data: React 128
  (31.1%), SQL 127, AWS 116; 35 rule-excluded, so 377 pass.
- **Drawn, not product UI.** The pointer, captions, the agent chat window, the agent's
  notes in the report, the three follow-up prompts and the end card.

"Near 3000" uses the app's own location contract: the 3000 CBD postcode is an exact
match and other recognised Victorian places are near. HTTP API and MCP snapshots
belong to separate processes, so their ids differ. The video therefore shows the
same *query* under each answer, not a shared snapshot.

## How it was made

- **Composition.** One 1920x1080 HTML page with a small deterministic timeline
  (springs, eases, typing, odometer counters, path motion) written for this video,
  because no animation library could be installed in the build sandbox. Every frame
  is a pure function of time, so the page can be previewed with a scrubber and
  rendered frame by frame.
- **Render.** Playwright drives headless Chromium. Each frame is sampled twice
  (120 Hz) and blended into 60 fps for light motion blur, then encoded with ffmpeg.
  Moving elements are composited layers, which keeps text from shimmering while the
  camera eases.
- **Audio.** A soft music bed and UI sounds (keys, clicks, a felt-piano accent at the
  three key moments) were synthesised with numpy and placed on the same timeline as
  the animation. No samples, no voice-over. The mix is loudness-normalised to -18 LUFS.
- **Fonts.** Inter and DejaVu Sans Mono (the panel's own stack falls back to these
  in the Linux render environment).

The composition, dataset generator, capture and audio scripts are maintainer tools
and are not distributed; the committed MP4, cover and banners are the result. The
build sandbox lacked `ruamel.yaml` (used only by Settings editing), so a local stub
was on `PYTHONPATH` while the app ran. Nothing in the video touches Settings.

## Banners

Two stills, `banner-en.png` / `banner-zh.png`, 1600x800, refreshed for v1.3. Same
design in both; only the title, short copy and the agent's sentence differ. Layout as
before: on the left, a three-line title (last line in the accent colour) and a two-line
value line; on the right, a real panel screenshot in a 12 px-radius card that bleeds off
the right and bottom edges. A small floating agent card overlaps the screenshot. Uses the
panel's paper / ink / accent tokens; the three dots above the title are the
panel / HTTP API / MCP colours.

| | Title | Short copy |
|---|---|---|
| EN | Collect. Screen. **Ask.** | One board for you and your agent. |
| ZH | 集中岗位 / 快速筛选 / **随心发问** | 一块看板，你和你的 agent 共用。 |

- Screenshot: the real panel at `eb56c4f` (normal `jobs.cli panel`, no Demo mode,
  English, light theme, 1440x1000 at 2x, shown at 0.72x) on the same generated
  synthetic dataset. The view is All with Location 3000 and Skills React; the open
  detail is a synthetic job marked To apply and starred.
- Agent card: drawn for the banner and not product UI. The call and the answer are the
  real `list_jobs` request and its `total` (64) on the same dataset, read through the
  app's MCP endpoint.
- No repository name, address or release information. The UI header shows "AU Job Board".

The banners were rendered from a small HTML page with Playwright (headless Chromium,
1600x800 at 1x, Inter / Noto Sans CJK SC).

## Versions

- Application shown: `eb56c4fef036daebd48e0723acf4f7468cc2e0f3` (release/v1.3.0.1);
  synthetic dataset generated with an anchor date of 2026-10-23.
- Playwright 1.63.0 (Node), headless Chromium (Playwright build 1243), Node 22.22.0,
  Python 3.13, numpy 2.5.3, scipy 1.18.1, ffmpeg 6.1.1 (libx264 + AAC).

## Limits

- Not a screen recording. The panel column is a condensed redraw; the real panel
  has more filters and a wider layout. The pointer is drawn.
- Light theme, English UI, desktop layout only.
- The agent chat window and the agent's notes are illustrative. The tool calls,
  arguments and returned totals are real; the wording of an agent's answer depends
  on the client and model used.
- Relative times ("Last fetched 1 min ago") and listing dates follow the dataset's
  anchor date and the capture moment.
- The previous 30-second walkthrough (v1.0 UI, Remotion, real screen capture) has been
  replaced by this cut. It remains in the repository history.
