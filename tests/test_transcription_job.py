import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.transcription.engines import ChunkTranscript
from scripts.transcription.job import (
    JobError,
    current_status,
    run_transcription_job,
    start_background,
)
from scripts.transcription.profiles import TranscriptionProfile


def cpu_profile() -> TranscriptionProfile:
    return TranscriptionProfile(
        engine="faster-whisper",
        model="turbo",
        device="cpu",
        compute_type="int8",
        batch_size=1,
        cpu_threads=2,
        use_gpu=False,
    )


def fake_manifest():
    return {
        "schema_version": 1,
        "duration_seconds": 20.0,
        "chunks": [
            {
                "index": 0,
                "path": "audio/chunk-0000.wav",
                "audio_start": 0.0,
                "audio_end": 11.0,
                "core_start": 0.0,
                "core_end": 10.0,
                "checkpoint": "chunks/chunk-0000.json",
            },
            {
                "index": 1,
                "path": "audio/chunk-0001.wav",
                "audio_start": 9.0,
                "audio_end": 20.0,
                "core_start": 10.0,
                "core_end": 20.0,
                "checkpoint": "chunks/chunk-0001.json",
            },
        ],
    }


class FakeEngine:
    def __init__(self, calls):
        self.calls = calls

    def transcribe_chunk(self, chunk, *, prompt):
        self.calls.append((chunk["index"], chunk["path"], prompt))
        index = int(chunk["index"])
        start = 1.0 if index == 0 else 11.0
        return ChunkTranscript(
            index=index,
            core_start=float(chunk["core_start"]),
            core_end=float(chunk["core_end"]),
            segments=[{"start": start, "end": start + 1.0, "text": f"第{index}段"}],
        )


class FakeConverter:
    def convert(self, text):
        return text


class TranscriptionJobTest(unittest.TestCase):
    def make_root(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "work" / "processed").mkdir(parents=True)
        (root / "work" / "processed" / "episode.mp3").write_bytes(b"audio")
        (root / "work" / "metadata.json").write_text(
            json.dumps({"show": "節目", "title": "單集"}), encoding="utf-8"
        )
        return tmp, root

    def test_run_job_commits_each_chunk_and_final_outputs(self):
        tmp, root = self.make_root()
        self.addCleanup(tmp.cleanup)
        calls = []

        result = run_transcription_job(
            root=root,
            profile=cpu_profile(),
            prepare_chunks_fn=lambda **kwargs: fake_manifest(),
            engine_factory=lambda profile: FakeEngine(calls),
            converter_factory=lambda: FakeConverter(),
        )

        self.assertEqual(result, root / "result" / "transcript.txt")
        self.assertEqual([call[0] for call in calls], [0, 1])
        self.assertEqual(
            json.loads((root / "work" / "transcript.json").read_text()),
            {
                "language": "zh",
                "segments": [
                    {"start": 1.0, "end": 2.0, "text": "第0段"},
                    {"start": 11.0, "end": 12.0, "text": "第1段"},
                ],
            },
        )
        self.assertEqual(current_status(root)["state"], "completed")

    def test_resume_skips_valid_chunk_checkpoints(self):
        tmp, root = self.make_root()
        self.addCleanup(tmp.cleanup)
        first_calls = []
        kwargs = {
            "root": root,
            "profile": cpu_profile(),
            "prepare_chunks_fn": lambda **ignored: fake_manifest(),
            "engine_factory": lambda profile: FakeEngine(first_calls),
            "converter_factory": lambda: FakeConverter(),
        }
        run_transcription_job(**kwargs)

        second_calls = []
        run_transcription_job(
            **{
                **kwargs,
                "engine_factory": lambda profile: FakeEngine(second_calls),
            }
        )

        self.assertEqual([call[0] for call in first_calls], [0, 1])
        self.assertEqual(second_calls, [])

    def test_start_background_returns_without_waiting_for_worker(self):
        tmp, root = self.make_root()
        self.addCleanup(tmp.cleanup)
        process = mock.Mock(pid=1234)

        with mock.patch("scripts.transcription.job.subprocess.Popen", return_value=process) as popen:
            result = start_background(root=root)

        self.assertEqual(result["pid"], 1234)
        self.assertEqual(result["state"], "queued")
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(current_status(root)["state"], "queued")

    def test_preflight_failure_marks_job_failed_instead_of_staying_queued(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(JobError):
                run_transcription_job(root=root, profile=cpu_profile())

            self.assertEqual(current_status(root)["state"], "failed")
            self.assertIn("episode.mp3", current_status(root)["error"])


if __name__ == "__main__":
    unittest.main()
