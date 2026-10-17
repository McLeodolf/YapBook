import asyncio
import threading
import time
import unittest
from unittest.mock import patch

from speech_service import SpeechSession, run_cancellable, validate_request

REQUEST = {"id": "one", "action": "speech", "text": "An invented test sentence.", "voice": "en-US-BrianMultilingualNeural", "rate": -15}


class SpeechTests(unittest.TestCase):
    def test_validation(self):
        validate_request(REQUEST)
        for changed in ({"text": "x"*1101}, {"voice": "invalid"}, {"rate": True}, {"rate": 999}, {"action": "unknown"}):
            with self.assertRaises(ValueError):
                validate_request({**REQUEST, **changed})

    def test_cancels_a_stalled_network_request(self):
        async def stalled(*args):
            await asyncio.sleep(100)
        cancelled = threading.Event()
        cancelled.set()
        with patch("speech_service.synthesize", stalled):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(run_cancellable(REQUEST, cancelled, lambda size: None))

    def test_new_request_discards_old_result(self):
        async def fake(request, progress):
            await asyncio.sleep(0.1)
            return {"audio": request["id"]}
        session = SpeechSession()
        with patch("speech_service.synthesize", fake):
            session.submit(REQUEST)
            session.submit({**REQUEST, "id": "two"})
            deadline = time.monotonic()+3
            while session.snapshot()["status"] != "ready" and time.monotonic()<deadline:
                time.sleep(0.01)
        self.assertEqual(session.snapshot()["result"]["audio"], "two")
        session.submit({"id":"one", "action":"ack"})
        self.assertIn("result", session.snapshot())
        session.submit({"id":"two", "action":"ack"})
        self.assertNotIn("result", session.snapshot())
        session.submit({"id":"cancel", "action":"cancel"})
        self.assertNotIn("result", session.snapshot())


if __name__ == "__main__":
    unittest.main()
