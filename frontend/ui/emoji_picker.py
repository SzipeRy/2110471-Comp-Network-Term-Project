import tkinter as tk

from . import theme as T

EMOJIS = "😀 😂 😍 👍 🎉 😢 😮 🙏 ❤️ 🔥 😎 🤔".split()


class EmojiPicker(tk.Toplevel):
    """Sketch 6 · popup above the 😀 button; clicking an emoji inserts it."""

    def __init__(self, anchor_widget, on_pick):
        super().__init__(anchor_widget)
        self.title("Emoji")
        self.configure(bg=T.CARD, padx=6, pady=6)
        self.resizable(False, False)
        self.transient(anchor_widget.winfo_toplevel())
        for i, e in enumerate(EMOJIS):
            tk.Button(self, text=e, font=T.F_EMOJI, relief="flat", bd=0, bg=T.CARD,
                      activebackground=T.THEM, cursor="hand2", width=2,
                      command=lambda e=e: (on_pick(e), self.destroy())
                      ).grid(row=i // 4, column=i % 4, padx=2, pady=2)
        self.update_idletasks()
        x = anchor_widget.winfo_rootx() - self.winfo_width() + anchor_widget.winfo_width()
        y = anchor_widget.winfo_rooty() - self.winfo_height() - 30
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.focus_set()
