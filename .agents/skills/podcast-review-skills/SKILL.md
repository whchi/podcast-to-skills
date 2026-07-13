---
name: podcast-review-skills
description: Use as Step 5 of the podcast-to-skills workflow to review generated skills with evidence-first scoring and produce result/review.md plus result/scores.json.
---

# Podcast Review Skills

Review generated skills with evidence before scoring.

## Inputs

- `result/transcript.txt`
- One generated `result/skills/{slug}/SKILL.md`
- `docs/methods/skill-review-rubric.md`

If no skills were generated (Step 4 was skipped because `work/candidates.md` was
empty), skip this step entirely and proceed to `podcast-report-cleanup`.

## Subagent Rule

If the runtime supports subagents, review each skill in an independent subagent with only the inputs above and this rubric. If unavailable, continue in the same context and state that limitation in the final report.

The parent agent aggregates every subagent's evidence and scores into the single
`result/review.md` and `result/scores.json` files described below — each skill
gets its own section/array entry in these shared files, not a separate file per
subagent.

## Evidence File

For each skill, write evidence before assigning scores. Save evidence in `result/review.md`:

```md
# Review Evidence

## {skill name}

### faithfulness
- Evidence: ...
- Score: 8.5

### actionability
- Evidence: ...
- Score: 7.0

### reusability
- Evidence: ...
- Score: 8.0

### custom
- Evidence: ...
- Score: 8.0
```

Omit `custom` when `CUSTOM_REVIEW_CRITERIA` is blank.

## Rubric

- `faithfulness`
  - 10: every claim can be located in the transcript
  - 7: one minor extrapolation
  - 4: one or more claims lack support
  - 2 or below: clear hallucination
- `actionability`
  - 10: directly executable, complete steps
  - 7: mostly executable but missing prerequisites
  - 4: vague mindset advice, hard to apply
- `reusability`
  - 10: trigger is clear and the skill works without transcript context
  - 7: usable but trigger is vague or scope is broad
  - 4: requires episode context to understand
  - 2 or below: unusable away from the source
- `custom`
  - Use `CUSTOM_REVIEW_CRITERIA`; if no anchors are provided, first write 10/7/4 anchors in `result/review.md`.

## Scores File

Write `result/scores.json`:

```json
{
  "episode": {"title": "EP678", "author": "...", "published": "2026-..."},
  "threshold": 7.0,
  "skills": [
    {
      "name": "...",
      "path": "result/skills/xxx/SKILL.md",
      "scores": {"faithfulness": 8.5, "actionability": 7.0, "reusability": 8.0},
      "total": 7.8,
      "pass": true,
      "review": "一句話理由 + 改善建議"
    }
  ]
}
```

## Self-Check

- `scores.json` parses with `json.loads`.
- All scores and totals have one decimal place.
- `total = round(average(active dimensions), 1)`.
- `pass = total >= SCORE_THRESHOLD`.
- `result/review.md` has evidence for every scored dimension.
