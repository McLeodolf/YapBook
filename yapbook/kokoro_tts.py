"""Optional local Kokoro CUDA runtime, isolated from the packaged app's Python."""

import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile


DEFAULT_VOICE = "af_heart"
CACHE_VERSION = "kokoro-82m-v1-onnx-cuda-1"
_VOICE_IDS = ("af_alloy af_aoede af_bella af_heart af_jessica af_kore af_nicole "
              "af_nova af_river af_sarah af_sky am_adam am_echo am_eric am_fenrir "
              "am_liam am_michael am_onyx am_puck am_santa bf_alice bf_emma "
              "bf_isabella bf_lily bm_daniel bm_fable bm_george bm_lewis").split()
VOICES = [{"ShortName": name, "Locale": "en-US" if name[0] == "a" else "en-GB",
           "FriendlyName": name.split("_", 1)[1].title() + " (Kokoro)",
           "Gender": "Female" if name[1] == "f" else "Male"} for name in _VOICE_IDS]
_UV_URL = "https://github.com/astral-sh/uv/releases/download/0.12.10/uv-x86_64-pc-windows-msvc.zip"
_UV_HASH = "f65744f94072152b1f86ba2aace4d01f1124d9a8ecb235805039e3718c36cac2"
_MODEL_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
_MODEL_HASHES = {"kokoro-v1.0.onnx": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5", "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"}
_INSTALL_LOCK = threading.Lock()
_INFERENCE_LOCK = threading.Lock()
_PROCESS_LOCK = threading.Lock()
_process = None
_responses = None


def runtime_dir():
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local / "YapBook" / "kokoro-v1"


def _resource(name):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    folder = {"kokoro_worker.py": "yapbook", "requirements-kokoro.lock": "requirements"}[name]
    return root / folder / name


def _interpreter():
    return runtime_dir() / "env" / "Scripts" / "python.exe"


def is_installed():
    """A cheap local check; selecting the engine never starts a download."""
    try:
        marker = json.loads((runtime_dir() / "ready.json").read_text(encoding="utf-8"))
        return (isinstance(marker, dict) and marker.get("version") == CACHE_VERSION and _interpreter().is_file()
                and all((runtime_dir() / "models" / name).is_file() for name in _MODEL_HASHES))
    except (OSError, ValueError):
        return False


def _cancelled(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError("Kokoro setup was cancelled. You can resume it next time.")


def _report(progress, message):
    if progress is not None:
        progress(message)


def _require_nvidia():
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("Local Kokoro requires 64-bit Windows and an NVIDIA CUDA GPU.")
    try:
        driver = ctypes.WinDLL("nvcuda.dll")
        count = ctypes.c_int()
        if driver.cuInit(0) or driver.cuDeviceGetCount(ctypes.byref(count)) or count.value < 1:
            raise OSError("No CUDA device")
    except (OSError, AttributeError) as error:
        raise RuntimeError("Kokoro GPU needs an NVIDIA GPU with a working NVIDIA driver. "
                           "Select Online voices on this computer.") from error


def _download(url, destination, expected_hash, progress=None, cancelled=None):
    destination = Path(destination)
    if destination.is_file():
        with destination.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() == expected_hash:
                return
    _cancelled(cancelled)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "YapBook-Kokoro-Setup"})
        with urllib.request.urlopen(request, timeout=30) as response, temporary.open("wb") as output:
            total = int(response.headers.get("Content-Length", 0))
            received, last_report = 0, 0
            digest = hashlib.sha256()
            while chunk := response.read(1024 * 1024):
                _cancelled(cancelled)
                output.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if time.monotonic() - last_report >= 0.3:
                    amount = f"{received / 1024 ** 2:.0f} MB"
                    if total:
                        amount += f" / {total / 1024 ** 2:.0f} MB"
                    _report(progress, f"Downloading {destination.name}: {amount}")
                    last_report = time.monotonic()
        if digest.hexdigest() != expected_hash:
            raise RuntimeError(f"The download of {destination.name} failed its integrity check. Please retry.")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _hidden_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def _collect_lines(stream, destination):
    try:
        for line in iter(stream.readline, ""):
            destination.put(line.rstrip("\r\n"))
    finally:
        stream.close()
        destination.put(None)


