"""Shared colors, fonts and small widget helpers (matches ui_sketch.html)."""
import tkinter as tk
from tkinter import ttk

BG = "#f4f5f7"      # window background
CARD = "#ffffff"    # panels
LINE = "#c9ced6"    # borders
INK = "#1f2430"     # main text
MUTE = "#6b7280"    # secondary text
ACC = "#2f6fed"     # accent / primary button
ACC_DARK = "#2459c7"
ME = "#dbe8ff"      # my bubbles / selected row
THEM = "#eef0f3"    # others' bubbles / hover
BOT = "#e6f6ea"     # chatbot bubbles
MENTION = "#fff4d6"       # bubbles that mention you, mention notifications, sidebar rows
MENTION_TAG = "#ffd666"   # highlight behind "@you", "@" badges in the sidebar
MENTION_DOT = "#f59e0b"   # dot on a chat tab while unread messages mention you
ERR = "#dd3333"
ONLINE = "#2db36a"

FAMILY = "Segoe UI"
F = (FAMILY, 10)
F_SMALL = (FAMILY, 8)
F_BOLD = (FAMILY, 10, "bold")
F_SECTION = (FAMILY, 8, "bold")
F_EMOJI = ("Segoe UI Emoji", 15)


def setup_style(root):
    root.configure(bg=BG)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure("Chat.TNotebook", background=BG, borderwidth=0)
    s.configure("Chat.TNotebook.Tab", font=F, padding=(12, 4), background=THEM, foreground=MUTE, bordercolor=LINE)
    s.map("Chat.TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", INK)])
    s.configure("Vertical.TScrollbar", background=THEM, troughcolor=CARD, bordercolor=CARD, arrowcolor=MUTE)
    _add_tab_close_button(root, s)


def _x_image(root, color, bg=None, size=14):
    """Draw a small ✕ icon pixel by pixel (no image files needed)."""
    img = tk.PhotoImage(master=root, width=size, height=size)
    if bg:
        img.put(bg, to=(1, 1, size - 1, size - 1))
    for i in range(4, size - 4):
        for x, y in ((i, i), (i + 1, i), (size - 1 - i, i), (size - 2 - i, i)):
            img.put(color, to=(x, y))
    return img


def dot_image(root, color, bg, size=10, gap=4):
    """A round dot with soft edges blended into bg, then a transparent gap (no image files)."""
    img = tk.PhotoImage(master=root, width=size + gap, height=size)
    rgb = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (color, bg)]
    r = size / 2
    for y in range(size):
        for x in range(size):  # share of 4x4 sample points inside the circle
            t = sum((x + (i + .5) / 4 - r) ** 2 + (y + (j + .5) / 4 - r) ** 2 <= r * r
                    for i in range(4) for j in range(4)) / 16
            if t:
                img.put("#" + "".join(f"{round(a * t + b * (1 - t)):02x}" for a, b in zip(*rgb)),
                        to=(x, y))
    return img


def _add_tab_close_button(root, s):
    """Add a ✕ element to every chat tab. MainWindow handles the click."""
    root._close_imgs = imgs = (_x_image(root, MUTE), _x_image(root, INK, "#d9dde3"),
                               _x_image(root, "white", ERR))
    s.element_create("close", "image", imgs[0],
                     ("active", "pressed", "!disabled", imgs[2]),
                     ("active", "!disabled", imgs[1]), border=6, sticky="")
    s.layout("Chat.TNotebook.Tab", [
        ("Notebook.tab", {"sticky": "nswe", "children": [
            ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                ("Notebook.focus", {"side": "top", "sticky": "nswe", "children": [
                    ("Notebook.label", {"side": "left", "sticky": ""}),
                    ("Notebook.close", {"side": "left", "sticky": ""}),
                ]})]})]})])


def button(parent, text, command, primary=False, **kw):
    if primary and parent.tk.call("tk", "windowingsystem") == "aqua":
        # macOS paints its own light button face and ignores bg, so white text would vanish.
        colors = dict(fg=ACC, activeforeground=ACC_DARK, font=F_BOLD)
    else:
        colors = dict(fg="white" if primary else ACC, activeforeground="white" if primary else ACC, font=F)
    b = tk.Button(parent, text=text, command=command, relief="flat", bd=0, cursor="hand2",
                  padx=10, pady=3, highlightthickness=1, highlightbackground=ACC,
                  bg=ACC if primary else CARD, activebackground=ACC_DARK if primary else ME,
                  **colors, **kw)
    b.primary = primary
    return b


def set_enabled(widget, ok):
    if isinstance(widget, tk.Button):
        p = getattr(widget, "primary", False)
        widget.config(state="normal" if ok else "disabled",
                      bg=(ACC if p else CARD) if ok else THEM,
                      disabledforeground=MUTE, cursor="hand2" if ok else "arrow")
    else:
        widget.config(state="normal" if ok else "disabled")


def entry(parent, **kw):
    return tk.Entry(parent, font=F, relief="flat", bg=BG, fg=INK, insertbackground=INK,
                    highlightthickness=1, highlightbackground=LINE, highlightcolor=ACC,
                    disabledbackground=THEM, **kw)


def section(parent, text, bg=CARD):
    return tk.Label(parent, text=text.upper(), font=F_SECTION, fg=MUTE, bg=bg, anchor="w")


def bind_tree(widget, sequence, func):
    """Bind on a widget and all its children (so clicks anywhere on a row/bubble work)."""
    widget.bind(sequence, func)
    for child in widget.winfo_children():
        bind_tree(child, sequence, func)


class ScrollFrame(tk.Frame):
    """Vertically scrollable frame; put content in .inner."""

    def __init__(self, master, bg=CARD):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.bind("<Enter>", self._wheel_on)
        self.bind("<Leave>", self._wheel_off)

    def _wheel_on(self, _e):
        self.canvas.bind_all("<MouseWheel>", self._wheel)                   # Windows / macOS
        self.canvas.bind_all("<Button-4>", lambda _e: self.canvas.yview_scroll(-1, "units"))  # Linux
        self.canvas.bind_all("<Button-5>", lambda _e: self.canvas.yview_scroll(1, "units"))

    def _wheel_off(self, _e):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.unbind_all(seq)

    def _wheel(self, e):
        step = int(-e.delta / 120) or (-1 if e.delta > 0 else 1)
        self.canvas.yview_scroll(step, "units")

    def scroll_to_end(self):
        self.update_idletasks()
        self.canvas.yview_moveto(1.0)
