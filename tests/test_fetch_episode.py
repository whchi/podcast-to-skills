import json
import tempfile
import unittest
from pathlib import Path

from scripts.fetch_episode import PodcastFetchError, fetch_episode, parse_apple_podcast_url


class FakeResponse:
    def __init__(self, *, json_data=None, chunks=None, status_code=200):
        self._json_data = json_data
        self._chunks = chunks or []
        self.status_code = status_code

    def json(self):
        return self._json_data

    def iter_content(self, chunk_size=1024 * 1024):
        for chunk in self._chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected extra GET")
        return self.responses.pop(0)


class FetchEpisodeTest(unittest.TestCase):
    def test_parse_apple_podcast_url_requires_episode_id(self):
        parsed = parse_apple_podcast_url(
            "https://podcasts.apple.com/tw/podcast/show-name/id1500839292?i=1000776355683"
        )

        self.assertEqual(parsed.podcast_id, "1500839292")
        self.assertEqual(parsed.episode_id, "1000776355683")
        self.assertEqual(parsed.country, "tw")

        with self.assertRaisesRegex(PodcastFetchError, "Apple Podcast.*i="):
            parse_apple_podcast_url("https://podcasts.apple.com/tw/podcast/show-name/id1500839292")

    def test_fetch_episode_writes_metadata_and_moves_downloaded_audio(self):
        lookup = {
            "results": [
                {
                    "kind": "podcast",
                    "artistName": "Example Author",
                    "collectionName": "Example Show",
                },
                {
                    "kind": "podcast-episode",
                    "trackId": 1000776355683,
                    "trackName": "Useful Episode",
                    "releaseDate": "2026-07-11T00:00:00Z",
                    "episodeUrl": "https://media.example/episode.mp3",
                },
            ]
        }
        session = FakeSession(
            [
                FakeResponse(json_data=lookup),
                FakeResponse(chunks=[b"audio", b"-bytes"]),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            metadata = fetch_episode(
                "https://podcasts.apple.com/tw/podcast/show-name/id1500839292?i=1000776355683",
                root=Path(tmp),
                session=session,
            )

            self.assertEqual(
                session.calls[0][0],
                "https://itunes.apple.com/lookup?id=1500839292&entity=podcastEpisode&limit=200&country=tw",
            )
            self.assertEqual(session.calls[1][0], "https://media.example/episode.mp3")
            self.assertEqual(
                metadata,
                {
                    "author": "Example Author",
                    "title": "Useful Episode",
                    "published": "2026-07-11T00:00:00Z",
                    "show": "Example Show",
                },
            )
            self.assertEqual(
                json.loads((Path(tmp) / "work" / "metadata.json").read_text()),
                metadata,
            )
            self.assertEqual((Path(tmp) / "work" / "processed" / "episode.mp3").read_bytes(), b"audio-bytes")
            self.assertFalse((Path(tmp) / "work" / "raw" / "episode.mp3").exists())

    def test_download_failure_mid_stream_cleans_up_and_raises_warning(self):
        lookup = {
            "results": [
                {
                    "kind": "podcast",
                    "artistName": "Example Author",
                    "collectionName": "Example Show",
                },
                {
                    "kind": "podcast-episode",
                    "trackId": 1000776355683,
                    "trackName": "Useful Episode",
                    "releaseDate": "2026-07-11T00:00:00Z",
                    "episodeUrl": "https://media.example/episode.mp3",
                },
            ]
        }
        session = FakeSession(
            [
                FakeResponse(json_data=lookup),
                FakeResponse(chunks=[b"partial-bytes", ConnectionError("connection reset")]),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(PodcastFetchError, "Warning:.*下載失敗"):
                fetch_episode(
                    "https://podcasts.apple.com/tw/podcast/show-name/id1500839292?i=1000776355683",
                    root=Path(tmp),
                    session=session,
                )

            self.assertFalse((Path(tmp) / "work" / "raw" / "episode.mp3").exists())
            self.assertFalse((Path(tmp) / "work" / "processed" / "episode.mp3").exists())

    def test_lookup_without_episode_url_stops_with_warning(self):
        lookup = {
            "results": [
                {"kind": "podcast", "artistName": "Author", "collectionName": "Show"},
                {"trackId": 1000776355683, "trackName": "Paid Episode", "releaseDate": "2026-07-11"},
            ]
        }
        session = FakeSession([FakeResponse(json_data=lookup)])

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(PodcastFetchError, "Warning:.*無法取得音檔"):
                fetch_episode(
                    "https://podcasts.apple.com/tw/podcast/show-name/id1500839292?i=1000776355683",
                    root=Path(tmp),
                    session=session,
                )

            self.assertEqual(len(session.calls), 1)


if __name__ == "__main__":
    unittest.main()
