from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
DEFAULT_CHUNK_SECONDS = 600.0
DEFAULT_OVERLAP_SECONDS = 10.0


class ChunkError(RuntimeError):
    """Audio preparation or checkpoint validation failed."""


def write_json_atomic(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def sha256_file(path: Path, *, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def chunk_manifest(
    *,
    source_hash: str,
    duration_seconds: float,
    chunk_seconds: float = DEFAULT_CHUNK_SECONDS,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
    config_fingerprint: str,
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ChunkError("音檔 duration 必須大於 0")
    if chunk_seconds <= 0 or overlap_seconds < 0 or overlap_seconds >= chunk_seconds:
        raise ChunkError("chunk/overlap 時間設定無效")

    chunks = []
    index = 0
    core_start = 0.0
    while core_start < duration_seconds:
        core_end = min(duration_seconds, core_start + chunk_seconds)
        audio_start = max(0.0, core_start - overlap_seconds)
        audio_end = min(duration_seconds, core_end + overlap_seconds)
        chunks.append(
            {
                "index": index,
                "path": f"audio/chunk-{index:04d}.wav",
                "audio_start": audio_start,
                "audio_end": audio_end,
                "core_start": core_start,
                "core_end": core_end,
                "ready": False,
                "checkpoint": f"chunks/chunk-{index:04d}.json",
            }
        )
        index += 1
        core_start = core_end
    return {
        "schema_version": SCHEMA_VERSION,
        "source_hash": source_hash,
        "duration_seconds": duration_seconds,
        "chunk_seconds": chunk_seconds,
        "overlap_seconds": overlap_seconds,
        "config_fingerprint": config_fingerprint,
        "chunks": chunks,
    }


def prepare_chunks(
    *,
    audio_path: Path,
    transcription_root: Path,
    config_fingerprint: str,
    chunk_seconds: float = DEFAULT_CHUNK_SECONDS,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> dict[str, Any]:
    audio_path = Path(audio_path)
    transcription_root = Path(transcription_root)
    manifest_path = transcription_root / "manifest.json"
    source_hash = sha256_file(audio_path)

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_manifest(manifest, source_hash, config_fingerprint)
    else:
        if any(transcription_root.glob("audio/*")):
            raise ChunkError("發現沒有 manifest 對應的既有音訊 chunks，拒絕覆寫")
        duration = probe_duration(audio_path, ffprobe_bin=ffprobe_bin)
        manifest = chunk_manifest(
            source_hash=source_hash,
            duration_seconds=duration,
            chunk_seconds=chunk_seconds,
            overlap_seconds=overlap_seconds,
            config_fingerprint=config_fingerprint,
        )
        write_json_atomic(manifest_path, manifest)

    audio_dir = transcription_root / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for chunk in manifest["chunks"]:
        output_path = transcription_root / chunk["path"]
        if output_path.exists():
            chunk["ready"] = True
            continue
        _extract_chunk(
            audio_path=audio_path,
            output_path=output_path,
            start=float(chunk["audio_start"]),
            duration=float(chunk["audio_end"]) - float(chunk["audio_start"]),
            ffmpeg_bin=ffmpeg_bin,
        )
        chunk["ready"] = True
        write_json_atomic(manifest_path, manifest)
    write_json_atomic(manifest_path, manifest)
    return manifest


def probe_duration(audio_path: Path, *, ffprobe_bin: str = "ffprobe") -> float:
    try:
        result = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        raise ChunkError(f"找不到或無法執行 ffprobe: {exc}") from exc
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise ChunkError(f"ffprobe 回傳無效 duration: {result.stdout!r}") from exc


def merge_segments(chunks: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks = list(chunks)
    last_index = max((int(chunk["index"]) for chunk in chunks), default=-1)
    merged: list[dict[str, Any]] = []
    for chunk in chunks:
        core_start = float(chunk["core_start"])
        core_end = float(chunk["core_end"])
        is_last = int(chunk["index"]) == last_index
        for raw_segment in chunk.get("segments", []):
            text = str(raw_segment.get("text", "")).strip()
            if not text:
                continue
            start = float(raw_segment["start"])
            end = float(raw_segment["end"])
            midpoint = start if end <= start else (start + end) / 2
            in_core = core_start <= midpoint < core_end or (is_last and midpoint <= core_end)
            if in_core:
                merged.append({"start": start, "end": end, "text": text})
    return sorted(merged, key=lambda segment: (segment["start"], segment["end"]))


def _validate_manifest(
    manifest: dict[str, Any], source_hash: str, config_fingerprint: str
) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ChunkError("manifest schema version 不相容")
    if manifest.get("source_hash") != source_hash:
        raise ChunkError("source MP3 已改變，拒絕沿用舊 transcription work/")
    if manifest.get("config_fingerprint") != config_fingerprint:
        raise ChunkError("transcription profile 已改變，拒絕沿用舊 checkpoints")


def _extract_chunk(
    *, audio_path: Path, output_path: Path, start: float, duration: float, ffmpeg_bin: str
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise ChunkError(f"拒絕覆寫既有 chunk: {output_path}")
    partial_path = output_path.with_name(f".{output_path.name}.part.wav")
    if partial_path.exists():
        raise ChunkError(f"發現未完成的 audio chunk，拒絕覆寫: {partial_path}")
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(audio_path),
        "-t",
        f"{duration:.3f}",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(partial_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        os.replace(partial_path, output_path)
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        raise ChunkError(f"ffmpeg 音訊正規化失敗: {exc}") from exc
