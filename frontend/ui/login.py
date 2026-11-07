import socket
import threading
import tkinter as tk
import unicodedata

from .net_interface import BOT_NAME, NameTakenError
from . import theme as T

RESERVED_NAMES = {"server", BOT_NAME.casefold()}


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
        if self.btn.cget("state") == "disabled":
            return
        name = unicodedata.normalize("NFC", self.name.get().strip())
        if not 1 <= len(name) <= 20 or not name.isprintable() or name.casefold() in RESERVED_NAMES:
            self._show(f"Username: 1–20 printable characters; 'server' and '{BOT_NAME}' are reserved",
                       error=True)
            return
        try:
            port = int(self.port.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self._show("Port must be a number from 1 to 65535", error=True)
            return
        host = self.host.get().strip()
        self._show("Connecting…", error=False)
        T.set_enabled(self.btn, False)
        threading.Thread(target=self._work,
                         args=(self.app.client, self.app.q, host, port, name), daemon=True).start()

    @staticmethod
    def _work(client, events, host, port, name):
        # Keep widget/App references off this worker, including during cleanup.
        try:
            confirmed_name = client.connect(host, port, name)
            events.put(("connected", confirmed_name))
        except NameTakenError:
            events.put(("connect_failed", f'Username "{name}" is already taken'))
        except (ConnectionError, OSError, ValueError, EOFError) as ex:
            events.put(("connect_failed", f"Cannot connect: {ex}"))

    def _show(self, text, error):
        self.status.config(text=text, fg=T.ERR if error else T.MUTE)

    def _fail(self, text):
        self._show(text, error=True)
        T.set_enabled(self.btn, True)