def _run_setup(arguments, progress, cancelled, env):
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", env=env,
                               **_hidden_options())
    output = queue.Queue()
    threading.Thread(target=_collect_lines, args=(process.stdout, output), daemon=True).start()
    try:
        while True:
            _cancelled(cancelled)
            try:
                line = output.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                break
            words = line.strip().split()
            if len(words) >= 2 and words[0] in ("Downloading", "Downloaded", "Installed", "Prepared", "Resolved"):
                # Never display arbitrary installer output: it may contain authenticated URLs.
                if all(char.isalnum() or char in "-_." for char in words[1]):
                    _report(progress, " ".join(words[:2]))
        if process.wait() != 0:
            raise RuntimeError("Kokoro setup failed. Check your internet connection and available disk space, "
                               "then retry. The installer did not complete successfully.")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def install(progress=None, cancelled=None):
    """Install only after UI consent. Cancel stops downloads/setup; retries reuse caches."""
    with _INSTALL_LOCK:
        if is_installed():
            return
        _cancelled(cancelled)
        _require_nvidia()
        root = runtime_dir()
        root.mkdir(parents=True, exist_ok=True)
        archive = root / "uv.zip"
        _download(_UV_URL, archive, _UV_HASH, progress, cancelled)
        uv = root / "uv.exe"
        with zipfile.ZipFile(archive) as bundle:
            # Read one known executable instead of extracting untrusted paths.
            with uv.open("wb") as output:
                output.write(bundle.read("uv.exe"))
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("UV_", "PIP_"))}
        env.update({"UV_PYTHON_INSTALL_DIR": str(root / "python"),
                    "UV_CACHE_DIR": str(root / "downloads"), "UV_NO_PROGRESS": "1",
                    "UV_PYTHON_PREFERENCE": "only-managed", "UV_LINK_MODE": "copy"})
        _report(progress, "Installing the isolated Python runtime...")
        _run_setup([str(uv), "--no-config", "python", "install", "3.13.15", "--no-bin"], progress, cancelled, env)
        if not _interpreter().is_file():
            _run_setup([str(uv), "--no-config", "venv", str(root / "env"), "--python", "3.13.15", "--no-project"],
                       progress, cancelled, env)
        _report(progress, "Installing the GPU voice runtime (about 2 GB download)...")
        _run_setup([str(uv), "--no-config", "pip", "install", "--python", str(_interpreter()),
                    "--default-index", "https://pypi.org/simple",
                    "--no-deps", "--require-hashes", "-r", str(_resource("requirements-kokoro.lock"))],
                   progress, cancelled, env)
        for name, digest in _MODEL_HASHES.items():
            _download(_MODEL_BASE + name, root / "models" / name, digest, progress, cancelled)
        _cancelled(cancelled)
        _report(progress, "Checking the NVIDIA GPU and loading Kokoro...")
        with _INFERENCE_LOCK:
            result = _exchange({"action": "check"}, progress, cancelled)
        if result.get("provider") != "CUDAExecutionProvider":
            close()
            raise RuntimeError("Kokoro could not activate the NVIDIA GPU. CPU fallback is disabled.")
        _cancelled(cancelled)
        marker = root / "ready.json"
        temporary = marker.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": CACHE_VERSION, "provider": result["provider"]}), encoding="utf-8")
        temporary.replace(marker)
        _report(progress, "Kokoro GPU is ready.")


def _start_worker():
    global _process, _responses
    with _PROCESS_LOCK:
        if _process is not None and _process.poll() is None:
            return _process, _responses
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        _process = subprocess.Popen([str(_interpreter()), "-I", "-X", "utf8", "-u", str(_resource("kokoro_worker.py")),
                                     str(runtime_dir() / "models")], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    text=True, encoding="utf-8", env=env, **_hidden_options())
        _responses = queue.Queue()
        threading.Thread(target=_collect_lines, args=(_process.stdout, _responses), daemon=True).start()
        return _process, _responses


def _exchange(request, progress, cancelled=None):
    _cancelled(cancelled)
    process, responses = _start_worker()
    try:
        process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                line = responses.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                raise RuntimeError("The Kokoro GPU process stopped. Update your NVIDIA driver and retry.")
            message = json.loads(line)
            if "progress" in message:
                _report(progress, message["progress"])
                continue
            if "error" in message:
                raise RuntimeError(message["error"])
            return message
        close()
        raise TimeoutError("Kokoro GPU did not finish within five minutes. Please retry or select Online voices.")
    except (OSError, ValueError) as error:
        close()
        raise RuntimeError("The Kokoro GPU connection failed. Please retry.") from error


def synthesize(text, voice=DEFAULT_VOICE, speed=1.0, progress=None, cancelled=None):
    """Return PCM WAV bytes and duration. Started work finishes for shared cache reuse."""
    if voice not in _VOICE_IDS:
        raise ValueError("Choose an available Kokoro English voice.")
    if not isinstance(text, str) or not text.strip() or len(text) > 20000:
        raise ValueError("Kokoro needs a non-empty text chunk of at most 20,000 characters.")
    if not isinstance(speed, (int, float)) or not 0.5 <= speed <= 2.0:
        raise ValueError("Kokoro speed must be between 0.5 and 2.0.")
    if not is_installed():
        raise RuntimeError("Set up Kokoro GPU before reading with local voices.")
    with _INFERENCE_LOCK:
        _cancelled(cancelled)
        result = _exchange({"action": "synthesize", "text": text, "voice": voice, "speed": speed},
                           progress, cancelled)
        return base64.b64decode(result["audio"], validate=True), float(result["duration_ms"])


def close():
    """Release only this app's helper process and GPU allocation."""
    global _process, _responses
    with _PROCESS_LOCK:
        process, _process = _process, None
        _responses = None
    if process is not None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stdin is not None:
            process.stdin.close()
