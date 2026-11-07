import tkinter as tk
from tkinter import messagebox, ttk

from .net_interface import BOT_NAME, private_room_id, private_peer
from . import theme as T
from .chat_room import ChatRoom
from .groups_dialog import GroupsDialog


class MainWindow(tk.Frame):
    """Sketch 2 · sidebar (R4 online users, R9 groups, AI bot) + tabbed chat rooms (R5)."""

    def __init__(self, master, app):
        super().__init__(master, bg=T.BG)
        self.app = app
        self.rooms = {}       # (room_type, room_id) -> ChatRoom
        self.titles = {}      # ChatRoom -> tab title
        self.groups_dlg = None

        side = tk.Frame(self, bg=T.CARD, width=190)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(self, bg=T.LINE, width=1).pack(side="left", fill="y")

        T.section(side, "Online users").pack(fill="x", padx=12, pady=(12, 2))
        self.users_box = tk.Frame(side, bg=T.CARD)
        self.users_box.pack(fill="x", padx=6)
        T.section(side, "Groups").pack(fill="x", padx=12, pady=(12, 2))
        self.groups_box = tk.Frame(side, bg=T.CARD)
        self.groups_box.pack(fill="x", padx=6)
        T.button(side, "+ New / join group", self.show_groups).pack(anchor="w", padx=12, pady=8)
        T.section(side, "AI").pack(fill="x", padx=12, pady=(8, 2))
        self.ai_box = tk.Frame(side, bg=T.CARD)
        self.ai_box.pack(fill="x", padx=6)
        tk.Label(side, text="Click a name to chat", font=T.F_SMALL, fg=T.MUTE,
                 bg=T.CARD).pack(side="bottom", pady=8)

        right = tk.Frame(self, bg=T.BG)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        # Mention notification bar, shown above the chat tabs for a few seconds.
        self.mention_bar = tk.Frame(right, bg=T.MENTION, highlightthickness=1,
                                    highlightbackground=T.MENTION_TAG)
        # A label, not a button: macOS would draw a native button face over the yellow bar.
        close = tk.Label(self.mention_bar, text="✕", font=T.F, fg=T.MUTE, bg=T.MENTION,
                         padx=6, cursor="hand2")
        close.pack(side="right", padx=(0, 4))
        close.bind("<Button-1>", lambda _e: self.hide_mention())
        close.bind("<Enter>", lambda _e: close.config(fg=T.INK))
        close.bind("<Leave>", lambda _e: close.config(fg=T.MUTE))
        T.button(self.mention_bar, "Open", self.open_mention).pack(side="right", padx=6, pady=4)
        self.mention_lbl = tk.Label(self.mention_bar, font=T.F, fg=T.INK, bg=T.MENTION, anchor="w",
                                    justify="left", wraplength=480, cursor="hand2")
        self.mention_lbl.pack(side="left", fill="x", expand=True, padx=8, pady=4)
        self.mention_lbl.bind("<Button-1>", lambda _e: self.open_mention())
        # Wrap at the label's real width, so a narrow window never hides text under Open.
        self.mention_lbl.bind("<Configure>",
                              lambda e: self.mention_lbl.config(wraplength=max(100, e.width - 16)))
        self.mention_key = None
        self._mention_job = None
        self.mention_dot = T.dot_image(self, T.MENTION_DOT, T.THEM)  # on unselected (gray) tabs
        self.placeholder = tk.Label(right, text="Select a user, group or the chatbot to start chatting",
                                    font=T.F, fg=T.MUTE, bg=T.BG)
        self.placeholder.pack(expand=True)
        self.tabs = ttk.Notebook(right, style="Chat.TNotebook")
        self.tabs.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.tabs.bind("<ButtonPress-1>", self._tab_press, add="+")      # ✕ on a tab
        self.tabs.bind("<ButtonRelease-1>", self._tab_release, add="+")
        if self.tk.call("tk", "windowingsystem") != "aqua":              # middle-click (not macOS)
            self.tabs.bind("<ButtonRelease-2>", self._tab_middle_click)
        self._pressed_tab = None
        self.render_sidebar()

    # ---------- sidebar ----------
    def _row(self, parent, text, on_click, selected=False, dot=False, mentions=0):
        # A chat with unread messages that mention you gets a yellow row and an "@" badge.
        bg = T.ME if selected else (T.MENTION if mentions else T.CARD)
        row = tk.Frame(parent, bg=bg, padx=6, pady=3, cursor="hand2")
        row.pack(fill="x", pady=1)
        if dot:
            c = tk.Canvas(row, width=8, height=8, bg=bg, highlightthickness=0)
            c.create_oval(0, 0, 7, 7, fill=T.ONLINE, outline="")
            c.pack(side="left", padx=(0, 6))
        badge = None
        if mentions:  # packed before the name, so a long name cannot push it out of view
            badge = tk.Label(row, text="@" if mentions == 1 else f"@{mentions}", font=T.F_BOLD,
                             fg=T.INK, bg=T.MENTION_TAG, padx=5)
            badge.pack(side="right")
        tk.Label(row, text=text, font=T.F_BOLD if mentions else T.F, fg=T.INK, bg=bg,
                 anchor="w").pack(side="left", fill="x")

        def hover(on):
            if not selected and row.winfo_exists():
                for w in [row, *row.winfo_children()]:
                    if w is not badge:
                        w.config(bg=T.THEM if on else bg)
        T.bind_tree(row, "<Enter>", lambda _e: hover(True))
        T.bind_tree(row, "<Leave>", lambda _e: hover(False))
        T.bind_tree(row, "<Button-1>", lambda _e: on_click())

    def render_sidebar(self):
        cur = self._current_key()
        for box in (self.users_box, self.groups_box, self.ai_box):
            for w in box.winfo_children():
                w.destroy()
        me = self.app.username

        def mentions(key):
            room = self.rooms.get(key)
            return room.unread_mentions if room else 0

        for u in self.app.users:  # R4: includes yourself
            if u == me:
                self._row(self.users_box, f"{u} (you)", lambda: None, dot=True)
            else:
                rid = private_room_id(me, u)
                self._row(self.users_box, u, lambda rid=rid: self._room("private", rid, select=True),
                          selected=cur == ("private", rid), dot=True, mentions=mentions(("private", rid)))
        if not self.app.groups:
            tk.Label(self.groups_box, text="No groups yet", font=T.F_SMALL, fg=T.MUTE,
                     bg=T.CARD).pack(anchor="w", padx=6)
        for g, info in sorted(self.app.groups.items()):  # R9
            mark = " ✓" if info.joined else ""
            self._row(self.groups_box, f"#{g} ({info.member_count}){mark}", lambda g=g: self.open_group(g),
                      selected=cur == ("group", g), mentions=mentions(("group", g)))
        if self.app.client.supports_bot:
            self._row(self.ai_box, "🤖 Chatbot", self.open_bot, selected=cur == ("bot", "chatbot"),
                      mentions=mentions(("bot", "chatbot")))
        else:
            tk.Label(self.ai_box, text="Chatbot unavailable", font=T.F_SMALL,
                     fg=T.MUTE, bg=T.CARD).pack(anchor="w", padx=6)

    # ---------- updates pushed from the client ----------
    def update_users(self, _users):
        self.render_sidebar()

    def update_groups(self, groups):
        self.render_sidebar()
        for (rtype, rid), room in self.rooms.items():
            if rtype == "group":
                room.set_group_info(groups.get(rid))
        if self.groups_dlg and self.groups_dlg.winfo_exists():
            self.groups_dlg.refresh()

    def on_message(self, msg):
        key = (msg["room_type"], msg["room_id"])
        room = self._room(*key)
        mentioned = room.add_message(msg) and self._mentions_me(msg)
        current = self._current_key() == key
        if mentioned and not current:
            room.unread_mentions += 1
            self.render_sidebar()  # yellow row and "@" badge on this chat
        if not current:
            self._mark_tab(room)
        if mentioned and not (current and self.focus_displayof() is not None):
            self.show_mention(msg, key)

    def _mark_tab(self, room):
        """Unread dot, or an orange dot and "@" (with a count) while unread messages mention you."""
        count = room.unread_mentions
        if count:
            self.tabs.tab(room, text=f"{self.titles[room]}  @{count if count > 1 else ''}",
                          image=self.mention_dot, compound="left")
        else:
            self.tabs.tab(room, text=f"{self.titles[room]}  •", image="")

    # ---------- @mention notifications ----------
    def _mentions_me(self, msg):
        """A person's message that mentions you. The bot's answers highlight names but never
        notify: an echoed or quoted @name would otherwise replace the real mention's bar."""
        me = (self.app.username or "").casefold()
        return (msg["type"] == "chat_message" and msg["sender"] != BOT_NAME
                and msg["sender"].casefold() != me
                and any(name.casefold() == me for name in msg.get("mentions") or ()))

    @staticmethod
    def _place(key):
        rtype, rid = key
        return {"group": f"#{rid}", "private": "a private chat"}.get(rtype, "the chatbot room")

    def show_mention(self, msg, key):
        text = " ".join(msg["text"].split())
        if len(text) > 70:
            text = text[:69] + "…"
        self.mention_lbl.config(text=f"🔔 {msg['sender']} mentioned you in {self._place(key)}: {text}")
        self.mention_key = key
        if not self.mention_bar.winfo_manager():
            first = self.tabs if self.tabs.winfo_manager() else self.placeholder
            self.mention_bar.pack(fill="x", pady=(0, 6), before=first)
        if self._mention_job:
            self.after_cancel(self._mention_job)
        self._mention_job = self.after(8000, self.hide_mention)
        if self.winfo_viewable():
            self.bell()

    def hide_mention(self):
        if self._mention_job:
            self.after_cancel(self._mention_job)
            self._mention_job = None
        self.mention_key = None
        self.mention_bar.pack_forget()

    def open_mention(self):
        key = self.mention_key
        self.hide_mention()
        if key in self.rooms:
            self._room(*key, select=True)

    def destroy(self):
        if self._mention_job:  # no timer may fire after the window is gone
            self.after_cancel(self._mention_job)
            self._mention_job = None
        super().destroy()

    # ---------- rooms / tabs ----------
    def _title(self, rtype, rid):
        if rtype == "private":
            return private_peer(rid, self.app.username)
        return "🤖 Bot" if rtype == "bot" else f"#{rid}"

    def _visible_tabs(self):
        return [t for t in self.tabs.tabs() if self.tabs.tab(t, "state") != "hidden"]

    def _current_key(self):
        if not self._visible_tabs():
            return None
        sel = self.tabs.select()
        for key, room in self.rooms.items():
            if str(room) == sel:
                return key
        return None

    def _show_placeholder_if_empty(self):
        if self._visible_tabs():
            self.placeholder.pack_forget()
            self.tabs.pack(fill="both", expand=True)
        else:
            self.tabs.pack_forget()
            self.placeholder.pack(expand=True)

    def _room(self, rtype, rid, select=False):
        """Get a room, creating it or re-showing a closed tab (history is kept)."""
        key = (rtype, rid)
        if key not in self.rooms:
            room = ChatRoom(self.tabs, self.app, rtype, rid)
            self.rooms[key] = room
            self.titles[room] = self._title(rtype, rid)
            self.tabs.add(room, text=self.titles[room])
            if rtype == "group":
                room.set_group_info(self.app.groups.get(rid))
        elif self.tabs.tab(self.rooms[key], "state") == "hidden":
            self.tabs.add(self.rooms[key])  # re-open a closed tab
        self._show_placeholder_if_empty()
        if select:
            self.tabs.select(self.rooms[key])
        return self.rooms[key]

    # ---------- closing tabs ----------
    def _tab_press(self, e):
        if "close" in self.tabs.identify(e.x, e.y):
            self._pressed_tab = self.tabs.index(f"@{e.x},{e.y}")
            self.tabs.state(["pressed"])
            return "break"  # don't switch to the tab

    def _tab_release(self, e):
        if self._pressed_tab is None:
            return
        self.tabs.state(["!pressed"])
        if "close" in self.tabs.identify(e.x, e.y) and self.tabs.index(f"@{e.x},{e.y}") == self._pressed_tab:
            self.close_tab(self.tabs.tabs()[self._pressed_tab])
        self._pressed_tab = None

    def _tab_middle_click(self, e):
        if self.tabs.identify(e.x, e.y):
            self.close_tab(self.tabs.tabs()[self.tabs.index(f"@{e.x},{e.y}")])

    def close_tab(self, tab_id):
        """Hide the tab. Messages stay; it re-opens from the sidebar or when a new message arrives."""
        room = self.nametowidget(tab_id)
        room.clear_reply()
        room.close_emoji()
        room.hide_suggestions()
        self.tabs.hide(room)
        self._show_placeholder_if_empty()
        self.render_sidebar()

    def close_current(self):
        if self._current_key():
            self.close_tab(self.tabs.select())

    # ---------- leaving a group ----------
    def leave_group(self, name, parent=None):
        if messagebox.askyesno("Leave group", f"Leave #{name}?\nYou will stop receiving its messages.",
                               parent=parent or self):
            self.app.client.leave_group(name)

    def _tab_changed(self, _e=None):
        key = self._current_key()
        for room in self.rooms.values():
            room.hide_suggestions()
        if key:
            room = self.rooms[key]
            room.unread_mentions = 0
            self.tabs.tab(room, text=self.titles[room], image="")  # clear unread dot / mention mark
            if key == self.mention_key:
                self.hide_mention()  # the mention is now in view
            room.entry.focus()
        self.render_sidebar()

    def open_group(self, name):
        self._room("group", name, select=True)

    def open_bot(self):
        self._room("bot", "chatbot", select=True)

    def show_groups(self):
        if self.groups_dlg and self.groups_dlg.winfo_exists():
            self.groups_dlg.lift()
        else:
            self.groups_dlg = GroupsDialog(self, self.app)
