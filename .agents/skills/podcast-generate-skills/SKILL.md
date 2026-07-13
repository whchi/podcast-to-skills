---
name: podcast-generate-skills
description: Use as Step 4 of the podcast-to-skills workflow to turn work/candidates.md entries into installable result/skills/<slug>/SKILL.md files.
---

# Podcast Generate Skills

Turn each candidate into an installable agent skill.

## Inputs

- `work/candidates.md`
- `result/transcript.txt`
- `docs/methods/skill-distillation.md`

## Procedure

If `work/candidates.md` is empty, skip this step and Step 5 (no `result/skills/`,
`result/review.md`, or `result/scores.json`); proceed directly to
`podcast-report-cleanup`.

Otherwise, process candidates one at a time. Do not batch-generate all skills in one pass.

For each candidate:

1. Create `result/skills/{slug}/SKILL.md`.
2. Use frontmatter:

   ```yaml
   ---
   name: slug-kebab-case
   description: Use when ... Do NOT use for ...
   ---
   ```

3. Put the Chinese skill name in the H1.
4. Write in Traditional Chinese.
5. Focus on repeatable procedure, decision rules, guardrails, output contract, and definition of done.
6. Apply `docs/methods/skill-distillation.md` Step 2, Step 3, Step 4, Step 5, and Step 7 as quality guidance.
7. Ignore that method file's `Output format` and `Test prompts` sections.
8. Ensure the skill still works when the original transcript is forgotten.

## Hard Rules

- No source citations.
- No podcast/show/episode names.
- No timestamps.
- No unsupported single-case detail promoted into universal law.

## Done

- Every candidate has `result/skills/{slug}/SKILL.md`.
- Frontmatter `name` equals the slug and uses lowercase `[a-z0-9-]`.
- Generated skills do not depend on access to the original transcript.
