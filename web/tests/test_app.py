from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest


class AppTests(unittest.TestCase):
    def test_reader_initializes_and_retains_speech_pool_on_rerun(self):
        app = AppTest.from_file(str(Path(__file__).parents[1] / "streamlit_app.py"), default_timeout=15)
        app.run()
        self.assertEqual(len(app.exception), 0)
        pool = app.session_state["speech_pool"]
        self.assertEqual(pool.snapshot()["replies"], [])
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertIs(app.session_state["speech_pool"], pool)


if __name__ == "__main__":
    unittest.main()
