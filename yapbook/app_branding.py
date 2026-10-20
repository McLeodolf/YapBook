"""Shared artwork for the source app and the standalone Windows build."""

import ctypes
from pathlib import Path

from PIL import Image, ImageTk


# Source and PyInstaller layouts both keep assets beside the yapbook package.
ASSETS = Path(__file__).resolve().parents[1] / "assets"


class _ShellFileInfo(ctypes.Structure):
    _fields_ = [("icon", ctypes.c_void_p), ("icon_index", ctypes.c_int),
                ("attributes", ctypes.c_uint), ("display_name", ctypes.c_wchar * 260),
                ("type_name", ctypes.c_wchar * 80)]


def apply_app_icon(root):
    set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    set_app_id.argtypes = [ctypes.c_wchar_p]
    set_app_id.restype = ctypes.c_long
    set_app_id("McLeodolf.YapBook")
    # The default also covers child windows and dialogs created by Tk.
    root.iconbitmap(default=str(ASSETS / "yapbook.ico"))
    root.iconbitmap(str(ASSETS / "yapbook.ico"))


def refresh_exe_icon(path):
    """Tell Explorer to reread an EXE replaced by a new build."""
    path = str(Path(path).resolve())
    shell = ctypes.windll.shell32
    info = _ShellFileInfo()
    get_info = shell.SHGetFileInfoW
    get_info.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.POINTER(_ShellFileInfo),
                        ctypes.c_uint, ctypes.c_uint]
    get_info.restype = ctypes.c_void_p
    # Resolve this file's system icon index; YapBook has one icon group at index 0.
    if get_info(path, 0, ctypes.byref(info), ctypes.sizeof(info), 0x4000):
        update_image = shell.SHUpdateImageW
        update_image.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint, ctypes.c_int]
        update_image.restype = None
        update_image(path, 0, 0, info.icon_index)
    notify = shell.SHChangeNotify
    notify.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p]
    notify.restype = None
    # SHCNE_UPDATEITEM, SHCNF_PATHW | SHCNF_FLUSH; only this file is affected.
    notify(0x2000, 0x1005, path, None)


def load_app_logo(root, size=40):
    with Image.open(ASSETS / "yapbook.png") as artwork:
        logo = artwork.resize((size, size), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(logo, master=root)
