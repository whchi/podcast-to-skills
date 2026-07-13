from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.transcription.job import (  # noqa: E402
    JobError,
    current_status,
    run_transcription_job,
    start_background,
)
from scripts.transcription.profiles import (  # noqa: E402
    TranscriptionProfile,
    probe_capabilities,
    select_profile,
)
from scripts.transcription.chunks import write_json_atomic  # noqa: E402


WHISPER_MODEL = "turbo"
COMPUTE_TYPE = "int8"
BATCH_SIZE = 8


class TranscriptionError(RuntimeError):
    """User-facing transcription failure."""


def transcribe_episode(*, root: Path, model_factory=None, converter_factory=None) -> Path:
    """Legacy synchronous API retained for injected-model unit tests.

    The CLI uses the resumable job runner. Callers that need a synchronous API
    should migrate to ``run_transcription_job`` so long audio is checkpointed.
    """
    root = Path(root)
    audio_path = root / "work" / "processed" / "episode.mp3"
    metadata_path = root / "work" / "metadata.json"
    transcript_json_path = root / "work" / "transcript.json"
    transcript_txt_path = root / "result" / "transcript.txt"

    if not audio_path.exists():
        raise TranscriptionError("轉寫失敗:找不到 work/processed/episode.mp3")
    if not metadata_path.exists():
        raise TranscriptionError("轉寫失敗:找不到 work/metadata.json")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    model_factory = model_factory or (lambda: _default_model_factory())
    converter_factory = converter_factory or _default_converter_factory

    model = model_factory()
    initial_prompt = f"以下是台灣 Podcast《{metadata.get('show', '')}》單集「{metadata.get('title', '')}」的繁體中文逐字稿。"
    segments_iter, info = model.transcribe(
        str(audio_path),
        language="zh",
        vad_filter=True,
        initial_prompt=initial_prompt,
        batch_size=BATCH_SIZE,
    )

    segments = [
        {
            "start": segment.start,
            "end": segment.end,
            "text": segment.text.strip(),
        }
        for segment in segments_iter
    ]
    write_json_atomic(
        transcript_json_path,
        {
            "language": getattr(info, "language", "zh"),
            "segments": segments,
        },
    )

    converter = converter_factory()
    plain_text = "\n".join(segment["text"] for segment in segments if segment["text"])
    converted = converter.convert(plain_text)
    transcript_txt_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_txt_path.write_text(converted.rstrip() + "\n", encoding="utf-8")
    return transcript_txt_path


def _default_model_factory(profile: TranscriptionProfile | None = None):
    import faster_whisper

    profile = profile or _legacy_profile()
    model_kwargs = {
        "device": profile.device,
        "compute_type": profile.compute_type,
    }
    if profile.device != "cuda":
        model_kwargs["cpu_threads"] = profile.cpu_threads
    model = faster_whisper.WhisperModel(profile.model, **model_kwargs)
    return faster_whisper.BatchedInferencePipeline(model=model)


def _legacy_profile() -> TranscriptionProfile:
    return TranscriptionProfile(
        engine="faster-whisper",
        model=WHISPER_MODEL,
        device="auto",
        compute_type=COMPUTE_TYPE,
        batch_size=BATCH_SIZE,
        cpu_threads=os.cpu_count() or 4,
        use_gpu=False,
    )


def _default_converter_factory():
    from opencc import OpenCC

    return OpenCC("s2twp")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resumable podcast transcription")
    subparsers = parser.add_subparsers(dest="command")
    for command in ("start", "resume", "run", "worker"):
        subparser = subparsers.add_parser(command)
        _add_runtime_options(subparser)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--root", type=Path, default=Path.cwd())
    status_parser.add_argument("--json", action="store_true", dest="as_json")
    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--root", type=Path, default=Path.cwd())
    doctor_parser.add_argument(
        "--engine",
        choices=("auto", "faster-whisper", "whisper-cpp"),
        default="auto",
    )
    doctor_parser.add_argument("--profile", choices=("quality", "memory"), default="quality")
    return parser


def _add_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--foreground", action="store_true")
    parser.add_argument(
        "--engine",
        choices=("auto", "faster-whisper", "whisper-cpp"),
        default="auto",
    )
    parser.add_argument("--profile", choices=("quality", "memory"), default="quality")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command is None:
        args.root = Path.cwd()
        args.engine = "auto"
        args.profile = "quality"
    command = args.command or "start"
    try:
        if command == "status":
            return _status_command(args.root, as_json=args.as_json)
        if command == "doctor":
            return _doctor_command(
                args.root,
                requested_engine=args.engine,
                memory_profile=args.profile == "memory",
            )
        if command == "run" or command == "worker":
            path = run_transcription_job(
                root=args.root,
                requested_engine=args.engine,
                memory_profile=args.profile == "memory",
            )
            if command == "run":
                print(f"Transcript written: {path}")
            return 0
        result = start_background(
            root=args.root,
            requested_engine=args.engine,
            memory_profile=args.profile == "memory",
        )
        state = result.get("state", "queued")
        pid = result.get("pid")
        print(f"Transcription {state}: pid={pid or 'starting'}")
        print(f"Status: {args.root / 'work' / 'transcription' / 'status.json'}")
        return 0
    except (JobError, TranscriptionError, OSError, ValueError) as exc:
        print(f"轉寫失敗: {exc}。音檔保留於 work/processed/", file=sys.stderr)
        return 1


def _status_command(root: Path, *, as_json: bool) -> int:
    status = current_status(root)
    if status is None:
        print("No transcription job")
        return 1
    if as_json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        print(
            f"state={status.get('state')} "
            f"progress={status.get('progress_percent', 0):.2f}% "
            f"chunks={status.get('completed_chunks', 0)}/{status.get('total_chunks') or '?'}"
        )
        if status.get("warning"):
            print(f"warning={status['warning']}")
        if status.get("heartbeat_stale"):
            print("warning=worker heartbeat stale;確認 worker.log，勿重複啟動")
        if status.get("error"):
            print(f"error={status['error']}")
    return 0


def _doctor_command(root: Path, *, requested_engine: str, memory_profile: bool) -> int:
    probe = probe_capabilities(root=root)
    profile = select_profile(
        probe,
        requested_engine=requested_engine,
        memory_profile=memory_profile,
    )
    print(
        json.dumps(
            {"capabilities": probe.__dict__, "profile": profile.as_dict()},
            ensure_ascii=False,
            indent=2,
            default=list,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
