# 0003 Estimating shooting order without file system times

## Context

Photos and videos saved from LINE often lose EXIF, and saving rewrites the file modification time. Issue #5 asks for an order built from the remaining clues, with a basis and a confidence (high / medium / low) for every file.

## Decision

Clues are combined in this order:

1. EXIF `DateTimeOriginal` (then `DateTimeDigitized`, then `DateTime`) for photos, and the `mvhd` creation time for MP4/MOV. Confidence high. MP4 times are stored in UTC and are converted to this computer's time zone so they line up with EXIF local times.
2. A date and time in the file name (`20231015_123456`, `2023-10-15 12.34.56`, 13-digit Unix milliseconds). Confidence medium.
3. Groups: files with times less than 10 minutes apart are one group, and photos whose 64-bit dHash differs by at most 10 bits are one group, unless both have times more than one hour apart. A photo with no time is placed right after the most similar timed photo in its group, with medium confidence. Groups are ordered by their earliest time; groups with no time at all go last with low confidence.
4. Itinerary: when stops are given, a group takes the earliest stop assigned to any of its members. Groups with a stop are ordered by stop number; groups without a stop go last and are flagged "未對應". Until #7 adds automatic matching, the owner assigns stops per group in the web page.

The file system modification time is never read for ordering. Exact duplicates are found by SHA-256 of the content; the first file by path is kept. The owner can reorder by drag-and-drop; files that the owner moved (those not on the longest run that kept the automatic order) are marked "手動調整".

The LINE chat export is only parsed for the send times of photo and video messages, shown per day as a reference. It does not change the order, because a message cannot be linked to a saved file reliably.

## Alternatives

- Using the file modification time: wrong after a LINE save, which is the whole problem.
- Matching LINE message times to files: LINE file names carry no message id, so the match would be a guess.
- A learned image embedding instead of dHash: better at "same place, different angle", but needs a model download. Revisit in #7.

## Consequences

The thresholds are constants in `travelphotos/ordering.py`. dHash finds near-identical shots (bursts, re-sends), not different views of the same place. #7 will plug automatic stop matching into the `assignments` input.
