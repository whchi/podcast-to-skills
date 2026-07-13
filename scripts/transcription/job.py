from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .chunks import (
    DEFAULT_CHUNK_SECONDS,
    DEFAULT_OVERLAP_SECONDS,
    ChunkError,
    merge_segments,
    prepare_chunks,
    sha256_file,
    write_json_atomic,
)
from .engines import ChunkTranscript, EngineError, build_engine
from .profiles import ProfileError, TranscriptionProfile, probe_capabilities, select_profile


STATUS_SCHEMA_VERSION = 1
HEARTBEAT_TIMEOUT_SECONDS = 60
_STATUS_LOCK = threading.Lock()


class JobError(RuntimeError):
    """Job lifecycle or finalization failure."""


def status_path(root: Path) -> Path:
    return Path(root) / "work" / "transcription" / "status.json"


def read_status(root: Path) -> dict[str, Any] | None:
    path = status_path(root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def current_status(root: Path) -> dict[str, Any] | None:
    status = read_status(root)
    if not status or status.get("state") != "running":
        return status
    status = dict(status)
    status["heartbeat_stale"] = _heartbeat_is_stale(status.get("heartbeat_at"))
    pid = status.get("pid")
    if isinstance(pid, int) and _pid_alive(pid):
        return status
    status.update(
        {
            "state": "interrupted",
            "error": f"worker PID {pid} 不存在，請執行 resume",
            "heartbeat_at": _now_iso(),
        }
    )
    write_json_atomic(status_path(root), status)
    return status


def start_background(
    *,
    root: Path,
    requested_engine: str = "auto",
    memory_profile: bool = False,
) -> dict[str, Any]:
    root = Path(root)
    existing = current_status(root)
    if existing and existing.get("state") == "completed":
        return existing
    if existing and existing.get("state") in {"queued", "running"}:
        pid = existing.get("pid")
        if isinstance(pid, int) and _pid_alive(pid):
            raise JobError(f"已有 transcription worker 在執行中: PID {pid}")

    transcription_root = root / "work" / "transcription"
    transcription_root.mkdir(parents=True, exist_ok=True)
    queued = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "state": "queued",
        "pid": None,
        "started_at": _now_iso(),
        "heartbeat_at": _now_iso(),
        "completed_chunks": 0,
        "total_chunks": None,
        "processed_until_seconds": 0.0,
        "progress_percent": 0.0,
        "error": None,
    }
    write_json_atomic(transcription_root / "status.json", queued)

    command = [
        sys.executable,
        str(root / "scripts" / "transcribe.py"),
        "worker",
        "--root",
        str(root),
        "--engine",
        requested_engine,
    ]
    if memory_profile:
        command.append("--profile")
        command.append("memory")
    log_path = transcription_root / "worker.log"
    try:
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        queued.update({"state": "failed", "error": str(exc), "heartbeat_at": _now_iso()})
        write_json_atomic(transcription_root / "status.json", queued)
        raise JobError(f"無法啟動 transcription worker: {exc}") from exc
    queued["pid"] = process.pid
    with _STATUS_LOCK:
        latest = read_status(root)
        if latest and latest.get("state") == "queued":
            latest["pid"] = process.pid
            latest["heartbeat_at"] = _now_iso()
            write_json_atomic(transcription_root / "status.json", latest)
    return queued


def run_transcription_job(
    *,
    root: Path,
    requested_engine: str = "auto",
    memory_profile: bool = False,
    profile: TranscriptionProfile | None = None,
    model_factory: Callable[[TranscriptionProfile], Any] | None = None,
    engine_factory: Callable[[TranscriptionProfile], Any] | None = None,
    converter_factory: Callable[[], Any] | None = None,
    prepare_chunks_fn: Callable[..., dict[str, Any]] | None = None,
) -> Path:
    root = Path(root)
    audio_path = root / "work" / "processed" / "episode.mp3"
    metadata_path = root / "work" / "metadata.json"
    transcription_root = root / "work" / "transcription"
    transcription_root.mkdir(parents=True, exist_ok=True)
    try:
        if not audio_path.exists():
            raise JobError("轉寫失敗:找不到 work/processed/episode.mp3")
        if not metadata_path.exists():
            raise JobError("轉寫失敗:找不到 work/metadata.json")
        if profile is None:
            profile = select_profile(
                probe_capabilities(root=root),
                requested_engine=requested_engine,
                memory_profile=memory_profile,
            )
        with _exclusive_lock(transcription_root / "worker.lock"):
            heartbeat_stop = threading.Event()
            heartbeat = threading.Thread(
                target=_heartbeat_loop,
                args=(root, heartbeat_stop),
                name="transcription-heartbeat",
                daemon=True,
            )
            heartbeat.start()
            try:
                return _run_locked(
                    root=root,
                    audio_path=audio_path,
                    metadata_path=metadata_path,
                    transcription_root=transcription_root,
                    profile=profile,
                    model_factory=model_factory,
                    engine_factory=engine_factory,
                    converter_factory=converter_factory,
                    prepare_chunks_fn=prepare_chunks_fn or prepare_chunks,
                )
            finally:
                heartbeat_stop.set()
                heartbeat.join(timeout=1)
    except (JobError, ChunkError, EngineError, ProfileError) as exc:
        _mark_failed(root, error=str(exc))
        raise
    except Exception as exc:
        _mark_failed(root, error=str(exc))
        raise JobError(f"轉寫失敗: {exc}") from exc


