import json
import tempfile
import unittest
from pathlib import Path

from scripts.transcription.chunks import (
    chunk_manifest,
    merge_segments,
    write_json_atomic,
)


class TranscriptionChunksTest(unittest.TestCase):
    def test_merge_segments_assigns_overlap_to_one_core_window(self):
        merged = merge_segments(
            [
                {
                    "index": 0,
                    "core_start": 0.0,
                    "core_end": 10.0,
                    "segments": [
                        {"start": 0.0, "end": 5.0, "text": "前段"},
                        {"start": 9.0, "end": 12.0, "text": "重疊"},
                    ],
                },
                {
                    "index": 1,
                    "core_start": 10.0,
                    "core_end": 20.0,
                    "segments": [
                        {"start": 9.0, "end": 12.0, "text": "重疊"},
                        {"start": 12.0, "end": 15.0, "text": "後段"},
                    ],
                },
            ]
        )

        self.assertEqual(
            merged,
            [
                {"start": 0.0, "end": 5.0, "text": "前段"},
                {"start": 9.0, "end": 12.0, "text": "重疊"},
                {"start": 12.0, "end": 15.0, "text": "後段"},
            ],
        )

    def test_atomic_json_write_and_manifest_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            manifest = chunk_manifest(
                source_hash="abc123",
                duration_seconds=25.0,
                chunk_seconds=10.0,
                overlap_seconds=1.0,
                config_fingerprint="cfg",
            )

            write_json_atomic(path, manifest)

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), manifest)
            self.assertEqual(len(manifest["chunks"]), 3)
            self.assertEqual(manifest["chunks"][1]["core_start"], 10.0)
            self.assertEqual(manifest["chunks"][1]["audio_start"], 9.0)


if __name__ == "__main__":
    unittest.main()
