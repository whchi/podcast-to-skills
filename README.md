# Podcast to Skills

Turn one Apple Podcast episode URL into reusable agent skills.

The repository is an agent workflow, not an app server. Python scripts handle
deterministic work (fetching audio and transcription). The executing coding
agent follows `WORKFLOW.md` for step order, then loads the matching project-local
skill under `.agents/skills/` for each step.

## Requirements

- Python 3.13
- `uv`
- An agent runtime that can read/write files and run shell commands
- `ffmpeg` and `ffprobe` on `PATH` for long-audio chunk preparation
- Optional: `whisper-cli` plus a whisper.cpp model for Metal/Core ML on Apple Silicon

## First-Time Setup

From the repo root, install Python packages once:

```bash
uv sync
```

This creates or updates `.venv/`. After setup, every project command in this
repo should call `.venv/bin/python` directly.

## Usage

Ask your coding agent to run the workflow with an Apple Podcast episode URL:

```text
Follow WORKFLOW.md for this episode:
https://podcasts.apple.com/tw/podcast/.../id1500839292?i=1000776355683
```

The URL must be an Apple Podcast episode URL containing `i=`.

### Batch Mode

To convert several episodes in one go, create `podcasts.jsonl` at the repo root
(format: see `podcasts.jsonl.example`, one `{"url": "..."}` per line), then
explicitly ask the agent to use it:

```text
Follow WORKFLOW.md in batch mode using podcasts.jsonl
```

Batch mode only accepts the filenames `podcasts.jsonl` and
`podcasts.jsonl.example`. Pasting multiple URLs in chat does not start a batch —
the agent will ask you to use `podcasts.jsonl` instead. Batch outputs land in
`result/<episode_id>/` plus a `result/batch-summary.json` status file.

## What Gets Produced

Successful runs create:

- `result/transcript.txt`
- `result/skills/<slug>/SKILL.md`
- `result/review.md`
- `result/scores.json`

If a transcript has no reusable method to extract, the workflow completes
without `skills/`, `review.md`, or `scores.json`; the final report states
`本集內容無可萃取的 skill`.

Batch runs keep per-episode inspection artifacts under `result/<episode_id>/`:

- `metadata.json`
- `transcript.txt`
- `candidates.md`
- `skills/`, `review.md`, and `scores.json` only when candidates were found

Temporary files live under `work/`. On success the agent deletes `work/`; on
failure it keeps `work/` for debugging.

Long transcriptions keep `work/transcription/status.json`, `manifest.json`,
`worker.log`, normalized audio chunks, and completed chunk checkpoints. A killed
worker can be resumed without starting the entire MP3 again.

## Workflow Skills

The detailed agent instructions live in project-local skills:

- `.agents/skills/podcast-preflight/SKILL.md`
- `.agents/skills/podcast-batch-convert/SKILL.md` (batch mode orchestration)
- `.agents/skills/podcast-fetch-episode/SKILL.md`
- `.agents/skills/podcast-transcribe-episode/SKILL.md`
- `.agents/skills/podcast-extract-candidates/SKILL.md`
- `.agents/skills/podcast-generate-skills/SKILL.md`
- `.agents/skills/podcast-review-skills/SKILL.md`
- `.agents/skills/podcast-report-cleanup/SKILL.md`

`WORKFLOW.md` only declares the order and main outputs.

## Manual Script Commands

The full workflow should be run by an agent, but the deterministic stages can be
run manually:

```bash
.venv/bin/python scripts/fetch_episode.py "<apple_podcast_url>"
.venv/bin/python scripts/transcribe.py
.venv/bin/python scripts/transcribe.py status --json
# after an interrupted worker:
.venv/bin/python scripts/transcribe.py resume
```

The no-argument transcription command starts a detached worker and returns
quickly, so a one-hour MP3 does not depend on a single long-lived shell command.
Use `doctor` to inspect the selected engine and platform profile:

```bash
.venv/bin/python scripts/transcribe.py doctor
```

On Apple Silicon, the preferred backend is whisper.cpp with Metal/Core ML when
`whisper-cli` and its model are installed. On Ubuntu with NVIDIA, the preferred
backend is faster-whisper with CUDA; Ubuntu CPU-only uses faster-whisper `int8`.
The repository does not silently switch an explicitly requested engine.

To enable the optional Apple Silicon backend, build whisper.cpp once and point
the profile at its binary and model:

```bash
git clone https://github.com/ggml-org/whisper.cpp.git "$HOME/.local/src/whisper.cpp"
cmake -S "$HOME/.local/src/whisper.cpp" -B "$HOME/.local/src/whisper.cpp/build"
cmake --build "$HOME/.local/src/whisper.cpp/build" --config Release -j
sh "$HOME/.local/src/whisper.cpp/models/download-ggml-model.sh" large-v3-turbo
export PATH="$HOME/.local/src/whisper.cpp/build/bin:$PATH"
export PODCAST_WHISPER_CPP_MODEL="$HOME/.local/src/whisper.cpp/models/ggml-large-v3-turbo.bin"
```

Ubuntu NVIDIA hosts need a compatible CUDA 12, cuBLAS, and cuDNN 9 runtime for
the faster-whisper CUDA profile. Without it, `doctor` selects the CPU `int8`
profile and reports the selected fallback.

`fetch_episode.py` uses iTunes Lookup only. It does not use RSS fallback or page
scraping. If lookup cannot resolve the episode audio, it prints a warning and
stops.

## Verification

Run the deterministic test suite:

```bash
.venv/bin/python -m unittest discover
```

These tests avoid network and Whisper downloads by injecting fake HTTP and model
boundaries.

## Important Constraints

- Repository code must not call external LLM APIs.
- Generated skills must not mention podcast/show/episode names, source
  citations, or timestamps.
- Generated skill frontmatter uses `name = slug`; the Chinese title belongs in
  the H1.
- Agent judgment steps use `docs/methods/skill-distillation.md` and
  `docs/methods/skill-review-rubric.md`, but the file outputs are defined by
  the project-local skills listed in `WORKFLOW.md`.
