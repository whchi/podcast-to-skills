# AGENTS.md

The coding agent should execute the podcast-to-skills workflow exactly as `WORKFLOW.md` defines it.

## Repository Contract

- `WORKFLOW.md` is the execution contract.
- `.agents/skills/*/SKILL.md` contains the executable step instructions.
- `docs/methods/skill-distillation.md` guides candidate extraction and SKILL.md generation.
- `docs/methods/skill-review-rubric.md` guides review evidence and scoring.
- `README.md` is the human usage entry point.

If files disagree, prefer `WORKFLOW.md` for runtime behavior and update the
other file instead of silently blending conflicting instructions.

## Hard Rules

- Do not add repository code that calls external LLM APIs.
- Do not use RSS fallback, RSS direct input, or `og:audio` scraping.
- Do not overwrite an existing `work/`; it is failed-run debug material.
- Do not delete arbitrary user-provided paths. Cleanup is limited to repo-local
  fixed paths named in `WORKFLOW.md`.
- Do not pause midway for episode confirmation. Include metadata in the final
  report.
- Do not batch-process multiple URLs pasted in chat. Batch input is only a
  user-specified repo-root file named exactly `podcasts.jsonl` (format:
  `podcasts.jsonl.example`); for pasted multi-URL requests, process nothing and
  direct the user to that file.
- Do not generate skill source citations, podcast/show/episode names, or
  timestamps inside generated SKILL.md files.

## Coding Workflow

For code changes, use test-first development:

1. Write or update a focused test for deterministic behavior.
2. Run the targeted test and confirm it fails for the expected missing behavior.
3. Implement the smallest production change.
4. Run the targeted test.
5. Run `.venv/bin/python -m unittest discover` before claiming completion.

External boundaries such as iTunes Lookup, audio download, Whisper, and OpenCC
should be injectable in tests. Do not hit the network or download Whisper models
from unit tests.

Use `uv sync` only for first-time setup or dependency changes. After `.venv/`
exists, every workflow command must call `.venv/bin/python` directly.

## Runtime Flow For Podcast Conversion

When asked to convert an episode:

1. Read `WORKFLOW.md`.
2. Load and execute each `.agents/skills/*/SKILL.md` listed in `WORKFLOW.md`, in order.
3. Treat the step skill as authoritative for commands, inputs, outputs, failure behavior, and done checks.
   Step 2 starts a detached transcription worker and polls `status --json`; it
   must not block on a long foreground Whisper command.
4. On success, report the final outputs and remove only `work/`. On failure, keep `work/` and report the last completed step.

When the user explicitly names `podcasts.jsonl` (or `podcasts.jsonl.example`),
run `.agents/skills/podcast-batch-convert/SKILL.md` instead. When the user
pastes multiple episode URLs in chat, process none and point them to
`podcasts.jsonl.example`.

## Acceptance Before Completion

Completion requires evidence for all of these:

- `README.md` explains setup, usage, outputs, manual script commands, and tests.
- `AGENTS.md` gives enough instruction for a coding agent to follow the flow.
- `WORKFLOW.md` lists only step order and points to `.agents/skills/*/SKILL.md`.
- Every workflow step has a project-local skill.
- `scripts/fetch_episode.py` and `scripts/transcribe.py` exist.
- `.venv/bin/python -m unittest discover` passes.
- The final implementation preserves the no-external-LLM-code constraint.
