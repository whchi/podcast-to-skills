import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import transcribe
from scripts.transcribe import transcribe_episode


class FakeModel:
    def transcribe(self, audio_path, **kwargs):
        self.audio_path = audio_path
        self.kwargs = kwargs
        return [
            SimpleNamespace(start=0.0, end=1.2, text="  这是第一句。"),
            SimpleNamespace(start=1.2, end=2.0, text="这是第二句。 "),
        ], SimpleNamespace(language="zh")


class FakeConverter:
    def convert(self, text):
        return text.replace("这是", "這是")


class TranscribeEpisodeTest(unittest.TestCase):
    def test_transcribe_episode_writes_timestamp_json_and_traditional_text(self):
        model = FakeModel()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "work" / "processed").mkdir(parents=True)
            (root / "work" / "processed" / "episode.mp3").write_bytes(b"mp3")
            (root / "work" / "metadata.json").write_text(
                json.dumps({"show": "範例節目", "title": "範例單集"}),
                encoding="utf-8",
            )

            result = transcribe_episode(
                root=root,
                model_factory=lambda: model,
                converter_factory=lambda: FakeConverter(),
            )

            self.assertEqual(result, root / "result" / "transcript.txt")
            self.assertEqual(
                model.kwargs,
                {
                    "language": "zh",
                    "vad_filter": True,
                    "initial_prompt": "以下是台灣 Podcast《範例節目》單集「範例單集」的繁體中文逐字稿。",
                    "batch_size": transcribe.BATCH_SIZE,
                },
            )
            self.assertEqual(
                json.loads((root / "work" / "transcript.json").read_text(encoding="utf-8")),
                {
                    "language": "zh",
                    "segments": [
                        {"start": 0.0, "end": 1.2, "text": "这是第一句。"},
                        {"start": 1.2, "end": 2.0, "text": "这是第二句。"},
                    ],
                },
            )
            self.assertEqual(
                (root / "result" / "transcript.txt").read_text(encoding="utf-8"),
                "這是第一句。\n這是第二句。\n",
            )

    def test_no_argument_cli_starts_detached_job(self):
        with mock.patch(
            "scripts.transcribe.start_background",
            return_value={"state": "queued", "pid": 42},
        ) as start:
            result = transcribe.main([])

        self.assertEqual(result, 0)
        start.assert_called_once()


class FakeBatchedPipeline:
    def __init__(self, model):
        self.model = model


class DefaultModelFactoryTest(unittest.TestCase):
    def test_builds_turbo_batched_pipeline_with_int8_and_all_cpu_threads(self):
        created = {}

        class FakeWhisperModel:
            def __init__(self, model_size_or_path, **kwargs):
                created["model_name"] = model_size_or_path
                created["kwargs"] = kwargs

        with (
            mock.patch("faster_whisper.WhisperModel", FakeWhisperModel),
            mock.patch("faster_whisper.BatchedInferencePipeline", FakeBatchedPipeline),
        ):
            pipeline = transcribe._default_model_factory()

        self.assertIsInstance(pipeline, FakeBatchedPipeline)
        self.assertIsInstance(pipeline.model, FakeWhisperModel)
        self.assertEqual(created["model_name"], transcribe.WHISPER_MODEL)
        self.assertEqual(
            created["kwargs"],
            {
                "device": "auto",
                "compute_type": transcribe.COMPUTE_TYPE,
                "cpu_threads": os.cpu_count() or 4,
            },
        )

    def test_uses_turbo_alias_without_large_v3_fallback(self):
        calls = []

        class FakeWhisperModel:
            def __init__(self, model_size_or_path, **kwargs):
                calls.append(model_size_or_path)

        with (
            mock.patch("faster_whisper.WhisperModel", FakeWhisperModel),
            mock.patch("faster_whisper.BatchedInferencePipeline", FakeBatchedPipeline),
        ):
            pipeline = transcribe._default_model_factory()

        self.assertEqual(calls, ["turbo"])
        self.assertIsInstance(pipeline, FakeBatchedPipeline)
        self.assertIsInstance(pipeline.model, FakeWhisperModel)

    def test_does_not_retry_fallback_on_non_value_error(self):
        calls = []

        class FakeWhisperModel:
            def __init__(self, model_size_or_path, **kwargs):
                calls.append(model_size_or_path)
                raise OSError("network unavailable")

        with mock.patch("faster_whisper.WhisperModel", FakeWhisperModel):
            with self.assertRaises(OSError):
                transcribe._default_model_factory()

        self.assertEqual(calls, [transcribe.WHISPER_MODEL])


if __name__ == "__main__":
    unittest.main()
