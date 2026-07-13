---
name: podcast-report-cleanup
description: Use as Step 6 of the podcast-to-skills workflow after review to report outputs, warnings, subagent usage, and clean up work/ on success.
---

# Podcast Report Cleanup

Report results and clean temporary state.

## Inputs

- `work/metadata.json`
- `work/candidates.md`
- `result/skills/*/SKILL.md` (absent if `work/candidates.md` was empty)
- `result/review.md` and `result/scores.json` (absent if no skills were generated)

## Final Report Order

1. Episode metadata: author, show, title, published.
2. State that `work/candidates.md` was created before Step 4.
3. If `work/candidates.md` was empty, report `本集內容無可萃取的 skill` and skip
   items 4–6 below.
4. Otherwise, for each skill: path, total, pass/fail, one-line review.
5. Group warnings and improvement suggestions for scores below threshold.
6. Include `result/` path.
7. State whether subagent review was used.

## Cleanup

- On success, delete only the fixed repo-local path `work/`.
- On failure, keep `work/` and report the last completed step plus debug paths.

## Done

- User can find all outputs under `result/`.
- `work/` is removed only after successful completion.
- Failures preserve debug material.
