---
name: podcast-fetch-episode
description: Use as Step 1 of the podcast-to-skills workflow to resolve one Apple Podcast episode URL into metadata and an MP3 file using the deterministic fetch script.
---

# Podcast Fetch Episode

Resolve the Apple Podcast URL to metadata and audio.

## Inputs

- Apple Podcast episode URL containing `i=`.
- Clean `work/` directories created by `podcast-preflight`.

## Procedure

Run:

```bash
.venv/bin/python scripts/fetch_episode.py "<apple_podcast_url>"
```

Expected outputs:

- `work/processed/episode.mp3`
- `work/metadata.json`

## Rules

- The script parses podcast id from `/id...` and episode id from `i=`.
- It uses iTunes Lookup only:

  ```text
  https://itunes.apple.com/lookup?id={pid}&entity=podcastEpisode&limit=200&country={cc}
  ```

- Do not perform RSS fallback or `og:audio` scraping.
- If lookup cannot find the episode or cannot provide `episodeUrl`, report stderr as a warning and stop.

## Done

- `work/processed/episode.mp3` exists and is non-empty.
- `work/metadata.json` exists with `author`, `title`, `published`, and `show`.
- Metadata is saved for the final report; do not pause for user confirmation.
