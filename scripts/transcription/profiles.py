from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


GIB = 1024**3


class ProfileError(RuntimeError):
    """The requested transcription profile cannot run on this host."""


@dataclass(frozen=True)
class CapabilityProbe:
    system: str
    machine: str
    cpu_cores: int
    available_memory_bytes: int
    whisper_cpp_available: bool = False
    whisper_cpp_model_path: str | None = None
    whisper_cpp_quantized_model_path: str | None = None
    cuda_device_count: int = 0
    cuda_vram_bytes: int = 0
    cuda_compute_types: frozenset[str] = field(default_factory=frozenset)
    cpu_compute_types: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class TranscriptionProfile:
    engine: str
    model: str
    device: str
    compute_type: str
    batch_size: int
    cpu_threads: int
    use_gpu: bool
    model_path: str | None = None
    quantized: bool = False
    warning: str | None = None

    @property
    def name(self) -> str:
        engine = self.engine.replace("-", "")
        return f"{engine}-{self.device}-{self.compute_type}-b{self.batch_size}"

    def as_dict(self) -> dict[str, object]:
        return {
            "engine": self.engine,
            "model": self.model,
            "device": self.device,
            "compute_type": self.compute_type,
            "batch_size": self.batch_size,
            "cpu_threads": self.cpu_threads,
            "use_gpu": self.use_gpu,
            "model_path": self.model_path,
            "quantized": self.quantized,
            "warning": self.warning,
        }


def probe_capabilities(*, root: Path | None = None) -> CapabilityProbe:
    system = platform.system()
    machine = platform.machine().lower()
    cpu_cores = _effective_cpu_count()
    memory = _available_memory_bytes()
    whisper_cli = shutil.which("whisper-cli")
    model_path, quantized_model_path = _find_whisper_cpp_models(root=root)

    cuda_count = 0
    cuda_types: frozenset[str] = frozenset()
    cpu_types: frozenset[str] = frozenset()
    try:
        import ctranslate2

        cpu_types = frozenset(ctranslate2.get_supported_compute_types("cpu"))
        cuda_count = int(ctranslate2.get_cuda_device_count())
        if cuda_count:
            cuda_types = frozenset(ctranslate2.get_supported_compute_types("cuda"))
    except (AttributeError, ImportError, OSError, RuntimeError, ValueError):
        pass

    return CapabilityProbe(
        system=system,
        machine=machine,
        cpu_cores=cpu_cores,
        available_memory_bytes=memory,
        whisper_cpp_available=bool(whisper_cli and (model_path or quantized_model_path)),
        whisper_cpp_model_path=str(model_path) if model_path else None,
        whisper_cpp_quantized_model_path=(
            str(quantized_model_path) if quantized_model_path else None
        ),
        cuda_device_count=cuda_count,
        cuda_vram_bytes=_nvidia_vram_bytes() if cuda_count else 0,
        cuda_compute_types=cuda_types,
        cpu_compute_types=cpu_types,
    )


def select_profile(
    probe: CapabilityProbe,
    *,
    requested_engine: str = "auto",
    memory_profile: bool = False,
) -> TranscriptionProfile:
    if requested_engine not in {"auto", "faster-whisper", "whisper-cpp"}:
        raise ProfileError(f"不支援的 STT engine: {requested_engine}")

    is_apple_silicon = probe.system == "Darwin" and probe.machine in {
        "arm64",
        "aarch64",
    }
    if (
        requested_engine == "auto"
        and is_apple_silicon
        and probe.whisper_cpp_available
        and (probe.whisper_cpp_model_path or memory_profile)
    ):
        return _whisper_cpp_profile(probe, memory_profile=memory_profile)
    if requested_engine == "whisper-cpp":
        if not probe.whisper_cpp_available or not probe.whisper_cpp_model_path:
            raise ProfileError("找不到 whisper-cli 或 whisper.cpp 模型")
        return _whisper_cpp_profile(probe, memory_profile=memory_profile)

    warning = None
    if requested_engine == "auto" and is_apple_silicon:
        warning = "找不到 whisper.cpp，改用 faster-whisper CPU；如需 Metal，請設定 whisper-cli 與模型"
    if probe.cuda_device_count:
        return _cuda_profile(probe, warning=warning)
    return _cpu_profile(probe, warning=warning)