def _run_locked(
    *,
    root: Path,
    audio_path: Path,
    metadata_path: Path,
    transcription_root: Path,
    profile: TranscriptionProfile,
    model_factory: Callable[[TranscriptionProfile], Any] | None,
    engine_factory: Callable[[TranscriptionProfile], Any] | None,
    converter_factory: Callable[[], Any] | None,
    prepare_chunks_fn: Callable[..., dict[str, Any]],
) -> Path:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source_hash = sha256_file(audio_path)
    config_fingerprint = _config_fingerprint(profile)
    _write_running_status(
        root,
        source_hash=source_hash,
        profile=profile,
        warning=profile.warning,
    )

    manifest = prepare_chunks_fn(
        audio_path=audio_path,
        transcription_root=transcription_root,
        config_fingerprint=config_fingerprint,
        chunk_seconds=DEFAULT_CHUNK_SECONDS,
        overlap_seconds=DEFAULT_OVERLAP_SECONDS,
    )
    _update_status(
        root,
        total_chunks=len(manifest["chunks"]),
        heartbeat_at=_now_iso(),
    )

    engine = (engine_factory or (lambda selected: build_engine(selected, model_factory=model_factory)))(
        profile
    )
    prompt = _prompt_from_metadata(metadata)
    completed = 0
    language = "zh"
    for manifest_chunk in manifest["chunks"]:
        checkpoint_path, checkpoint = _find_checkpoint(transcription_root, manifest_chunk)
        if checkpoint is not None:
            completed += 1
            language = checkpoint.get("language", language)
            _update_status(
                root,
                completed_chunks=completed,
                processed_until_seconds=float(manifest_chunk["core_end"]),
                progress_percent=completed / len(manifest["chunks"]) * 100,
                heartbeat_at=_now_iso(),
            )
            continue

        runtime_chunk = dict(manifest_chunk)
        runtime_chunk["path"] = str(transcription_root / manifest_chunk["path"])
        runtime_chunk["checkpoint_path"] = str(checkpoint_path)
        try:
            transcript = engine.transcribe_chunk(runtime_chunk, prompt=prompt)
        except Exception as exc:
            if _is_cuda_oom(exc) and profile.batch_size > 1 and profile.engine == "faster-whisper":
                lower_batch = max(1, profile.batch_size // 2)
                profile = replace(profile, batch_size=lower_batch)
                _update_status(
                    root,
                    profile=profile.as_dict(),
                    degraded_reason=f"CUDA OOM，降 batch size 到 {lower_batch}",
                    heartbeat_at=_now_iso(),
                )
                engine = (engine_factory or (lambda selected: build_engine(selected, model_factory=model_factory)))(
                    profile
                )
                transcript = engine.transcribe_chunk(runtime_chunk, prompt=prompt)
            else:
                raise
        if not isinstance(transcript, ChunkTranscript):
            raise JobError("engine adapter 必須回傳 ChunkTranscript")
        write_json_atomic(checkpoint_path, transcript.as_dict())
        completed += 1
        language = transcript.language or language
        _update_status(
            root,
            completed_chunks=completed,
            processed_until_seconds=float(manifest_chunk["core_end"]),
            progress_percent=completed / len(manifest["chunks"]) * 100,
            heartbeat_at=_now_iso(),
        )

    checkpoints = []
    for manifest_chunk in manifest["chunks"]:
        checkpoint_path, checkpoint = _find_checkpoint(transcription_root, manifest_chunk)
        if checkpoint is None:
            raise JobError(f"缺少 chunk checkpoint: {manifest_chunk['index']}")
        checkpoints.append(
            {
                **checkpoint,
                "index": int(manifest_chunk["index"]),
                "core_start": float(manifest_chunk["core_start"]),
                "core_end": float(manifest_chunk["core_end"]),
            }
        )
    segments = merge_segments(checkpoints)
    transcript_json_path = root / "work" / "transcript.json"
    write_json_atomic(
        transcript_json_path,
        {"language": language, "segments": segments},
    )
    converter = converter_factory() if converter_factory else _default_converter()
    plain_text = "\n".join(segment["text"] for segment in segments)
    converted = converter.convert(plain_text).rstrip() + "\n"
    transcript_txt_path = root / "result" / "transcript.txt"
    _write_text_atomic(transcript_txt_path, converted)
    _update_status(
        root,
        state="completed",
        pid=os.getpid(),
        completed_chunks=len(manifest["chunks"]),
        processed_until_seconds=float(manifest["duration_seconds"]),
        progress_percent=100.0,
        heartbeat_at=_now_iso(),
        error=None,
    )
    return transcript_txt_path


def _write_running_status(
    root: Path,
    *,
    source_hash: str,
    profile: TranscriptionProfile,
    warning: str | None,
) -> None:
    existing = read_status(root) or {}
    status = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "job_id": f"{source_hash[:12]}",
        "state": "running",
        "pid": os.getpid(),
        "engine": profile.engine,
        "profile": profile.name,
        "profile_config": profile.as_dict(),
        "model": profile.model,
        "started_at": existing.get("started_at", _now_iso()),
        "heartbeat_at": _now_iso(),
        "source_hash": source_hash,
        "completed_chunks": 0,
        "total_chunks": None,
        "processed_until_seconds": 0.0,
        "progress_percent": 0.0,
        "degraded_reason": None,
        "warning": warning,
        "error": None,
    }
    with _STATUS_LOCK:
        write_json_atomic(status_path(root), status)


