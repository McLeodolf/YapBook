"""Small vector toolbar icons and tooltips, rendered crisply with bundled Pillow."""

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk


# A 24-unit vector grid; the same primitives can be exported as editable SVGs.
ICONS = {
    "play": [("polygon", (8, 4, 20, 12, 8, 20))],
    "pause": [("rect", (6, 4, 9, 20)), ("rect", (15, 4, 18, 20))],
    "stop": [("rect", (6, 6, 18, 18))],
    "previous": [("line", (5, 5, 5, 19)), ("polygon", (18, 5, 8, 12, 18, 19))],
    "next": [("polygon", (6, 5, 16, 12, 6, 19)), ("line", (19, 5, 19, 19))],
    "folder": [("line", (3, 9, 3, 5, 9, 5, 12, 8, 21, 8, 21, 10)),
               ("line", (3, 10, 22, 10, 19, 20, 2, 20, 3, 10))],
    "recent": [("circle", (4, 4, 21, 21)), ("line", (12, 7, 12, 13, 16, 15)),
               ("line", (2, 3, 2, 9, 7, 9))],
    "bookmark": [("line", (6, 3, 18, 3, 18, 21, 12, 17, 6, 21, 6, 3))],
    "bookmark_add": [("line", (5, 3, 13, 3)), ("line", (17, 13, 17, 21, 11, 17, 5, 21, 5, 3)),
                     ("line", (18, 3, 18, 9)), ("line", (15, 6, 21, 6))],
    "preview": [("line", (5, 13, 5, 9, 7, 5, 12, 3, 17, 5, 19, 9, 19, 13)),
                ("outline", (3, 12, 7, 20)), ("outline", (17, 12, 21, 20))],
    "star": [("line", (12, 3, 15, 9, 22, 10, 17, 15, 18, 22, 12, 18, 6, 22, 7, 15, 2, 10, 9, 9, 12, 3))],
    "star_filled": [("polygon", (12, 3, 15, 9, 22, 10, 17, 15, 18, 22, 12, 18, 6, 22, 7, 15, 2, 10, 9, 9))],
    "refresh": [("line", (20, 9, 18, 5, 14, 3, 9, 3, 5, 6, 3, 10)),
                ("line", (20, 3, 20, 9, 14, 9)),
                ("line", (4, 15, 6, 19, 10, 21, 15, 21, 19, 18, 21, 14)),
                ("line", (4, 21, 4, 15, 10, 15))],
    "smaller": [("line", (3, 19, 9, 4, 15, 19)), ("line", (5, 14, 13, 14)), ("line", (17, 12, 23, 12))],
    "larger": [("line", (3, 19, 9, 4, 15, 19)), ("line", (5, 14, 13, 14)),
               ("line", (17, 12, 23, 12)), ("line", (20, 9, 20, 15))],
    "loading": [("line", (6, 3, 18, 3, 18, 6, 6, 18, 6, 21, 18, 21, 18, 18, 6, 6, 6, 3))],
    "sun": [("circle", (7, 7, 17, 17)), ("line", (12, 1, 12, 4)), ("line", (12, 20, 12, 23)),
            ("line", (1, 12, 4, 12)), ("line", (20, 12, 23, 12)), ("line", (4, 4, 6, 6)),
            ("line", (18, 18, 20, 20)), ("line", (4, 20, 6, 18)), ("line", (18, 6, 20, 4))],
    "moon": [("line", (19, 15, 16, 20, 11, 21, 6, 19, 3, 15, 3, 9, 6, 5, 10, 3,
                        8, 7, 8, 11, 11, 15, 15, 16, 19, 15))],
}

LABEL_ICONS = {"Start reading": "play", "Resume": "play", "Pause": "pause",
               "Preparing audio …": "loading", "Preview voice": "preview", "Stop preview": "stop",
               "Favorite": "star", "Unfavorite": "star_filled",
               "Switch to dark mode": "moon", "Switch to light mode": "sun"}


