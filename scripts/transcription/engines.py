from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .profiles import TranscriptionProfile


class EngineError(RuntimeError):
    """An STT backend could not transcribe a chunk."""


@dataclass(frozen=True)
class ChunkTranscript:
    index: int
    core_start: float
    core_end: float
    segments: list[dict[str, Any]]
    language: str = "zh"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "index": self.index,
            "core_start": self.core_start,
            "core_end": self.core_end,
            "language": self.language,
            "segments": self.segments,
        }


class FasterWhisperEngine:
    def __init__(
        self,
        profile: TranscriptionProfile,
        *,
        model_factory: Callable[[TranscriptionProfile], Any] | None = None,
    ) -> None:
        self.profile = profile
        self.model = (model_factory or _build_faster_whisper_model)(profile)

    def transcribe_chunk(self, chunk: dict[str, Any], *, prompt: str) -> ChunkTranscript:
        try:
            segments_iter, info = self.model.transcribe(
                str(chunk["path"]),
                language="zh",
                vad_filter=True,
                initial_prompt=prompt,
                batch_size=self.profile.batch_size,
            )
            segments = [
                {
                    "start": float(chunk["audio_start"]) + float(segment.start),
                    "end": float(chunk["audio_start"]) + float(segment.end),
                    "text": str(segment.text).strip(),
                }
                for segment in segments_iter
                if str(segment.text).strip()
            ]
        except Exception as exc:
            raise EngineError(f"faster-whisper chunk {chunk['index']} 失敗: {exc}") from exc
        return ChunkTranscript(
            index=int(chunk["index"]),
            core_start=float(chunk["core_start"]),
            core_end=float(chunk["core_end"]),
            segments=segments,
            language=getattr(info, "language", "zh"),
        )


class WhisperCppEngine:
    def __init__(
        self,
        profile: TranscriptionProfile,
        *,
        binary: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        if not profile.model_path:
            raise EngineError("whisper.cpp profile 缺少 model path")
        self.profile = profile
        self.binary = binary or shutil.which("whisper-cli")
        if not self.binary:
            raise EngineError("找不到 whisper-cli")
        self.runner = runner or subprocess.run

    def build_command(
        self, chunk: dict[str, Any], *, prompt: str, output_prefix: Path
    ) -> list[str]:
        return [
            self.binary,
            "--model",
            self.profile.model_path or "",
            "--file",
            str(chunk["path"]),
            "--language",
            "zh",
            "--prompt",
            prompt,
            "--output-json",
            "--output-file",
            str(output_prefix),
            "--no-prints",
            "--threads",
            str(self.profile.cpu_threads),
        ]

    def transcribe_chunk(self, chunk: dict[str, Any], *, prompt: str) -> ChunkTranscript:
        output_prefix = Path(chunk["checkpoint_path"]).with_suffix(".raw")
        output_path = Path(f"{output_prefix}.json")
        if output_path.exists():
            try:
                payload = json.loads(output_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                output_prefix = _next_raw_prefix(output_prefix)
            else:
                return ChunkTranscript(
                    index=int(chunk["index"]),
                    core_start=float(chunk["core_start"]),
                    core_end=float(chunk["core_end"]),
                    segments=_parse_whisper_cpp_segments(payload, float(chunk["audio_start"])),
                )
        output_path = Path(f"{output_prefix}.json")
        command = self.build_command(chunk, prompt=prompt, output_prefix=output_prefix)
        try:
            self.runner(command, check=True, capture_output=True, text=True)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise EngineError(f"whisper.cpp chunk {chunk['index']} 失敗: {exc}") from exc
        return ChunkTranscript(
            index=int(chunk["index"]),
            core_start=float(chunk["core_start"]),
            core_end=float(chunk["core_end"]),
            segments=_parse_whisper_cpp_segments(payload, float(chunk["audio_start"])),
        )


def build_engine(
    profile: TranscriptionProfile,
    *,
    model_factory: Callable[[TranscriptionProfile], Any] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> FasterWhisperEngine | WhisperCppEngine:
    if profile.engine == "faster-whisper":
        return FasterWhisperEngine(profile, model_factory=model_factory)
    if profile.engine == "whisper-cpp":
        return WhisperCppEngine(profile, runner=runner)
    raise EngineError(f"不支援的 engine: {profile.engine}")


def _build_faster_whisper_model(profile: TranscriptionProfile) -> Any:
    import faster_whisper

    kwargs = {
        "device": profile.device,
        "compute_type": profile.compute_type,
    }
    if profile.device == "cpu":
        kwargs["cpu_threads"] = profile.cpu_threads
    model = faster_whisper.WhisperModel(profile.model, **kwargs)
    return faster_whisper.BatchedInferencePipeline(model=model)


def _parse_whisper_cpp_segments(
    payload: dict[str, Any], audio_start: float
) -> list[dict[str, Any]]:
    raw_segments = payload.get("transcription") or payload.get("segments") or []
    parsed = []
    for raw in raw_segments:
        timestamps = raw.get("timestamps", {})
        start = _timestamp_seconds(timestamps.get("from", raw.get("start", 0)))
        end = _timestamp_seconds(timestamps.get("to", raw.get("end", start)))
        text = str(raw.get("text", "")).strip()
        if text:
            parsed.append(
                {
                    "start": audio_start + start,
                    "end": audio_start + end,
                    "text": text,
                }
            )
    return parsed


def _timestamp_seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    parts = text.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        return float(text)
    except ValueError as exc:
        raise EngineError(f"whisper.cpp timestamp 無效: {value!r}") from exc


def _next_raw_prefix(base: Path) -> Path:
    for index in range(1, 100):
        candidate = base.with_name(f"{base.name}.retry-{index}")
        if not Path(f"{candidate}.json").exists():
            return candidate
    raise EngineError(f"whisper.cpp raw output retry 次數過多: {base}")
