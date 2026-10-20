"""Private stdin/stdout helper: book text stays on the user's computer."""

import base64
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import wave


_VOICES = frozenset(("af_alloy af_aoede af_bella af_heart af_jessica af_kore af_nicole "
                    "af_nova af_river af_sarah af_sky am_adam am_echo am_eric am_fenrir "
                    "am_liam am_michael am_onyx am_puck am_santa bf_alice bf_emma "
                    "bf_isabella bf_lily bm_daniel bm_fable bm_george bm_lewis").split())


_DLL_HANDLES = []


def prepare_dll_search():
    # cuDNN loads additional engines lazily; older ORT preload lists omit newer DLLs.
    # Scope their search path to this private helper, never the user's system PATH.
    if sys.platform == "win32" and not _DLL_HANDLES:
        root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
        folders = [folder for folder in root.glob("*/bin") if folder.is_dir()]
        for folder in folders:
            _DLL_HANDLES.append(os.add_dll_directory(str(folder)))
        if folders:
            os.environ["PATH"] = os.pathsep.join(map(str, folders)) + os.pathsep + os.environ.get("PATH", "")


def create_session(ort, model):
    if "CUDAExecutionProvider" not in ort.get_available_providers():
        raise RuntimeError("The NVIDIA CUDA runtime is unavailable. Reinstall Kokoro GPU or select Online voices.")
    prepare_dll_search()
    ort.preload_dlls(directory="")
    options = ort.SessionOptions()
    options.log_severity_level = 3
    options.intra_op_num_threads = 2
    session = ort.InferenceSession(str(model), sess_options=options,
                                   providers=[("CUDAExecutionProvider", {"device_id": 0,
                                               "cudnn_conv_algo_search": "HEURISTIC"})])
    # ONNX may place shape bookkeeping on CPU, but model inference must use CUDA.
    if session.get_providers()[0] != "CUDAExecutionProvider":
        raise RuntimeError("Kokoro could not activate the NVIDIA GPU. Update your NVIDIA driver. CPU fallback is disabled.")
    session.disable_fallback()
    return session


def synthesize(engine, text, voice, speed):
    import numpy as np
    if voice not in _VOICES or not isinstance(text, str) or not text.strip() or len(text) > 20000:
        raise ValueError("Invalid local voice or text chunk.")
    if not isinstance(speed, (int, float)) or not 0.5 <= speed <= 2.0:
        raise ValueError("Invalid Kokoro speed.")
    samples, sample_rate = engine.create(text, voice=voice, speed=speed,
                                        lang="en-us" if voice.startswith("a") else "en-gb")
    if len(samples) == 0 or not np.all(np.isfinite(samples)):
        raise RuntimeError("Kokoro did not return usable audio. Try another voice.")
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(pcm)
    return {"audio": base64.b64encode(output.getvalue()).decode("ascii"),
            "duration_ms": len(samples) * 1000 / sample_rate}


def main():
    model_dir = Path(sys.argv[1])
    engine = None
    protocol = sys.stdout
    def send(message):
        protocol.write(json.dumps(message) + "\n")
        protocol.flush()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("action") not in ("check", "synthesize"):
                raise ValueError("Unknown Kokoro request.")
            # Third-party imports and diagnostics must never corrupt the JSON pipe.
            with contextlib.redirect_stdout(sys.stderr):
                if engine is None:
                    send({"progress": "Loading Kokoro on your NVIDIA GPU..."})
                    import onnxruntime as ort
                    from kokoro_onnx import Kokoro
                    session = create_session(ort, model_dir / "kokoro-v1.0.onnx")
                    engine = Kokoro.from_session(session, str(model_dir / "voices-v1.0.bin"))
                if request["action"] == "check":
                    # Actually run a small inference; provider presence alone is insufficient.
                    synthesize(engine, "Ready.", "af_heart", 1.0)
                    result = {"provider": "CUDAExecutionProvider"}
                else:
                    send({"progress": "Generating audio on your NVIDIA GPU..."})
                    result = synthesize(engine, request["text"], request["voice"], request["speed"])
            send(result)
        except Exception:
            # Exceptions from tokenizers may include book text; do not log or return them.
            send({"error": "Kokoro GPU could not generate audio. Check your NVIDIA driver and available GPU memory, "
                           "then retry or select Online voices."})


if __name__ == "__main__":
    main()
