# Kerf design brief (design thinking)

Framework: Stanford d.school's five modes (Empathize, Define, Ideate, Prototype, Test) plus NN/g's Implement step.
The modes loop; Test sends us back on purpose.

## 1 · Empathize

**Who:** video editors cutting talking-head, vlog, podcast and short-form work in Premiere Pro, After Effects or
DaVinci Resolve, often all three in one week, on deadline, on one machine.

Observations (what we saw) and interpretations (what we think it means) are kept apart.

| Observation | Interpretation |
|---|---|
| A punch-in zoom is 4–6 keyframes per clip, eased by hand, repeated for every cut in a 60-clip edit. | The work isn't hard, it's repetitive; time goes into the same five gestures. |
| A camera shake is either a third-party preset or wiggle expressions retyped per layer. | Editors rebuild the same effect instead of reusing it. |
| A 16:9 clip in a 9:16 sequence has to be rescaled before any effect; Kerf 0.2.2 zooms reset it to letterboxed. | An effect that ignores the clip's framing is worse than no effect: it creates cleanup. |
| The Premiere panel showed "engine offline" with the engine running (Premiere 2026 permissions). | The first-run moment decides trust; a dead panel reads as a broken product. |
| The AE panel was grey ScriptUI; the Resolve window showed garbled characters and a JSON box. | Inconsistent, odd-looking UI reads as unfinished and makes editors second-guess every click. |
| Panels didn't scroll; buttons were grey slabs in Premiere; sliders showed 144.22199992451814%. | Small visual defects compound into "this is buggy". |
| The editor runs three editors at once; Premiere and AE both quit unexpectedly during testing. | Anything that runs inside the editor must never be the reason it crashes. |
| A separate "Kerf Studio" window had to be opened and kept around. | Editors want the tool where they already are, not another app to manage. |

## 2 · Define

**POV:** A working video editor needs to apply the effects they repeat every day — zooms, shakes, speed ramps,
captions, cuts, reframes — in one action, inside the editor they're already in, because every minute spent
re-keyframing the same move is a minute not spent on the story, and anything that breaks their project costs more
than it saves.

**How might we** let editors apply their everyday effects in one click, in their own editor, with results that fit
the timeline they're in and never put their project at risk?

Success criteria (what "on point" means, checked in Test):

1. **One action** for each everyday effect, with sensible defaults; settings are optional, never required.
2. **Fits the context:** uses the open sequence/comp/timeline, its resolution, fps, aspect ratio and each clip's own
   framing. No cleanup after.
3. **Safe:** Premiere/Resolve edits land in a new sequence/timeline; After Effects changes are one undo group.
   Nothing runs on a timer inside the editor.
4. **Same Kerf everywhere:** one look, one vocabulary and one layout in Premiere, After Effects and Resolve; each shows
   only what works there.
5. **Always answers:** every click gives visible feedback (working…, done, or a plain-language fix), never silence.
6. **Zero setup:** one installer; the engine starts when a panel opens and stops when the editors close.

## 3 · Ideate

Diverged widely, then converged against desirability / feasibility / viability:

| Idea | D | F | V | Kept? |
|---|---|---|---|---|
| Kerf Studio desktop app as the hub | low (another app) | high | high | **dropped** (user feedback) |
| Native panel per editor sharing one UI (UXP Premiere, CEP After Effects) | high | high | high | **yes** |
| Resolve: Kerf-styled native window (Qt) | high | high | high | **dropped** (Resolve is Kerf FX only: OpenFX effects) |
| Effects build on each clip's existing Scale/Position | high | high | high | **yes** |
| Capability map: show only what an editor supports | high | high | high | **yes** |
| Background installer that sets up engine + all panels | high | medium | high | **yes** |
| Live chip: project · sequence · playhead | medium | high | high | **yes** |
| Timer-driven heartbeats in ExtendScript | low (crash risk) | high | — | **dropped** |
| Settings as raw JSON | low | high | — | **demoted** to "More settings" |

## 4 · Prototype

| Piece | Where |
|---|---|
| Shared UI (React), capability map, host adapters | `ui/src/host.ts`, `App.tsx`, `Toolkit.tsx` |
| Premiere UXP rendering fixes (buttons, SVG, sliders) | `ui/src/uxp-jsx-runtime.ts`, `ui/vite.config.ts` |
| After Effects HTML panel calling native AE tools | `aftereffects/cep/`, `aftereffects/Kerf.jsx` (`KerfAE.call`) |
| Kerf FX for Resolve (OpenFX) | `ofx/kerf_fx.cpp` |
| Engine: live editors, follow-editors, framing | `kerf/hosts.py`, `kerf/timeline.py` |

## 5 · Test

Tasks, not tours. Each row is checked in the real editor with a scratch project; results go in the release notes.

| Task | Premiere | After Effects | Resolve |
|---|---|---|---|
| Open the panel cold: it connects and shows the live chip | | | |
| Punch-in zoom on a 9:16 clip keeps its fill framing | | | |
| Camera shake (HV) on the clip at the playhead | | | |
| Speed ramp on the clip at the playhead | | | |
| Add null / solid / adjustment | | | |
| Beat markers from a music clip | | | |
| Stabilize | | | |
| Quick mask cutout | | | |
| Frame export, project sort | | | |
| Captions | | | |
| An Edit feature end to end (silences) | | n/a | |
| Panel resizes narrow/short: no overflow, scrolls | | | |
| Every failure shows a plain-language message | | | |

Automated: `python tests/test_core.py` (engine), `python tests/smoke_features.py` (every feature with defaults),
UI typecheck + build, ExtendScript harness for `KerfAE.call` in a scratch AE project, Resolve API harness.

## 6 · Implement

Ship only what passed Test; note anything untested in the release notes rather than implying it works.
