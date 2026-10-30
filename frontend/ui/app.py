"""Entry point (run from the frontend folder):
    python -m ui.app          -> mock backend (no server needed)
    python -m ui.app --real   -> real client from Person 4 (frontend/network_client.py, class NetworkClient)"""
import queue
import sys
import tkinter as tk
from tkinter import messagebox

from . import theme
from .login import LoginFrame
from .main_window import MainWindow


class App(tk.Tk):
    def __init__(self, client):
        super().__init__()
        self.title("Chat")
        self.geometry("900x580")
        self.minsize(700, 450)
        theme.setup_style(self)
        self.client = client
        self.username, self.users, self.groups = None, [], {}
        self.main = None
        self.q = queue.Queue()  # network threads -> UI thread (Tkinter is not thread-safe)
        client.set_handlers(
            on_message=lambda m: self.q.put(("msg", m)),
            on_users=lambda u: self.q.put(("users", u)),
            on_groups=lambda g: self.q.put(("groups", g)),
            on_error=lambda e: self.q.put(("error", e)),
            on_disconnect=lambda: self.q.put(("bye", None)))
        self.login = LoginFrame(self, self)
        self.login.pack(expand=True)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self._poll)

    def show_main(self, username):
        self.username = username
        self.login.pack_forget()
        self.main = MainWindow(self, self)
        self.main.pack(fill="both", expand=True)
        self.title(f"Chat – {username}")

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "users":
                    self.users = data
                elif kind == "groups":
                    self.groups = data
                if kind == "error":
                    messagebox.showerror("Error", data)
                elif kind == "bye":
                    messagebox.showwarning("Disconnected", "Lost connection to the server")
                elif self.main:
                    {"msg": self.main.on_message, "users": self.main.update_users,
                     "groups": self.main.update_groups}[kind](data)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def close(self):
        self.client.close()
        self.destroy()


if __name__ == "__main__":
    if "--real" in sys.argv:
        from network_client import NetworkClient  # Person 4's module
        client = NetworkClient()
    else:
        from .mock_client import MockClient
        client = MockClient()
    App(client).mainloop()
