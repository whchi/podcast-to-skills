from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse


LOOKUP_URL = "https://itunes.apple.com/lookup"
REQUEST_TIMEOUT = (10, 60)
USER_AGENT = "podcast-to-skills/0.1"


class PodcastFetchError(RuntimeError):
    """User-facing fetch failure."""


@dataclass(frozen=True)
class ParsedPodcastUrl:
    podcast_id: str
    episode_id: str
    country: str


def parse_apple_podcast_url(url: str) -> ParsedPodcastUrl:
    parsed = urlparse(url)
    podcast_match = re.search(r"/id(\d+)", parsed.path)
    episode_id = parse_qs(parsed.query).get("i", [None])[0]
    path_parts = [part for part in parsed.path.split("/") if part]
    country = path_parts[0].lower() if path_parts and len(path_parts[0]) == 2 else "us"

    if not podcast_match or not episode_id:
        raise PodcastFetchError("請提供 Apple Podcast「單集」連結(網址需含 i= 參數)")

    return ParsedPodcastUrl(
        podcast_id=podcast_match.group(1),
        episode_id=episode_id,
        country=country,
    )


def fetch_episode(url: str, *, root: Path, session=None) -> dict:
    parsed = parse_apple_podcast_url(url)
    root = Path(root)
    session = session or _default_session()

    raw_dir = root / "work" / "raw"
    processed_dir = root / "work" / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    lookup_url = (
        f"{LOOKUP_URL}?id={parsed.podcast_id}"
        f"&entity=podcastEpisode&limit=200&country={parsed.country}"
    )
    lookup_response = _get(session, lookup_url)
    lookup_response.raise_for_status()
    lookup_data = lookup_response.json()

    show = _find_show(lookup_data)
    episode = _find_episode(lookup_data, parsed.episode_id)
    if not episode:
        raise PodcastFetchError("Warning:找不到這一集,可能已下架、超出 lookup 範圍或連結有誤")

    episode_url = episode.get("episodeUrl")
    if not episode_url:
        raise PodcastFetchError("Warning:此集無法取得音檔,可能是付費限定或平台未提供直鏈")

    raw_audio = raw_dir / "episode.mp3"
    processed_audio = processed_dir / "episode.mp3"
    _download_audio(session, episode_url, raw_audio)
    shutil.move(str(raw_audio), str(processed_audio))

    metadata = {
        "author": show.get("artistName", ""),
        "title": episode.get("trackName", ""),
        "published": episode.get("releaseDate", ""),
        "show": show.get("collectionName", ""),
    }
    metadata_path = root / "work" / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def _default_session():
    import requests

    return requests.Session()


def _get(session, url: str, **kwargs):
    headers = {"User-Agent": USER_AGENT}
    headers.update(kwargs.pop("headers", {}))
    return session.get(url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs)


def _find_show(lookup_data: dict) -> dict:
    for item in lookup_data.get("results", []):
        if item.get("kind") == "podcast":
            return item
    return {}


def _find_episode(lookup_data: dict, episode_id: str) -> dict | None:
    for item in lookup_data.get("results", []):
        if str(item.get("trackId")) == episode_id:
            return item
    return None


def _download_audio(session, episode_url: str, destination: Path) -> None:
    try:
        response = _get(session, episode_url, stream=True)
        response.raise_for_status()

        bytes_written = 0
        with destination.open("wb") as audio_file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                audio_file.write(chunk)
                bytes_written += len(chunk)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise PodcastFetchError(f"Warning:音檔下載失敗({exc}),請稍後重試") from exc

    if bytes_written == 0:
        destination.unlink(missing_ok=True)
        raise PodcastFetchError("Warning:音檔下載失敗(empty file),請稍後重試")


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if len(argv) != 1:
        print("Usage: python scripts/fetch_episode.py <apple_podcast_url>", file=sys.stderr)
        return 2

    try:
        metadata = fetch_episode(argv[0], root=Path.cwd())
    except PodcastFetchError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(
        f"Fetched: {metadata['author']} / {metadata['show']} / "
        f"{metadata['title']} ({metadata['published']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
