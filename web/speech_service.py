"""Session-local, cancellable speech jobs. Books never enter the Python process."""
import asyncio
import base64
import html
import re
import threading

import edge_tts

_CAPACITY = threading.BoundedSemaphore(4)
_VOICE = re.compile(r"[a-z]{2,3}-[A-Z]{2}-[A-Za-z0-9]+Neural")


def validate_request(request):
    if not isinstance(request, dict) or not isinstance(request.get("id"), str) or len(request["id"]) > 100:
        raise ValueError("Invalid request.")
    if request.get("action") in ("voices", "cancel", "ack"):
        return
    if request.get("action") != "speech":
        raise ValueError("Unknown request.")
    text = request.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 1100:
        raise ValueError("Please select a sentence of up to 1,100 characters.")
    if not isinstance(request.get("voice"), str) or not _VOICE.fullmatch(request["voice"]):
        raise ValueError("Choose a valid reading voice.")
    if type(request.get("rate")) is not int or not -65 <= request["rate"] <= 85:
        raise ValueError("The reading speed is out of range.")


async def synthesize(request, progress):
    if request["action"] == "voices":
        voices = await edge_tts.list_voices()
        return {"voices": [{"name": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"]} for v in voices]}
    audio = bytearray()
    boundaries = []
    speech = edge_tts.Communicate(request["text"], request["voice"], rate=f'{request["rate"]:+d}%', boundary="SentenceBoundary")
    async for event in speech.stream():
        if event["type"] == "audio":
            audio.extend(event["data"])
            if len(audio) > 4 * 1024 * 1024:
                raise ValueError("The voice service returned too much audio.")
            progress(len(audio))
        elif event["type"] == "SentenceBoundary":
            boundaries.append({"text": html.unescape(event["text"]), "offset": event["offset"], "duration": event["duration"]})
    if not audio or not boundaries:
        raise ValueError("This voice returned no usable audio or sentence timing. Please retry or choose another voice.")
    return {"audio": base64.b64encode(audio).decode("ascii"), "boundaries": boundaries}


async def run_cancellable(request, cancelled, progress):
    task = asyncio.create_task(synthesize(request, progress))
    try:
        async with asyncio.timeout(90 if request["action"] == "speech" else 20):
            while not task.done():
                if cancelled.is_set():
                    raise asyncio.CancelledError
                await asyncio.wait({task}, timeout=0.1)
            return await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class SpeechSession:
    def __init__(self):
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self._reply = {"id": "", "status": "idle"}

    def snapshot(self):
        with self._lock:
            return dict(self._reply)

    def _update(self, request_id, **fields):
        with self._lock:
            if self._reply["id"] == request_id:
                self._reply.update(fields)

    def submit(self, request):
        if request is None:
            return
        try:
            validate_request(request)
        except ValueError as exc:
            with self._lock:
                self._reply = {"id": request.get("id", "invalid") if isinstance(request, dict) else "invalid", "status": "error", "error": str(exc)}
            return
        if request["action"] == "ack":
            # Once delivered, avoid sending the same audio on every fragment refresh.
            with self._lock:
                if request["id"] == self._reply["id"] and self._reply["status"] == "ready":
                    self._reply = {"id":request["id"], "status":"idle"}
            return
        if request["id"] == self.snapshot()["id"]:
            return
        self._cancelled.set()
        cancelled = self._cancelled = threading.Event()
        with self._lock:
            self._reply = {"id": request["id"], "status": "idle" if request["action"] == "cancel" else "preparing", "bytes": 0}
        if request["action"] != "cancel":
            threading.Thread(target=self._work, args=(dict(request), cancelled), daemon=True).start()

    def _work(self, request, cancelled):
        request_id = request["id"]
        # Bound simultaneous external requests across all browser sessions.
        if not _CAPACITY.acquire(timeout=1):
            self._update(request_id, status="error", error="The voice service is busy. Please retry in a moment.")
            return
        try:
            result = asyncio.run(run_cancellable(request, cancelled, lambda count: self._update(request_id, bytes=count)))
            if not cancelled.is_set():
                self._update(request_id, status="ready", result=result)
        except asyncio.CancelledError:
            pass
        except TimeoutError:
            self._update(request_id, status="error", error="The voice service timed out. Please retry this sentence or choose another voice.")
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else "The voice service could not finish this request. Please retry or choose another voice."
            self._update(request_id, status="error", error=message)
        finally:
            _CAPACITY.release()
