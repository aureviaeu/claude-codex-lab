# 0013 Photos with no readable place name: 不確定, then a guess (推測) from neighbouring photos

## Context

Issue #32: after #22 three real photos still got no stop: a building with no text (Kinkaku-ji), a convenience-store sign at Kyoto Station (text that is not a place name), and a junction sign near Fushimi Inari with several place names (no single stop). The owner decided (2026-11-22): such a photo is first marked 不確定, then the most likely stop is guessed from the photos before and after it by time order / sort position; a guess is labelled 推測, kept apart from text results, and can be changed by hand. No building-recognition model, no itinerary aliases. A guess must not cross into a wrong stop when the neighbours belong to different stops. Photos read directly, manual choice, 未對應, and a hotel listed twice must not get worse. Measure with the benchmark, including the owner's own photos kept out of git.

## Decision

- **Where**: a fifth step in `places/pipeline.analyze`, after text, look-alike matching and repeated-stop resolution (ADR 0010). Only groups still without a stop are touched, so a stop read from text is never changed.
- **Rule**: a group without a stop takes the stop of its nearest identified neighbours only when the nearest one before and the nearest one after are at the *same itinerary stop* (same index). Otherwise it stays 不確定, with the reason in its evidence: the two different stops, or that one side has no identified photo (first or last photos of the trip). "Same index" means two visits to one hotel (ADR 0010 splits them by day) are different stops, so a photo between the two nights is not guessed onto either.
- **Neighbours**: identified groups (text or look-alike) found before this step. A guess never feeds another guess, so a run of uncertain photos is guessed only when the identified photos on both ends agree. A group with a capture time looks at timed groups in time order, and is guessed only when both neighbours were taken on the same date as the group (a stop photographed on two days says nothing about the photos between those days; review note); a group with no time looks at all groups in file-name order (camera counters), because it has no time to compare.
- **Labels**: `GroupPlace.method = "inferred"`, confidence low. The summary label is 推測 (not 高/中/低), the headline `推測：<stop>`; a group with no stop is 不確定, which replaces 未知 everywhere (page, `places.md`, report column), including without an itinerary, so the page uses one word for "no stop". A group whose automatic stop the owner set to 未對應 shows 手動指定：未對應. The page shows the headline next to the group's stop menu, in its own colour (`.place-guess`, the existing `--medium` colour, contrast checked by #27's test), and the finish message counts guessed and uncertain groups.
- **Override**: a guessed stop is an automatic assignment like any other (ADR 0010): the owner's choice in the menu wins and survives a re-run; 未對應 by hand is kept.
- **Benchmark** (`python -m travelphotos.places.benchmark`): new ordered *sequences* (`sequences.json`, or `sequence.csv` for one trip) where `expected` is what the app should finally show (null = must stay 不確定). Each photo is one group; the app's own text decision and `pipeline.infer_in_order` are run, and counts are printed before and after the guess (hits from text, hits from 推測, uncertain, wrong stops). Public cases are in `tests/data/sequences/` (real photos from `tests/data/signs/` plus two images drawn by this project: a two-name junction sign and a fictional store sign). The owner's photos go in `benchmark-local/` (in `.gitignore`, test-checked); it is read after the public set whenever it exists, with its own `labels.*`, `sequence(s).*` and optional `itinerary.txt`; `--local DIR` names another folder.

Measured with the real models on this computer:

| Set | Before | After |
| --- | --- | --- |
| Single sign photos (`tests/data/signs`) | 命中 8/13, 錯站 0, 誤判 0/12 | 命中 8/13, 錯站 0, 誤判 0/12 (unchanged: per-photo text only) |
| Sequences (`tests/data/sequences`, 16 photos with a stop, 3 that must stay uncertain) | 命中 11/16, 錯站 0 | 命中 16/16 (text 11, 推測 5), 錯站 0, 3/3 kept 不確定 |

## Alternatives

- **Guess from one neighbour** (the nearest identified photo on either side, or the closer in time): more guesses, but at the start or end of a stop it would put a photo taken on the way onto the stop before or after. Ruled out by the owner's "no wrong stop across segments".
- **A tighter time limit** (e.g. neighbours within an hour): photos without capture time have no time, and two identified photos at the same stop on the same date already bound the gap. Not needed for the cases in the issue; revisit with the owner's photos if a long gap gives a wrong guess.
- **Restrict a multi-name sign to the names on it**: a sign at Kyoto Station listing other destinations would then never be guessed as Kyoto Station. The neighbours are the stronger evidence.
- **Let guesses chain** (a guessed group becomes a neighbour): would spread one stop over long runs of photos with no evidence.
- **Using manual choices as neighbours**: the analysis runs on its own and manual choices win afterwards; mixing them in would make a re-run depend on edit order. Revisit if the owner wants it.
- **Keep 未知 and add 不確定 only for guessed-but-failed cases**: two words for "no stop" on one page.

## Consequences

- Photos with no sign between two photos of one stop now land on that stop, labelled 推測 and low confidence, instead of going last as 未知.
- A wrong guess is possible when someone leaves a stop and comes back with photos elsewhere in between, all without signs. It is labelled 推測 and can be changed in the menu.
- The benchmark measures the guess on single-photo groups in a given order; it does not run grouping by similarity or look-alike matching. The owner can measure their real photos without committing them.
