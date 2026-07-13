import unittest

from scripts.transcription.profiles import CapabilityProbe, ProfileError, select_profile


class TranscriptionProfileTest(unittest.TestCase):
    def test_selects_whisper_cpp_for_available_apple_silicon(self):
        profile = select_profile(
            CapabilityProbe(
                system="Darwin",
                machine="arm64",
                cpu_cores=8,
                available_memory_bytes=16 * 1024**3,
                whisper_cpp_available=True,
                whisper_cpp_model_path="/models/full.bin",
            )
        )

        self.assertEqual(profile.engine, "whisper-cpp")
        self.assertEqual(profile.model, "large-v3-turbo")
        self.assertTrue(profile.use_gpu)

    def test_memory_profile_uses_quantized_whisper_cpp_model_path(self):
        profile = select_profile(
            CapabilityProbe(
                system="Darwin",
                machine="arm64",
                cpu_cores=8,
                available_memory_bytes=8 * 1024**3,
                whisper_cpp_available=True,
                whisper_cpp_model_path="/models/full.bin",
                whisper_cpp_quantized_model_path="/models/q5.bin",
            ),
            requested_engine="whisper-cpp",
            memory_profile=True,
        )

        self.assertEqual(profile.model, "large-v3-turbo-q5_0")
        self.assertEqual(profile.model_path, "/models/q5.bin")
        self.assertTrue(profile.quantized)

    def test_selects_cuda_profile_from_supported_types_and_vram(self):
        profile = select_profile(
            CapabilityProbe(
                system="Linux",
                machine="x86_64",
                cpu_cores=16,
                available_memory_bytes=32 * 1024**3,
                cuda_device_count=1,
                cuda_vram_bytes=10 * 1024**3,
                cuda_compute_types={"float16", "int8_float16"},
            )
        )

        self.assertEqual(profile.engine, "faster-whisper")
        self.assertEqual(profile.device, "cuda")
        self.assertEqual(profile.compute_type, "float16")
        self.assertEqual(profile.batch_size, 8)

    def test_selects_cpu_int8_profile_when_cuda_is_unavailable(self):
        profile = select_profile(
            CapabilityProbe(
                system="Linux",
                machine="x86_64",
                cpu_cores=8,
                available_memory_bytes=16 * 1024**3,
                cpu_compute_types={"int8", "float32"},
            )
        )

        self.assertEqual(profile.engine, "faster-whisper")
        self.assertEqual(profile.device, "cpu")
        self.assertEqual(profile.compute_type, "int8")
        self.assertEqual(profile.cpu_threads, 8)

    def test_explicit_unavailable_engine_fails_without_silent_fallback(self):
        with self.assertRaises(ProfileError):
            select_profile(
                CapabilityProbe(
                    system="Linux",
                    machine="x86_64",
                    cpu_cores=4,
                    available_memory_bytes=8 * 1024**3,
                ),
                requested_engine="whisper-cpp",
            )


if __name__ == "__main__":
    unittest.main()
