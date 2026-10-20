"""Optional GPU setup and transport tests; no GPU or downloads required."""

import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import sys
import unittest
from unittest.mock import Mock, patch

from yapbook import kokoro_tts
from yapbook import kokoro_worker


class Download(io.BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.headers = {"Content-Length": str(len(content))}


class KokoroBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runtime = patch.object(kokoro_tts, "runtime_dir", return_value=self.root)
        self.runtime.start()

    def tearDown(self):
        self.runtime.stop()
        self.temporary.cleanup()

    def test_voice_catalog_is_english_and_has_a_valid_default(self):
        self.assertIn(kokoro_tts.DEFAULT_VOICE, [voice["ShortName"] for voice in kokoro_tts.VOICES])
        self.assertEqual(len({voice["ShortName"] for voice in kokoro_tts.VOICES}), 28)
        self.assertEqual({voice["Locale"] for voice in kokoro_tts.VOICES}, {"en-US", "en-GB"})
        self.assertEqual(set(kokoro_tts._VOICE_IDS), kokoro_worker._VOICES)

    def test_status_rejects_missing_incomplete_and_malformed_setup(self):
        marker = self.root / "ready.json"
        self.assertFalse(kokoro_tts.is_installed())
        for value in ("broken", "null", "[]", "42", '{"version":"old"}'):
            marker.write_text(value, encoding="utf-8")
            self.assertFalse(kokoro_tts.is_installed())
        marker.write_text(json.dumps({"version": kokoro_tts.CACHE_VERSION}), encoding="utf-8")
        self.assertFalse(kokoro_tts.is_installed())
        interpreter = self.root / "env" / "Scripts" / "python.exe"
        interpreter.parent.mkdir(parents=True)
        interpreter.touch()
        (self.root / "models").mkdir()
        for name in kokoro_tts._MODEL_HASHES:
            (self.root / "models" / name).touch()
        self.assertTrue(kokoro_tts.is_installed())

    def test_download_checks_hash_and_reuses_completed_asset(self):
        content = b"trusted model bytes"
        digest = hashlib.sha256(content).hexdigest()
        destination = self.root / "model.onnx"
        with patch.object(kokoro_tts.urllib.request, "urlopen", return_value=Download(content)) as fetch:
            kokoro_tts._download("https://example.invalid/model", destination, digest)
            self.assertEqual(destination.read_bytes(), content)
            kokoro_tts._download("https://example.invalid/model", destination, digest)
            self.assertEqual(fetch.call_count, 1)
        self.assertFalse(destination.with_suffix(".onnx.part").exists())

    def test_download_integrity_failure_does_not_publish_partial_asset(self):
        destination = self.root / "model.onnx"
        with patch.object(kokoro_tts.urllib.request, "urlopen", return_value=Download(b"corrupt")):
            with self.assertRaisesRegex(RuntimeError, "integrity check"):
                kokoro_tts._download("https://example.invalid/model", destination, "0" * 64)
        self.assertFalse(destination.exists())
        self.assertFalse(destination.with_suffix(".onnx.part").exists())

    def test_cancelled_download_and_synthesis_do_no_work(self):
        cancelled = threading.Event()
        cancelled.set()
        with patch.object(kokoro_tts.urllib.request, "urlopen") as fetch:
            with self.assertRaises(InterruptedError):
                kokoro_tts._download("https://example.invalid/model", self.root / "model", "0" * 64,
                                     cancelled=cancelled)
            fetch.assert_not_called()
        with patch.object(kokoro_tts, "is_installed", return_value=True), \
                patch.object(kokoro_tts, "_exchange") as send:
            with self.assertRaises(InterruptedError):
                kokoro_tts.synthesize("A sentence.", cancelled=cancelled)
            send.assert_not_called()

    def test_synthesis_rejects_invalid_values_before_starting_helper(self):
        with patch.object(kokoro_tts, "_start_worker") as start:
            for arguments in (("",), ("Hello", "en-US-BrianNeural"), ("Hi", "af_heart", 0.1),
                              ("Hello", "af_heart", float("nan")), ("x" * 20001,)):
                with self.assertRaises(ValueError):
                    kokoro_tts.synthesize(*arguments)
            start.assert_not_called()

    def test_synthesis_is_serial_and_keeps_started_result_after_cancel(self):
        cancelled = threading.Event()
        entered, release = threading.Event(), threading.Event()
        active, maximum = 0, 0
        guard = threading.Lock()
        results = []
        def exchange(request, progress, cancel):
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(maximum, active)
            entered.set()
            release.wait(2)
            with guard:
                active -= 1
            return {"audio": base64.b64encode(b"wav").decode("ascii"), "duration_ms": 1000}
        def call(cancel=None):
            results.append(kokoro_tts.synthesize("A sentence.", cancelled=cancel))
        with patch.object(kokoro_tts, "is_installed", return_value=True), \
                patch.object(kokoro_tts, "_exchange", side_effect=exchange):
            first = threading.Thread(target=call, args=(cancelled,))
            second = threading.Thread(target=call)
            first.start()
            self.assertTrue(entered.wait(1))
            second.start()
            cancelled.set()
            release.set()
            first.join(2)
            second.join(2)
        self.assertEqual(maximum, 1)
        self.assertEqual(results, [(b"wav", 1000.0), (b"wav", 1000.0)])

    def test_installed_setup_does_not_launch_installer(self):
        with patch.object(kokoro_tts, "is_installed", return_value=True), \
                patch.object(kokoro_tts, "_run_setup") as run:
            kokoro_tts.install()
            run.assert_not_called()

    def test_stdio_worker_is_reused_and_shutdown_releases_it(self):
        helper = self.root / "fake_worker.py"
        helper.write_text("import sys, json, base64\n"
                          "for line in sys.stdin:\n"
                          "    item = json.loads(line)\n"
                          "    print(json.dumps({'progress':'Generating local audio'}),flush=True)\n"
                          "    print(json.dumps({'audio':base64.b64encode(item['text'].encode()).decode(),"
                          "'duration_ms':1200}),flush=True)\n", encoding="utf-8")
        progress = []
        try:
            with patch.object(kokoro_tts, "is_installed", return_value=True), \
                    patch.object(kokoro_tts, "_interpreter", return_value=Path(sys.executable)), \
                    patch.object(kokoro_tts, "_resource", return_value=helper):
                first = kokoro_tts.synthesize("Perry’s café — déjà vu.", progress=progress.append)
                process = kokoro_tts._process
                second = kokoro_tts.synthesize("Second sentence.", progress=progress.append)
                self.assertIs(kokoro_tts._process, process)
            self.assertEqual(first, ("Perry’s café — déjà vu.".encode("utf-8"), 1200.0))
            self.assertEqual(second, (b"Second sentence.", 1200.0))
            self.assertEqual(progress, ["Generating local audio"] * 2)
        finally:
            kokoro_tts.close()
        self.assertIsNotNone(process.poll())

    def test_installer_output_never_exposes_authenticated_urls(self):
        process = Mock()
        process.stdout = io.StringIO("Downloading numpy (12 MiB)\n"
                                     "Downloading https://user:secret@example.invalid/package\n"
                                     "Error fetching https://user:secret@example.invalid/index\n")
        process.wait.return_value = 1
        process.poll.return_value = 1
        progress = []
        with patch.object(kokoro_tts.subprocess, "Popen", return_value=process):
            with self.assertRaises(RuntimeError) as failure:
                kokoro_tts._run_setup(["installer"], progress.append, None, {})
        self.assertEqual(progress, ["Downloading numpy"])
        self.assertNotIn("secret", str(failure.exception))
        self.assertNotIn("https://", str(failure.exception))

    def test_native_runtime_rejects_unsupported_platform(self):
        with patch.object(kokoro_tts.sys, "platform", "linux"):
            with self.assertRaisesRegex(RuntimeError, "Windows"):
                kokoro_tts._require_nvidia()


class CudaProviderTests(unittest.TestCase):
    def test_cuda_dll_search_is_scoped_to_private_runtime_and_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folders = [root / "Lib" / "site-packages" / "nvidia" / name / "bin"
                       for name in ("cublas", "cudnn")]
            for folder in folders:
                folder.mkdir(parents=True)
            with patch.object(kokoro_worker.sys, "prefix", str(root)), \
                    patch.object(kokoro_worker.sys, "platform", "win32"), \
                    patch.object(kokoro_worker, "_DLL_HANDLES", []), \
                    patch.object(kokoro_worker.os, "add_dll_directory", create=True) as add, \
                    patch.dict(kokoro_worker.os.environ, {"PATH": "original"}):
                kokoro_worker.prepare_dll_search()
                kokoro_worker.prepare_dll_search()
                self.assertEqual(add.call_count, 2)
                self.assertEqual(len(kokoro_worker._DLL_HANDLES), 2)
                self.assertTrue(kokoro_worker.os.environ["PATH"].endswith("original"))
                self.assertTrue(all(str(folder) in kokoro_worker.os.environ["PATH"] for folder in folders))

    def test_missing_cuda_fails_before_model_load(self):
        ort = Mock()
        ort.get_available_providers.return_value = ["CPUExecutionProvider"]
        with self.assertRaisesRegex(RuntimeError, "CUDA runtime"):
            kokoro_worker.create_session(ort, "model.onnx")
        ort.InferenceSession.assert_not_called()

    def test_cpu_fallback_is_rejected(self):
        ort = Mock()
        ort.get_available_providers.return_value = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        ort.InferenceSession.return_value.get_providers.return_value = ["CPUExecutionProvider"]
        with self.assertRaisesRegex(RuntimeError, "CPU fallback is disabled"):
            kokoro_worker.create_session(ort, "model.onnx")

    def test_cuda_is_explicit_and_runtime_fallback_disabled(self):
        ort = Mock()
        ort.get_available_providers.return_value = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        session = ort.InferenceSession.return_value
        session.get_providers.return_value = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self.assertIs(kokoro_worker.create_session(ort, "model.onnx"), session)
        ort.preload_dlls.assert_called_once_with(directory="")
        session.disable_fallback.assert_called_once()
        self.assertEqual(ort.InferenceSession.call_args.kwargs["providers"][0][0], "CUDAExecutionProvider")


if __name__ == "__main__":
    unittest.main()
