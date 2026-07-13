---
name: podcast-preflight
description: Use as Step 0 of the podcast-to-skills workflow before fetching audio. Validates repo files and `.venv/bin/python` dependencies, then protects failed-run debug material.
---

# Podcast Preflight

Prepare a clean one-shot run without overwriting debug material.

## Inputs

- Repo root.
- One Apple Podcast episode URL containing `i=` is expected by later steps.

## Procedure

1. Confirm you are at repo root.
2. Confirm these paths exist:
   - `WORKFLOW.md`
   - `scripts/fetch_episode.py`
   - `scripts/transcribe.py`
   - `docs/methods/skill-distillation.md`
   - `docs/methods/skill-review-rubric.md`
3. Check dependencies before downloading audio using the project Python:

   ```bash
   .venv/bin/python -c "import ctranslate2, faster_whisper, opencc, requests"
   command -v ffmpeg
   command -v ffprobe
   .venv/bin/python scripts/transcribe.py doctor
   ```

   `doctor` must print a selected profile. On Apple Silicon, a warning that
   `whisper.cpp` is unavailable is actionable and means the run will use the
   slower faster-whisper CPU fallback; an explicit `--engine whisper-cpp`
   request must fail instead of silently falling back.

4. If `work/` already exists, stop. Treat it as debug material from a failed run.
5. Recreate only repo-local output directories:
   - Clear and recreate `result/`
   - Create `work/raw/`
   - Create `work/processed/`

Batch mode override: when running inside `podcast-batch-convert`, skip the
`result/` clearing (the batch skill clears `result/` once at batch start);
every other check in this skill still applies per episode.

## Guardrails

- Do not accept any user-supplied deletion target.
- Cleanup paths are fixed and repo-local.
- If `.venv/bin/python` is missing or dependencies cannot import, stop with:

  ```text
  缺少 Python 套件:{名稱}。請先執行 uv sync
  ```

## Done

- Required files exist.
- Dependencies import.
- `ffmpeg`, `ffprobe`, and the selected transcription profile are available.
- `result/`, `work/raw/`, and `work/processed/` are ready.
- No previous `work/` debug state was overwritten.
