import re
import tkinter as tk

from . import theme as T
from .emoji_picker import EmojiPicker


class ChatRoom(tk.Frame):
    """Sketch 2/4/5 · one chat room (R5): header, message window and chat box (R6).
    Used for private, group and bot rooms."""

    def __init__(self, master, app, room_type, room_id):
        super().__init__(master, bg=T.CARD)
        self.app, self.room_type, self.room_id = app, room_type, room_id
        self.messages = {}      # message_id -> msg (for reply quotes)
        self.reply_to = None
        self.typing_row = None

        # header bar
        head = tk.Frame(self, bg=T.BG)
        head.pack(fill="x")
        self.header = tk.Label(head, font=T.F_BOLD, bg=T.BG, fg=T.INK, anchor="w", padx=10, pady=6)
        self.header.pack(side="left", fill="x", expand=True)
        self.join_btn = T.button(head, "Join", lambda: app.client.join_group(room_id), primary=True)
        tk.Frame(self, bg=T.LINE, height=1).pack(fill="x")

        # chat box (packed at the bottom first so it never gets squeezed out)
        self.bottom = tk.Frame(self, bg=T.CARD, padx=8, pady=8)
        self.bottom.pack(side="bottom", fill="x")
        tk.Frame(self, bg=T.LINE, height=1).pack(side="bottom", fill="x")
        self.reply_bar = tk.Frame(self.bottom, bg=T.CARD)
        tk.Frame(self.reply_bar, bg=T.ACC, width=3).pack(side="left", fill="y")
        self.reply_lbl = tk.Label(self.reply_bar, font=T.F_SMALL, fg=T.MUTE, bg=T.CARD, anchor="w")
        self.reply_lbl.pack(side="left", fill="x", expand=True, padx=6)
        tk.Button(self.reply_bar, text="✕", font=T.F_SMALL, relief="flat", bd=0, bg=T.CARD, fg=T.MUTE,
                  cursor="hand2", command=self.clear_reply).pack(side="right")
        self.locked_lbl = tk.Label(self.bottom, text="Join this group to send messages",
                                   font=T.F_SMALL, fg=T.MUTE, bg=T.CARD, anchor="w")
        self.input_row = tk.Frame(self.bottom, bg=T.CARD)
        self.input_row.pack(fill="x")
        self.entry = T.entry(self.input_row)
        self.entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.entry.bind("<Return>", lambda _e: self.send())
        self.emoji_btn = T.button(self.input_row, "😀", self.open_emoji)
        self.emoji_btn.pack(side="left", padx=4)
        self.send_btn = T.button(self.input_row, "Send", self.send, primary=True)
        self.send_btn.pack(side="left")

        # message window
        self.list = T.ScrollFrame(self)
        self.list.pack(fill="both", expand=True)

        if room_type == "private":
            other = next(u for u in room_id.split("-") if u != app.username)
            self.header.config(text=f"Private chat with {other}")
        elif room_type == "bot":
            self.header.config(text="🤖 Chatbot")
        self.add_system({"private": "Only you and the other person can see this chat",
                         "group": "Only group members can see this chat",
                         "bot": "Ask the AI chatbot anything"}[room_type])

    # ---------- group membership (R10, R11) ----------
    def set_group_info(self, members):
        joined = self.app.username in members
        self.header.config(text=f"#{self.room_id}  ·  members: {', '.join(members) or '-'}")
        if joined:
            self.join_btn.pack_forget()
            self.locked_lbl.pack_forget()
        else:
            self.join_btn.pack(side="right", padx=8)
            self.locked_lbl.pack(fill="x", pady=(0, 4), before=self.input_row)
        for w in (self.entry, self.emoji_btn, self.send_btn):
            T.set_enabled(w, joined)

    # ---------- sending ----------
    def send(self):
        text = self.entry.get().strip()
        if not text or self.entry.cget("state") == "disabled":
            return
        self.app.client.send_message(self.room_type, self.room_id, text, self.reply_to)
        self.entry.delete(0, "end")
        self.clear_reply()
        if self.room_type == "bot":
            self._show_typing()

    def open_emoji(self):
        EmojiPicker(self.emoji_btn, lambda e: (self.entry.insert("insert", e), self.entry.focus()))

    # ---------- displaying ----------
    def add_system(self, text):
        tk.Label(self.list.inner, text=text, font=T.F_SMALL, fg=T.MUTE, bg=T.CARD).pack(pady=(8, 4))

    def add_message(self, msg):
        self.messages[msg["message_id"]] = msg
        mine = msg["sender"] == self.app.username
        if self.typing_row and not mine:
            self.typing_row.destroy()
            self.typing_row = None
        color = T.ME if mine else (T.BOT if self.room_type == "bot" else T.THEM)

        row = tk.Frame(self.list.inner, bg=T.CARD)
        row.pack(fill="x", padx=10, pady=3)
        bubble = tk.Frame(row, bg=color, padx=9, pady=5)
        bubble.pack(side="right" if mine else "left")

        who = "You" if mine else msg["sender"]
        tk.Label(bubble, text=f"{who}  {msg.get('timestamp', '')[11:16]}", font=T.F_SMALL,
                 fg=T.MUTE, bg=color, anchor="w").pack(fill="x")

        quoted = self.messages.get(msg.get("reply_to"))
        if quoted:  # reply quote with a blue strip
            q = tk.Frame(bubble, bg=color)
            q.pack(fill="x", pady=(2, 3))
            tk.Frame(q, bg=T.ACC, width=3).pack(side="left", fill="y")
            tk.Label(q, text=f"{quoted['sender']}: {quoted['text'][:50]}", font=T.F_SMALL, fg=T.MUTE,
                     bg=color, justify="left", wraplength=260).pack(side="left", padx=(5, 0))

        text = msg["text"]
        width = min(max((len(line) for line in text.splitlines()), default=1) + 1, 42)
        body = tk.Text(bubble, font=T.F, bg=color, fg=T.INK, relief="flat", bd=0, highlightthickness=0,
                       wrap="word", width=width, height=1, padx=0, pady=0, cursor="arrow")
        body.tag_config("mention", foreground=T.ACC, font=T.F_BOLD)
        for part in re.split(r"(@\w+)", text):  # highlight @username mentions
            is_mention = part.startswith("@") and part[1:] in self.app.users
            body.insert("end", part, "mention" if is_mention else ())
        body.config(state="disabled")
        body.pack(anchor="w")
        body.bind("<Map>", lambda _e, b=body: self._fit(b))  # measure once it's laid out

        T.bind_tree(bubble, "<Button-3>", lambda e, m=msg["message_id"]: self._menu(e, m))
        T.bind_tree(bubble, "<Button-2>", lambda e, m=msg["message_id"]: self._menu(e, m))  # macOS

    def _fit(self, body):
        """Grow the Text widget to its wrapped height, then scroll down."""
        if not body.winfo_exists():
            return
        body.update_idletasks()
        n = body.count("1.0", "end", "displaylines")
        n = n[0] if isinstance(n, tuple) else n
        body.config(height=max(1, n or 1))
        self.list.scroll_to_end()

    def _show_typing(self):
        if self.typing_row:
            return
        self.typing_row = tk.Frame(self.list.inner, bg=T.CARD)
        self.typing_row.pack(fill="x", padx=10, pady=3)
        tk.Label(self.typing_row, text="Bot is typing…", font=T.F_SMALL, fg=T.MUTE, bg=T.BOT,
                 padx=9, pady=5).pack(side="left")
        self.list.scroll_to_end()

    # ---------- reply (right-click a message) ----------
    def _menu(self, event, message_id):
        if self.entry.cget("state") == "disabled":
            return
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Reply", command=lambda: self.set_reply(message_id))
        m.tk_popup(event.x_root, event.y_root)

    def set_reply(self, message_id):
        msg = self.messages[message_id]
        self.reply_to = message_id
        self.reply_lbl.config(text=f"Replying to {msg['sender']}: {msg['text'][:40]}")
        self.reply_bar.pack(fill="x", pady=(0, 6), before=self.input_row)
        self.entry.focus()

    def clear_reply(self):
        self.reply_to = None
        self.reply_bar.pack_forget()