def icon_image(master, name, color="#e2e8f0", size=22):
    scale = 4
    image = Image.new("RGBA", (24 * scale, 24 * scale))
    draw = ImageDraw.Draw(image)
    for kind, coordinates in ICONS[name]:
        points = tuple(value * scale for value in coordinates)
        if kind == "line":
            draw.line(points, fill=color, width=2 * scale, joint="curve")
        elif kind == "polygon":
            draw.polygon(points, fill=color)
        elif kind == "circle":
            draw.ellipse(points, outline=color, width=2 * scale)
        elif kind == "outline":
            draw.rectangle(points, outline=color, width=2 * scale)
        else:
            draw.rectangle(points, fill=color)
    return ImageTk.PhotoImage(image.resize((size, size), Image.Resampling.LANCZOS), master=master)


def icon_svg(name):
    elements = []
    for kind, points in ICONS[name]:
        if kind in ("line", "polygon"):
            pairs = " ".join(f"{points[i]},{points[i + 1]}" for i in range(0, len(points), 2))
            tag = "polyline" if kind == "line" else "polygon"
            fill = "none" if kind == "line" else "currentColor"
            elements.append(f'<{tag} points="{pairs}" fill="{fill}"/>')
        else:
            x, y, right, bottom = points
            if kind == "circle":
                elements.append(f'<ellipse cx="{(x + right) / 2}" cy="{(y + bottom) / 2}" rx="{(right - x) / 2}" ry="{(bottom - y) / 2}" fill="none"/>')
            else:
                fill = "none" if kind == "outline" else "currentColor"
                elements.append(f'<rect x="{x}" y="{y}" width="{right - x}" height="{bottom - y}" fill="{fill}"/>')
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + ''.join(elements) + '</svg>\n'


class IconButton(ttk.Button):
    def __init__(self, master, icon, label, command, **kwargs):
        self.label = label
        self.icon = icon
        self.icon_color = "#e2e8f0"
        self.tooltip = None
        self.tooltip_timer = None
        super().__init__(master, command=command, style="Icon.TButton", **kwargs)
        self._set_icon(icon)
        self.bind("<Enter>", self._schedule_tooltip)
        self.bind("<FocusIn>", self._schedule_tooltip)
        for event in ("<Leave>", "<FocusOut>", "<ButtonPress-1>", "<Destroy>"):
            self.bind(event, self._hide_tooltip)
        self.bind("<Return>", lambda _event: self.invoke())

    def _set_icon(self, name):
        self.icon = name
        color = "#b68b16" if name == "star_filled" else self.icon_color
        self.normal_image = icon_image(self, name, color)
        self.disabled_image = icon_image(self, name, "#64748b")
        super().configure(image=(self.normal_image, "disabled", self.disabled_image))

    def set_color(self, color):
        if self.icon_color != color:
            self.icon_color = color
            self._set_icon(self.icon)

    def configure(self, cnf=None, **kwargs):
        if "text" in kwargs:
            label = kwargs.pop("text")
            if label != self.label:
                self._hide_tooltip()
                self.label = label
            icon = LABEL_ICONS.get(label, self.icon)
            if icon != self.icon:
                self._set_icon(icon)
        return super().configure(cnf, **kwargs)

    def _schedule_tooltip(self, _event=None):
        self._hide_tooltip()
        self.tooltip_timer = self.after(450, self._show_tooltip)

    def _show_tooltip(self):
        self.tooltip_timer = None
        self.tooltip = tip = tk.Toplevel(self)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tk.Label(tip, text=self.label, bg="#334155", fg="#f8fafc",
                 font=("Segoe UI", 10), padx=9, pady=5).pack()
        tip.update_idletasks()
        x = min(self.winfo_rootx(), self.winfo_screenwidth() - tip.winfo_reqwidth() - 8)
        y = self.winfo_rooty() + self.winfo_height() + 6
        if y + tip.winfo_reqheight() > self.winfo_screenheight():
            y = self.winfo_rooty() - tip.winfo_reqheight() - 6
        tip.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _hide_tooltip(self, _event=None):
        if self.tooltip_timer is not None:
            self.after_cancel(self.tooltip_timer)
            self.tooltip_timer = None
        if self.tooltip is not None:
            self.tooltip.destroy()
            self.tooltip = None
