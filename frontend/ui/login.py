import socket
import threading
import tkinter as tk

from .net_interface import NameTakenError
from . import theme as T


def _default_host():
    try:  # same default as the team's server (it binds to this machine's IP)
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


class LoginFrame(tk.Frame):
    """Sketch 1 · R3: unique username. Shows an error if the server rejects the name."""

    def __init__(self, master, app):
        super().__init__(master, bg=T.BG)
        self.app = app
        self.host = tk.StringVar(value=_default_host())
        self.port = tk.StringVar(value="5050")
        self.name = tk.StringVar()

        card = tk.Frame(self, bg=T.CARD, highlightthickness=1, highlightbackground=T.LINE)
        card.pack(padx=20, pady=20)
        tk.Label(card, text="Chat – Login", font=T.F_BOLD, bg=T.BG, fg=T.INK,
                 anchor="w", padx=12, pady=6).pack(fill="x")
        tk.Frame(card, bg=T.LINE, height=1).pack(fill="x")

        body = tk.Frame(card, bg=T.CARD, padx=20, pady=14)
        body.pack()
        for label, var in (("Server IP", self.host), ("Port", self.port), ("Username", self.name)):
            tk.Label(body, text=label, font=T.F, bg=T.CARD, fg=T.INK, anchor="w").pack(fill="x")
            e = T.entry(body, textvariable=var, width=32)
            e.pack(fill="x", pady=(2, 10), ipady=4)
        e.focus()  # username box
        e.bind("<Return>", lambda _e: self.connect())

        self.status = tk.Label(body, text="", font=T.F_SMALL, bg=T.CARD, fg=T.ERR,
                               anchor="w", justify="left", wraplength=260)
        self.status.pack(fill="x", pady=(0, 8))
        row = tk.Frame(body, bg=T.CARD)
        row.pack(fill="x")
        self.btn = T.button(row, "Connect", self.connect, primary=True)
        self.btn.pack(side="left")
        T.button(row, "Quit", app.close).pack(side="left", padx=6)

    def connect(self):
        name = self.name.get().strip()
        if not name or not name.replace("_", "").isalnum():
            self._show("Username: letters, digits and _ only", error=True)
            return
        self._show("Connecting…", error=False)
        T.set_enabled(self.btn, False)
        threading.Thread(target=self._work, args=(name,), daemon=True).start()

    def _work(self, name):  # blocking connect runs off the UI thread
        try:
            self.app.client.connect(self.host.get().strip(), int(self.port.get()), name)
            self.app.after(0, self.app.show_main, name)
        except NameTakenError:
            self.app.after(0, self._fail, f'Username "{name}" is already taken')
        except (ConnectionError, OSError, ValueError) as ex:
            self.app.after(0, self._fail, f"Cannot connect: {ex}")

    def _show(self, text, error):
        self.status.config(text=text, fg=T.ERR if error else T.MUTE)

    def _fail(self, text):
        self._show(text, error=True)
        T.set_enabled(self.btn, True)
