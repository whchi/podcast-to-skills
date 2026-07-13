---
name: podcast-extract-candidates
description: Use as Step 3 of the podcast-to-skills workflow after transcription to identify reusable skill candidates from the transcript and write work/candidates.md before any SKILL.md generation.
---

# Podcast Extract Candidates

Identify reusable methods in the transcript.

## Inputs

- `result/transcript.txt`
- `work/metadata.json`
- `docs/methods/skill-distillation.md`

## Procedure

1. Read the full transcript.
2. Use `metadata.title` as high-weight topic context.
3. Apply `docs/methods/skill-distillation.md` Step 0 and Step 1 only as method guidance.
4. Ignore that method file's `Output format`; this workflow's file contract wins.
5. Each candidate must have a distinct trigger, inputs/outputs, and workflow.
6. Merge shallow variants that share the same workflow.
7. Write `work/candidates.md` before Step 4. One candidate per line:

   ```text
   slug-kebab-case | 中文名稱 | 一句話 summary
   ```

8. If there is no reusable method, write an empty `work/candidates.md`, report `本集內容無可萃取的 skill`, and finish normally.

## Done

- `work/candidates.md` exists before any generated `result/skills/*/SKILL.md`.
- The final report can state that the two-stage checkpoint happened.
