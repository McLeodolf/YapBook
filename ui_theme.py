"""Shared light/dark colors for the desktop controls and library dialogs."""
import ctypes
import sys
import tkinter as tk
from tkinter import ttk

from ui_icons import IconButton


def apply_theme(root, dark):
    background, field = ("#111827", "#1f2937") if dark else ("#f4f5f2", "#ffffff")
    foreground, muted = ("#e2e8f0", "#94a3b8") if dark else ("#263b32", "#65776b")
    hover = "#334155" if dark else "#e1e9dd"
    style = ttk.Style(root)
    style.configure(".", background=background, foreground=foreground, fieldbackground=field,
                    troughcolor=field, bordercolor=hover, lightcolor=hover, darkcolor=hover)
    for name in ("TFrame", "TLabel", "TCheckbutton"):
        style.configure(name, background=background, foreground=foreground)
    for name in ("TButton", "Icon.TButton", "TCombobox", "TEntry", "Treeview", "Treeview.Heading"):
        style.configure(name, background=field, foreground=foreground, fieldbackground=field)
        style.map(name, foreground=[("disabled", muted), ("readonly", foreground)],
                  background=[("active", hover), ("disabled", background)],
                  fieldbackground=[("readonly", field), ("disabled", background)])
    style.map("Treeview", background=[("selected", "#456b55")], foreground=[("selected", "#ffffff")])
    style.map("TCheckbutton", background=[("active", hover)])
    style.configure("Horizontal.TScale", background=hover, troughcolor=field)
    style.configure("Horizontal.TProgressbar", background="#6d9675", troughcolor=field)
    style.configure("TSeparator", background=hover)
    for option, value in (("background", field), ("foreground", foreground),
                          ("selectBackground", "#456b55"), ("selectForeground", "#ffffff")):
        root.option_add(f"*TCombobox*Listbox.{option}", value)
    pending, visited = [root], set()
    while pending:
        widget = pending.pop()
        if str(widget) in visited:
            continue
        visited.add(str(widget))
        if hasattr(widget, "set_document"):
            continue  # The HTML widget manages its own colors and child hierarchy.
        if isinstance(widget, IconButton):
            widget.set_color(foreground)
        elif isinstance(widget, (tk.Tk, tk.Toplevel)):
            widget.configure(bg=background)
        elif isinstance(widget, tk.Label):
            widget.configure(bg=background, fg=foreground)
        pending.extend(widget.winfo_children())
    if sys.platform == "win32":
        # Use the native Windows title-bar theme without changing system settings.
        try:
            value = ctypes.c_int(bool(dark))
            handle = ctypes.windll.user32.GetParent(root.winfo_id())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(handle), 20,
                                                       ctypes.byref(value), ctypes.sizeof(value))
        except (AttributeError, OSError):
            pass