def _update_status(root: Path, **changes: Any) -> None:
    with _STATUS_LOCK:
        status = read_status(root) or {
            "schema_version": STATUS_SCHEMA_VERSION,
            "state": "running",
        }
        status.update(changes)
        write_json_atomic(status_path(root), status)


def _mark_failed(root: Path, *, error: str | None = None) -> None:
    with _STATUS_LOCK:
        status = read_status(root)
        if not status:
            status = {
                "schema_version": STATUS_SCHEMA_VERSION,
                "state": "failed",
                "pid": os.getpid(),
                "heartbeat_at": _now_iso(),
                "error": error or "worker failed",
            }
            write_json_atomic(status_path(root), status)
            return
        if status.get("state") == "completed":
            return
        status.update(
            {
                "state": "failed",
                "heartbeat_at": _now_iso(),
                "error": error or status.get("error") or "worker failed",
            }
        )
        write_json_atomic(status_path(root), status)


def _heartbeat_loop(root: Path, stop: threading.Event) -> None:
    while not stop.wait(15):
        status = read_status(root)
        if status and status.get("state") == "running":
            _update_status(root, heartbeat_at=_now_iso())


def _find_checkpoint(
    transcription_root: Path, manifest_chunk: dict[str, Any]
) -> tuple[Path, dict[str, Any] | None]:
    base = transcription_root / manifest_chunk["checkpoint"]
    candidates = [base]
    candidates.extend(
        base.with_name(f"{base.stem}.retry-{index}{base.suffix}") for index in range(1, 100)
    )
    for candidate in candidates:
        if not candidate.exists():
            return candidate, None
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            if (
                payload.get("schema_version") == 1
                and int(payload.get("index")) == int(manifest_chunk["index"])
                and isinstance(payload.get("segments"), list)
            ):
                return candidate, payload
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    raise JobError(f"chunk checkpoint retry 次數過多: {manifest_chunk['index']}")


def _config_fingerprint(profile: TranscriptionProfile) -> str:
    payload = json.dumps(
        {
            "profile": profile.as_dict(),
            "chunk_seconds": DEFAULT_CHUNK_SECONDS,
            "overlap_seconds": DEFAULT_OVERLAP_SECONDS,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _prompt_from_metadata(metadata: dict[str, Any]) -> str:
    return f"以下是台灣 Podcast《{metadata.get('show', '')}》單集「{metadata.get('title', '')}」的繁體中文逐字稿。"


def _default_converter() -> Any:
    from opencc import OpenCC

    return OpenCC("s2twp")


def _write_text_atomic(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    os.replace(temp_path, path)


def _is_cuda_oom(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "out of memory" in message or "cuda out of memory" in message


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextlib.contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise JobError("已有 transcription worker 持有 worker.lock") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _heartbeat_is_stale(value: Any) -> bool:
    if not value:
        return True
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - timestamp).total_seconds() > HEARTBEAT_TIMEOUT_SECONDS
