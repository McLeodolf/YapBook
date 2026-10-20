"""Small Windows audio player shared by the CLI and the reading window."""

import ctypes
from ctypes import wintypes
from pathlib import Path


class WindowsAudio:
    def __init__(self):
        self.alias = f"epub_audio_{id(self)}"
        self.opened = False
        self.winmm = ctypes.WinDLL("winmm")
        self.send = self.winmm.mciSendStringW
        self.send.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.UINT, wintypes.HWND]
        self.send.restype = wintypes.DWORD
        self.error_text = self.winmm.mciGetErrorStringW
        self.error_text.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.UINT]
        self.error_text.restype = wintypes.BOOL

    def command(self, text):
        result = ctypes.create_unicode_buffer(512)
        error = self.send(text, result, len(result), None)
        if error:
            self.error_text(error, result, len(result))
            raise RuntimeError(f"Windows audio: {result.value or error}")
        return result.value

    def play(self, path, volume=1000):
        self.close()
        self.command(f'open "{Path(path).resolve()}" type mpegvideo alias {self.alias}')
        self.opened = True
        try:
            self.command(f"set {self.alias} time format milliseconds")
            self.set_volume(volume)
            self.command(f"play {self.alias}")
        except BaseException:
            self.close()
            raise

    def set_volume(self, volume):
        if self.opened:
            self.command(f"setaudio {self.alias} volume to {max(0, min(1000, int(volume)))}")

    def pause(self):
        self.command(f"pause {self.alias}")

    def resume(self):
        self.command(f"resume {self.alias}")

    def seek(self, position_ms):
        self.command(f"seek {self.alias} to {max(0, int(position_ms))}")
        self.command(f"play {self.alias}")

    def position_ms(self):
        return int(self.command(f"status {self.alias} position"))

    def mode(self):
        return self.command(f"status {self.alias} mode") if self.opened else "stopped"

    def close(self):
        if self.opened:
            self.send(f"close {self.alias}", None, 0, None)
            self.opened = False
