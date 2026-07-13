---
name: podcast-batch-convert
description: Use ONLY when the user explicitly points to a batch input file named exactly podcasts.jsonl (or podcasts.jsonl.example as a format reference) for the podcast-to-skills workflow. Do NOT use when the user pastes multiple episode URLs in chat — in that case process nothing and direct them to create podcasts.jsonl following podcasts.jsonl.example.
---

# Podcast Batch Convert

Run the full podcast-to-skills pipeline once per episode listed in a JSONL file.

## Trigger Rules

- Batch mode activates only when the user explicitly names a JSONL file.
- Accepted filenames, repo root only: `podcasts.jsonl` and `podcasts.jsonl.example`.
  Any other filename (for example `my-episodes.jsonl`): do not process; ask the
  user to rename the file to `podcasts.jsonl`.
- Multiple URLs pasted directly in chat are NOT a batch request. Process none of
  them and reply:

  ```text
  一次只處理一集。若要批次處理,請在 repo root 建立 podcasts.jsonl
  (格式參考 podcasts.jsonl.example,每行一個 {"url": "..."}),
  再告訴我使用該檔案。
  ```

## Input Format

One JSON object per line:

```jsonl
{"url": "https://podcasts.apple.com/tw/podcast/ep678/id1500839292?i=1000776355683"}
```

Each `url` must be an Apple Podcast episode URL containing `i=`.

## Procedure

1. **Validate everything before processing anything.** Read the file; every
   non-empty line must parse as a JSON object with a string `url` containing
   `i=`. If any line is invalid, report all invalid line numbers and stop —
   process zero episodes.
2. Extract `episode_id` (the `i=` value) per line. Duplicate `episode_id`s:
   keep the first, report the duplicates as skipped.
3. Clear and recreate `result/` once, at batch start (this replaces
   `podcast-preflight`'s per-run `result/` clearing; do not clear `result/`
   again between episodes).
4. For each entry, in file order, run WORKFLOW.md Steps 0–5 with these
   overrides:
  - Step 0 (`podcast-preflight`): skip the `result/` clearing; keep every
     other check (existing `work/` still stops the batch).
  - Step 2 (`podcast-transcribe-episode`): start the detached worker, then poll
    `status --json` with short-lived commands until `state` is `completed`.
    Never wait on a foreground one-hour transcription command. On
    `interrupted`, use `resume`; on `failed`, stop and keep `work/`.
  - After Step 3 completes, every episode must keep its inspection artifacts in
    `result/{episode_id}/`: `metadata.json`, `transcript.txt`, and
    `candidates.md`.
  - If `work/candidates.md` is empty, skip Steps 4 and 5 for that episode,
    mark the entry `done`, set `skills_count` to `0`, and include a note that no
    reusable skill was extracted.
  - If `work/candidates.md` is not empty, run Steps 4 and 5, then move the
    generated artifacts into `result/{episode_id}/`: `skills/`, `review.md`,
    and `scores.json`.
   - Delete `work/` before starting the next entry.
5. After each entry (success or failure), update `result/batch-summary.json`:

   ```json
   {
     "source": "podcasts.jsonl",
     "entries": [
       {"line": 1, "url": "...", "episode_id": "1000776355683", "status": "done",
        "title": "...", "result_path": "result/1000776355683/", "skills_count": 2},
       {"line": 2, "url": "...", "episode_id": "...", "status": "done",
        "title": "...", "result_path": "result/...", "skills_count": 0,
        "note": "No extractable skill; empty candidates, Steps 4-5 skipped"},
       {"line": 2, "url": "...", "episode_id": "...", "status": "failed", "error": "..."},
       {"line": 3, "url": "...", "episode_id": "...", "status": "not_reached"}
     ]
   }
   ```

   `status` is one of `done`, `failed`, `not_reached`, `skipped_duplicate`.
6. **Fail-fast:** on the first episode failure, stop the batch. Keep `work/`
   for debugging, mark remaining entries `not_reached`, and report which line
   failed and why. Completed episodes stay in `result/{episode_id}/`.

## Final Report

1. Batch source file and entry count.
2. Per episode: line number, title, `skills_count`, score summary when skills
   exist, and `result/` path.
3. For episodes with `skills_count = 0`, state `本集內容無可萃取的 skill`.
4. Warnings for skills below threshold, grouped per episode.
5. On failure: the failing line, its error, and `work/` debug location.
6. Whether subagent review was used.

## Done

- Every `done` entry has `result/{episode_id}/metadata.json`,
  `result/{episode_id}/transcript.txt`, and
  `result/{episode_id}/candidates.md`.
- Every `done` entry with `skills_count > 0` also has
  `result/{episode_id}/skills/`, `result/{episode_id}/review.md`, and
  `result/{episode_id}/scores.json`.
- `result/batch-summary.json` covers every input line with a final status.
- `work/` exists only if the batch stopped on a failure.
