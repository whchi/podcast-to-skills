# Podcast to Skills Workflow

This file is the orchestration order only. Step instructions live in
project-local skills under `.agents/skills/*/SKILL.md`.

## Settings

```text
SCORE_THRESHOLD = 7.0
CUSTOM_REVIEW_CRITERIA =

HARD_RULES:
- Do not call external LLM APIs from repository code.
- Generated SKILL.md files must not mention source citations, podcast/show/episode names, or timestamps.
- Generated SKILL.md frontmatter must use name = slug, lowercase [a-z0-9-].
- The Chinese skill title belongs in the SKILL.md H1, not in frontmatter name.
```

If `CUSTOM_REVIEW_CRITERIA` is blank, omit the custom score dimension.

## Input

- **Single mode (default):** one Apple Podcast episode URL containing `i=`.
- **Batch mode:** only when the user explicitly points to a JSONL file named
  exactly `podcasts.jsonl` (format reference: `podcasts.jsonl.example`). Other
  filenames are rejected — ask the user to rename to `podcasts.jsonl`. Batch
  execution is defined by `.agents/skills/podcast-batch-convert/SKILL.md`.
- **Multiple URLs pasted in chat:** not a batch request. Process none of them;
  reply asking the user to create `podcasts.jsonl` following
  `podcasts.jsonl.example` and to explicitly request batch processing.

## Skill Order

Run these project-local skills in order:

| Step | Skill | Purpose | Main outputs |
|---|---|---|---|
| 0 | `.agents/skills/podcast-preflight/SKILL.md` | Verify setup and clean run directories | `work/raw/`, `work/processed/`, `result/` |
| 1 | `.agents/skills/podcast-fetch-episode/SKILL.md` | Fetch episode metadata and MP3 | `work/metadata.json`, `work/processed/episode.mp3` |
| 2 | `.agents/skills/podcast-transcribe-episode/SKILL.md` | Transcribe MP3 to text with resumable worker | `work/transcript.json`, `result/transcript.txt`, `work/transcription/status.json` |
| 3 | `.agents/skills/podcast-extract-candidates/SKILL.md` | Extract reusable skill candidates | `work/candidates.md` |
| 4 | `.agents/skills/podcast-generate-skills/SKILL.md` | Generate installable skills | `result/skills/<slug>/SKILL.md` |
| 5 | `.agents/skills/podcast-review-skills/SKILL.md` | Evidence-first review and scoring | `result/review.md`, `result/scores.json` |
| 6 | `.agents/skills/podcast-report-cleanup/SKILL.md` | Report final results and clean temp files | user report, `work/` removed on success |

Batch mode wraps Steps 0–5 per episode (see
`.agents/skills/podcast-batch-convert/SKILL.md`): `result/` is cleared once at
batch start, each episode's artifacts move to `result/{episode_id}/`, and
`result/batch-summary.json` tracks per-line status.

## Supporting References

- `docs/methods/skill-distillation.md`: method guidance for candidate extraction and skill generation.
- `docs/methods/skill-review-rubric.md`: review lens for generated skills.

The support references are method guidance only. Output contracts are defined by
the step skills above.

## Completion

A successful run ends with:

- `result/transcript.txt`
- one or more `result/skills/<slug>/SKILL.md`, or an explicit no-candidate result
- when at least one skill was generated: `result/review.md` and `result/scores.json`
- when `work/candidates.md` is empty: Steps 4 and 5 are skipped; no `result/skills/`, `result/review.md`, or `result/scores.json` are produced
- final report to the user
- `work/` removed only after success

A successful batch run ends with `result/{episode_id}/` per completed episode
plus `result/batch-summary.json`. Each completed episode keeps
`metadata.json`, `transcript.txt`, and `candidates.md`; episodes with extracted
skills also keep `skills/`, `review.md`, and `scores.json`.
