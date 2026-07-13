---
name: podcast-transcribe-episode
description: Use as Step 2 of the podcast-to-skills workflow to transcribe the fetched episode MP3 into timestamp JSON and Traditional Chinese transcript text.
---

# Podcast Transcribe Episode

Convert the fetched MP3 into transcript artifacts.

## Inputs

- `work/processed/episode.mp3`
- `work/metadata.json`

## Procedure

Start the resumable worker:

```bash
.venv/bin/python scripts/transcribe.py
```

The default command returns quickly and runs transcription in a detached worker.
Poll it with short-lived commands until `state=completed`:

```bash
.venv/bin/python scripts/transcribe.py status --json
```

Do not use `run` for a long production episode; `run` is the foreground test
command. If the status is `interrupted`, run `resume` and continue polling.

Expected outputs:

- `work/transcript.json`
- `result/transcript.txt`
- `work/transcription/status.json`
- `work/transcription/manifest.json`
- `work/transcription/chunks/`

The script uses:

- `language="zh"`
- `vad_filter=True`
- `initial_prompt` built from `work/metadata.json`
- OpenCC `s2twp`
- capability-based engine selection: whisper.cpp on available Apple Silicon,
  faster-whisper CUDA on Ubuntu NVIDIA, and faster-whisper CPU `int8` otherwise
- 10-minute audio windows with overlap and atomic checkpoints

## Failure

If transcription fails, stop, report the error, and keep `work/`.
The worker log is at `work/transcription/worker.log`. Do not delete or overwrite
an existing transcription manifest when resuming.

## Done

- `work/transcript.json` exists and includes segment timestamps.
- `result/transcript.txt` exists and is Traditional Chinese text.
- `work/transcription/status.json` has `state: "completed"`.
