"""Windows audio-device integration check; run explicitly on a desktop PC."""

import os
from pathlib import Path
import tempfile
import unittest

from tests.desktop.test_app_state import silent_wav


@unittest.skipUnless(os.name == 'nt', 'The desktop player uses Windows MCI')
class WindowsAudioTests(unittest.TestCase):
    def test_kokoro_pcm_wav_supports_volume_pause_resume_and_seek(self):
        from yapbook.windows_audio import WindowsAudio
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'generated.wav'
            path.write_bytes(silent_wav(3000))
            player = WindowsAudio()
            try:
                player.play(path, volume=0)
                self.assertEqual(player.mode(), 'playing')
                self.assertEqual(player.command(f'status {player.alias} volume'), '0')
                player.set_volume(375)
                self.assertEqual(player.command(f'status {player.alias} volume'), '375')
                player.set_volume(0)
                player.pause()
                self.assertEqual(player.mode(), 'paused')
                player.seek(1200)
                self.assertEqual(player.mode(), 'playing')
                self.assertGreaterEqual(player.position_ms(), 1200)
                self.assertLess(player.position_ms(), 2000)
                player.pause()
                player.resume()
                self.assertEqual(player.mode(), 'playing')
            finally:
                player.close()
            self.assertEqual(player.mode(), 'stopped')


if __name__ == "__main__":
    unittest.main()
