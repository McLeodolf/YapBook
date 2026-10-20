import asyncio
import threading
import time
import unittest
from unittest.mock import patch

from speech_service import SpeechSession, SpeechPool, run_cancellable, validate_request

REQUEST = {"id": "one", "action": "speech", "text": "An invented test sentence.", "voice": "en-US-BrianMultilingualNeural", "rate": -15}


class SpeechTests(unittest.TestCase):
    def test_prefetch_pool_runs_six_jobs_and_refills_without_duplicate_sends(self):
        calls, release = [], threading.Event()
        async def fake(request, progress):
            calls.append(request['id'])
            while not release.is_set():
                await asyncio.sleep(0.01)
            return {'audio':request['id']}
        pool = SpeechPool()
        requests = [{**REQUEST, 'id':str(i), 'text':f'Sentence {i}.'} for i in range(6)]
        with patch('speech_service.synthesize', fake):
            try:
                for _ in range(4):pool.submit({'action':'batch','requests':requests,'ack':[]})
                deadline=time.monotonic()+3
                while len(calls)<6 and time.monotonic()<deadline:time.sleep(0.01)
                self.assertCountEqual(calls,[str(i) for i in range(6)])
                release.set()
                while any(r['status']!='ready' for r in pool.snapshot()['replies']) and time.monotonic()<deadline:time.sleep(0.01)
                self.assertTrue(all(r['status']=='ready' for r in pool.snapshot()['replies']))
                pool.submit({'action':'batch','requests':requests[1:],'ack':['0']})
                self.assertEqual(len(pool.snapshot()['replies']),5)
                self.assertCountEqual(calls,[str(i) for i in range(6)])
                refill = [*requests[1:], {**REQUEST, 'id':'6', 'text':'Sentence 6.'}]
                for _ in range(4):pool.submit({'action':'batch','requests':refill,'ack':['0']})
                deadline = time.monotonic() + 3
                while len(calls)<7 and time.monotonic()<deadline:time.sleep(0.01)
                self.assertCountEqual(calls,[str(i) for i in range(7)])
                self.assertEqual({r['id'] for r in pool.snapshot()['replies']}, {str(i) for i in range(1,7)})
            finally:
                release.set()
                pool.submit({'action':'batch','requests':[],'ack':[str(i) for i in range(7)]})

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