def _whisper_cpp_profile(
    probe: CapabilityProbe, *, memory_profile: bool
) -> TranscriptionProfile:
    model = "large-v3-turbo-q5_0" if memory_profile else "large-v3-turbo"
    model_path = (
        probe.whisper_cpp_quantized_model_path
        if memory_profile
        else probe.whisper_cpp_model_path
    )
    if not model_path:
        raise ProfileError(f"找不到 whisper.cpp {model} 模型")
    return TranscriptionProfile(
        engine="whisper-cpp",
        model=model,
        device="metal" if probe.system == "Darwin" else "auto",
        compute_type="q5_0" if memory_profile else "float16",
        batch_size=1,
        cpu_threads=max(1, probe.cpu_cores),
        use_gpu=True,
        model_path=model_path,
        quantized=memory_profile,
    )


def _cuda_profile(probe: CapabilityProbe, *, warning: str | None) -> TranscriptionProfile:
    supported = probe.cuda_compute_types
    if "float16" in supported:
        compute_type = "float16"
    elif "int8_float16" in supported:
        compute_type = "int8_float16"
    elif "float32" in supported:
        compute_type = "float32"
    else:
        raise ProfileError(f"CUDA 不支援可用的 compute type: {sorted(supported)}")

    if probe.cuda_vram_bytes >= 8 * GIB:
        batch_size = 8
    elif probe.cuda_vram_bytes >= 6 * GIB:
        batch_size = 4
    else:
        batch_size = 1
    return TranscriptionProfile(
        engine="faster-whisper",
        model="turbo",
        device="cuda",
        compute_type=compute_type,
        batch_size=batch_size,
        cpu_threads=max(1, probe.cpu_cores),
        use_gpu=True,
        warning=warning,
    )


def _cpu_profile(probe: CapabilityProbe, *, warning: str | None) -> TranscriptionProfile:
    supported = probe.cpu_compute_types
    if "int8" in supported:
        compute_type = "int8"
    elif "int8_float32" in supported:
        compute_type = "int8_float32"
    elif "float32" in supported or not supported:
        compute_type = "float32"
    else:
        raise ProfileError(f"CPU 不支援可用的 compute type: {sorted(supported)}")

    if probe.available_memory_bytes >= 16 * GIB:
        batch_size = 8
    elif probe.available_memory_bytes >= 8 * GIB:
        batch_size = 4
    else:
        batch_size = 1
    return TranscriptionProfile(
        engine="faster-whisper",
        model="turbo",
        device="cpu",
        compute_type=compute_type,
        batch_size=batch_size,
        cpu_threads=max(1, probe.cpu_cores),
        use_gpu=False,
        warning=warning,
    )


def _effective_cpu_count() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def _available_memory_bytes() -> int:
    if Path("/proc/meminfo").exists():
        try:
            for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError):
            pass
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
        return int(page_size * page_count)
    except (AttributeError, OSError, ValueError):
        return 0


def _nvidia_vram_bytes() -> int:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        first = result.stdout.strip().splitlines()[0]
        return int(float(first) * 1024**2)
    except (FileNotFoundError, IndexError, OSError, ValueError, subprocess.SubprocessError):
        return 0


def _find_whisper_cpp_models(*, root: Path | None) -> tuple[Path | None, Path | None]:
    configured = os.environ.get("PODCAST_WHISPER_CPP_MODEL")
    configured_path = Path(configured) if configured else None
    full_candidates = [configured_path] if configured_path and "q5" not in configured_path.name else []
    quantized_candidates = [configured_path] if configured_path and "q5" in configured_path.name else []
    if root:
        full_candidates.extend(
            [
                root / "models" / "ggml-large-v3-turbo.bin",
            ]
        )
        quantized_candidates.append(root / "models" / "ggml-large-v3-turbo-q5_0.bin")
    full_candidates.append(
        Path.home() / ".cache" / "podcast-to-skills" / "models" / "ggml-large-v3-turbo.bin"
    )
    quantized_candidates.append(
        Path.home()
        / ".cache"
        / "podcast-to-skills"
        / "models"
        / "ggml-large-v3-turbo-q5_0.bin"
    )
    return (
        next((path for path in full_candidates if path and path.is_file()), None),
        next((path for path in quantized_candidates if path and path.is_file()), None),
    )
