import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.transcription.engines import FasterWhisperEngine, WhisperCppEngine
from scripts.transcription.profiles import TranscriptionProfile


def cpu_profile():
    return TranscriptionProfile(
        engine="faster-whisper",
        model="turbo",
        device="cpu",
        compute_type="int8",
        batch_size=4,
        cpu_threads=6,
        use_gpu=False,
    )


class FakeWhisperModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return [SimpleNamespace(start=1.0, end=2.0, text=" 一句 ")], SimpleNamespace(language="zh")


class TranscriptionEnginesTest(unittest.TestCase):
    def test_faster_whisper_engine_offsets_chunk_timestamps(self):
        model = FakeWhisperModel()
        engine = FasterWhisperEngine(cpu_profile(), model_factory=lambda profile: model)

        result = engine.transcribe_chunk(
            {
                "index": 2,
                "path": "/tmp/chunk.wav",
                "audio_start": 9.0,
                "core_start": 10.0,
                "core_end": 20.0,
            },
            prompt="prompt",
        )

        self.assertEqual(result.segments, [{"start": 10.0, "end": 11.0, "text": "一句"}])
        self.assertEqual(model.calls[0][1]["batch_size"], 4)
        self.assertEqual(model.calls[0][1]["initial_prompt"], "prompt")

    def test_whisper_cpp_engine_builds_bounded_cli_and_parses_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = root / "chunks" / "chunk-0000.json"
            checkpoint.parent.mkdir()
            (root / "chunks" / "chunk-0000.raw.json").write_text("partial", encoding="utf-8")
            model_path = root / "ggml-large-v3-turbo.bin"
            model_path.write_bytes(b"model")
            profile = TranscriptionProfile(
                engine="whisper-cpp",
                model="large-v3-turbo",
                device="metal",
                compute_type="float16",
                batch_size=1,
                cpu_threads=8,
                use_gpu=True,
                model_path=str(model_path),
            )

            def runner(command, **kwargs):
                output_prefix = Path(command[command.index("--output-file") + 1])
                self.assertTrue(str(output_prefix).endswith("retry-1"))
                Path(f"{output_prefix}.json").write_text(
                    json.dumps(
                        {
                            "transcription": [
                                {
                                    "timestamps": {"from": "00:00:01,000", "to": "00:00:02,500"},
                                    "text": " 測試 ",
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            engine = WhisperCppEngine(profile, binary="whisper-cli", runner=runner)
            result = engine.transcribe_chunk(
                {
                    "index": 0,
                    "path": str(root / "chunk.wav"),
                    "audio_start": 9.0,
                    "core_start": 0.0,
                    "core_end": 10.0,
                    "checkpoint_path": str(checkpoint),
                },
                prompt="prompt",
            )

            self.assertEqual(result.segments, [{"start": 10.0, "end": 11.5, "text": "測試"}])


if __name__ == "__main__":
    unittest.main()
