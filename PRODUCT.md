# How Kerf is built

One loop for every change, small or large: **Design Thinking decides what is worth building, Agile decides how it
ships.** The design record lives in [`dev-docs/DESIGN.md`](dev-docs/DESIGN.md) (the six stages for Kerf as a whole); this
file is how work moves through them, sprint by sprint.

## The loop

| Stage | What happens for Kerf | Output | Lives in |
|---|---|---|---|
| **Empathize** | Watch the change in the real editor: Premiere Pro, After Effects, Resolve (Edit, Color, Fusion pages). Read what editors report, and `~/.kerf/logs/errors.jsonl` when they share it. | A screenshot, a log line, a quote | The issue |
| **Define** | One problem, one sentence, from the editor's side: *"How might we start Kerf without Premiere asking for permission?"* | A problem statement with the evidence | The issue (Problem, Evidence) |
| **Ideate** | Two or three ways, each scored for desirability, feasibility and viability (D / F / V), as in `dev-docs/DESIGN.md` § 3. Pick the smallest that works. | The chosen approach and why | The issue (Approach) |
| **Prototype** | The cheapest real version: the panel in the browser (`npm run dev`, `?preview`), the engine CLI (`python -m kerf run`), the stand-in hosts in `tests/`. | A branch | Git |
| **Test** | Tests, the checks in the Definition of Done, then the editor itself. A change is not done until it has been seen working where editors use it. | Green CI and a hand check | The PR |
| **Implement** | Release on the train below; record what was learned. | A version and a changelog line | `CHANGELOG.md` |

When a test fails in the editor, go back to **Define**, not to the code: most of 0.3's bugs (the console window,
the permission prompt, Kerf FX missing in Resolve 21) were wrong assumptions about the editor, not typos.

## Cadence (Scrum, sized for a small team)

- **Sprint:** two weeks, ending in a release candidate.
- **Planning (30 min):** take items from the top of the backlog until the sprint is full; each must meet the
  Definition of Ready. Name one sprint goal an editor would notice.
- **Daily:** a three-line note in the sprint issue: done, next, blocked.
- **Review:** run the release candidate through the hand checklist in Premiere Pro, After Effects and Resolve.
- **Retro (15 min):** one thing to keep, one to change; the change becomes a backlog item.
- **WIP limit:** two items in progress at once. Finish before starting.

## Definition of Ready

An item can enter a sprint when it has: the editor and host it is for; the problem in one sentence with evidence;
acceptance criteria an editor could check; a size (S: under a day, M: up to three days, L: split it first).

## Definition of Done

- [ ] `pytest tests/` passes; `cd ui && npx tsc --noEmit` is clean; the panel lint (Hallmark, app scope) has 0 FAIL.
- [ ] CI is green on all four builds (Windows, macOS ARM, macOS Intel, Linux), including the OFX host test.
- [ ] Seen working in every editor it touches, from an installed build, not only in the browser preview.
- [ ] No console window opens, no permission prompt appears, nothing lags (the Graphics grid is the canary).
- [ ] Copy is plain and sentence case; errors tell the editor what to do next.
- [ ] `CHANGELOG.md` has a line an editor would understand.

## Release train

1. Work lands on a branch; push it as a test branch and run the release workflow by hand (`gh workflow run
   release.yml --ref <branch>`). It builds every installer and publishes nothing.
2. Install that build and run the hand checklist (below).
3. Merge to `main`, tag `vX.Y.Z`, push the tag: the release workflow publishes, and installed Kerf updates itself.

**Hand checklist:** the panel opens with every tab; one tool per tab runs and lands on the timeline; the Graphics
tab scrolls smoothly; no console window, no permission prompt; Kerf FX lists all its effects in Resolve; uninstall
removes the panels, Kerf FX and only Kerf's entries.

## Backlog

Ordered by value to editors. Each item names its evidence (where we saw the problem).

### Sprint 1: ship 0.3.3, stable in all three editors

| # | Item | Evidence | Size |
|---|---|---|---|
| 1 | Install the CI build here and pass the hand checklist: login watcher, no prompts, 7 Kerf FX effects in Resolve 21, uninstaller | Fixes made on `test/stabilize-ofx-only`, verified in CI only | M |
| 2 | Decide the release: move the unpublished `v0.3.2` tag or cut `v0.3.3` | `v0.3.2` was tagged, its release held | S |
| 3 | GPL compliance for the bundled ffmpeg (licence text and source offer) and a NOTICES file for bundled models and libraries | Windows build ships BtbN's GPL ffmpeg | M |
| 4 | Website legal pages and accessibility | In progress in its own session | M |
| 5 | Merge `test/stabilize-ofx-only` into `main` once 1 to 4 pass | Branch holds the 0.3.3 work | S |

### Next

| # | Item | Evidence | Size |
|---|---|---|---|
| 6 | Rebuild the MOGRT pack with vertical captions at 0.7x | 9:16 captions ran off the frame; only new builds have the fix | M (needs After Effects) |
| 7 | macOS: register `kerf://` (Info.plist) and check the watcher LaunchAgent on a Mac | Windows-only verification so far | M |
| 8 | The helper's liveness check reads the port from `engine.json` instead of assuming 7878 | Locator added in 0.3.3; the helper still hard-codes the port | S |
| 9 | Automate the Premiere and After Effects panel checks where the hosts allow it | Hand checklist is the only test of the real panels | L (split) |

### Later

| # | Item | Evidence | Size |
|---|---|---|---|
| 10 | Pro plan (hosted transcription and AI edits), see `dev-docs/MONETIZATION.md` | Listed as "Pro, later" on the site | L (split) |

## Writing issues and pull requests

Use the templates in `.github/`: an issue carries the Empathize and Define stages (who, problem, evidence,
acceptance); a pull request carries Prototype and Test (what changed, how it was checked, the Definition of Done).
