# AI chatbot and @mentions (Person 3)

Two Part 3 special features: an **AI chatbot** (the project's required AI
feature) and **@username mentions** with highlighting, notifications and
autocomplete. Both work in the Tkinter app and the terminal client, over the
same TCP socket protocol as the rest of the chat.

## Try it

1. On the **server computer** only, install the requirements and give the server
   a Gemini API key. Clients need no key. Get a free key at
   <https://aistudio.google.com/apikey>: sign in with a Google account, accept
   the terms, and copy the key that AI Studio creates.

   ```powershell
   python -m pip install -r requirements.txt
   $env:GEMINI_API_KEY = "your-key"           # PowerShell, this terminal only
   python backend/server.py
   ```

   macOS/Linux: `export GEMINI_API_KEY="your-key"`. Or create a file named
   `.env` next to `requirements.txt` containing `GEMINI_API_KEY=your-key`;
   the server reads it at startup and `.gitignore` keeps it out of Git. The
   server prints `[CHATBOT] Gemini gemini-3.5-flash-lite` and warns if no key
   is set. To use Claude instead, set `CHATBOT_PROVIDER=claude` and
   `ANTHROPIC_API_KEY`.
2. Start clients as usual: `python -m frontend.ui.app --real`.
3. Without internet or a key, run `python backend/server.py --bot echo`: the bot
   then repeats each question instead of calling the AI, so the rest of the demo
   still works.

**Demo script (2 minutes):** Alice opens **🤖 Chatbot** and asks "What is TCP?",
then "And how is UDP different?" (the bot remembers the first question). Alice
and Bob join `#Study`. In `#Study`, Bob types `@`, picks **🤖 @Bot** from the
list and asks "explain sockets in one sentence"; Alice and Bob both see the
answer. While Alice has another tab open, Bob writes `@Alice can you check?`:
Alice's tab shows `@`, a yellow notification appears, and her name is
highlighted. Carol, who is not in `#Study`, receives none of these messages.

## Feature 1: AI chatbot

### What users see

- **Chatbot room:** the sidebar's **🤖 Chatbot** opens a private room. The bot's
  answers appear in green bubbles after a "Bot is typing…" row. The room takes one
  question at a time; Send waits until the answer arrives.
- **@Bot in any chat:** writing `@Bot` in a private or group chat asks the bot
  there. Its answer quotes the question and is visible to everyone in that chat,
  and only to them.
- **Terminal:** `/bot <question>` asks privately; answers print as `[bot] [Bot] ...`.

### How it works

```text
Tkinter / terminal client ──TCP: 64-byte header + JSON──▶ chat server ──HTTPS──▶ Gemini API (or Claude API)
                          ◀──────── chat_message ──────── (worker thread)  ◀──────
```

- **The server calls the AI, not the clients.** Clients keep using only the
  socket protocol (requirement R2) and need no API key or extra package; the key
  stays on one computer; and the server, which already enforces privacy, decides
  who receives each answer.
- A bot request is a normal `chat_message` with `room_type: "bot"`. The server
  echoes the question to the sender, then answers from a **separate daemon
  thread**, so a slow AI call never blocks any client's socket handler. At most
  four AI calls run at once; each user has at most one unanswered question
  (otherwise the error `bot_busy`).
- Answers are ordinary `chat_message` frames from the reserved user `Bot`, so
  replies, quoting, emoji and mentions work on them as on any message.

### Model, settings and prompt

`CHATBOT_PROVIDER` (or `--bot`) picks the AI service: `gemini` (default),
`claude`, or `echo` (offline, not AI). Everything else is the same for both.

| Setting | Gemini (default) | Claude |
|---|---|---|
| API | `generateContent` REST API over HTTPS, using Python's `urllib` (no extra package) | Messages API via the official `anthropic` SDK |
| Key | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | `ANTHROPIC_API_KEY` |
| Model (`CHATBOT_MODEL`) | `gemini-3.5-flash-lite`: stable, has a free tier, quick (minimal thinking by default) | `claude-opus-5-5` |
| Reasoning | The model's default | `effort: low` (`CHATBOT_EFFORT`: low, medium, high, xhigh, max) |
| Output limit | The model's default | `max_tokens` 16000, since thinking counts toward it |
| Declined requests | A blocked question or answer becomes "Sorry, I can't help with that request." | Same, after `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) lets the API retry on its recommended model |
| Timeout and retries | 60 s per attempt; up to 2 retries after a 5xx error | 60 s per attempt; the SDK's 2 automatic retries |

Gemini's free tier needs no payment. Its limits belong to the Google Cloud
project behind the key; AI Studio shows them at
<https://aistudio.google.com/rate-limit>. When they run out, the bot says the free
quota is used up. `CHATBOT_MODEL=gemini-3.6-flash` gives stronger but slower
answers.

Context: the chatbot room remembers the last 20 messages (10 questions and
answers) of that connection, as text, and forgets them on disconnect. An `@Bot`
question in another chat is answered on its own: the server does not store chat
history, so the bot sees only that message. Only the answer **text** is kept and
sent back; the model's thinking is never replayed, so dropping the oldest turns
cannot break it.

System prompt (`backend/chatbot.py`), followed by "You are talking with
<name> in <place>.", where the place says who can read the answer:

> You are Bot, the AI assistant built into a chat application that students made
> for a computer networks course. People talk to you in a private chatbot room, and
> they can also write @Bot in their private and group chats to ask you something there.
>
> Reply in the language of the message you are answering, for example Thai or
> English. Keep replies short and conversational, usually one to five sentences,
> unless someone asks for more detail. The chat window shows plain text only, so do
> not use Markdown: no bold, headings, tables or code fences. Simple lists that
> start with "-" are fine.
>
> In a chat between people you see only the message that mentioned you, not the
> rest of the conversation, and everyone in that chat can read your answer. If a
> question depends on earlier messages you cannot see, say so briefly. You cannot
> send messages to other users, join groups or look up who is online, so never claim
> to have done so. If you are not sure of something, say so.

### Errors and limits

| Situation | What the user sees |
|---|---|
| No API key on the server | The bot answers that the server operator must set `GEMINI_API_KEY` (`ANTHROPIC_API_KEY` for Claude) |
| `anthropic` package missing on the server (Claude only) | The bot answers with the `pip install -r requirements.txt` command |
| Free Gemini quota used up | The bot asks to try again in a minute, or tomorrow if the daily limit is reached |
| Key rejected, unknown model, rate limit, no internet, API error | A short bot answer explaining it; nothing crashes; the server logs only the error type and HTTP status |
| Request declined by the model | "Sorry, I can't help with that request." |
| A second question before the first answer | Error `bot_busy`; the desktop app keeps the draft until the answer arrives |
| Empty question or more than 4,000 characters | Error `invalid_message` |
| Username `Bot` (any capitalization) | Rejected at login: the name is reserved for the chatbot |

**Privacy:** only text written in the chatbot room, or a message that mentions
`@Bot`, is sent to the AI service. Other private and group messages never leave
the server, and the server console logs no message text. On Gemini's free tier,
Google's pricing page says the data is "used to improve our products" (the paid
tier is not), so nobody should send the bot anything private.

## Feature 2: @username mentions

### What users see

- **Highlighting:** mentioned names are blue and bold. Your own name has a yellow
  background, and the whole bubble is tinted.
- **Notifications:** when someone mentions you in a chat that is not in front
  (or while the app is in the background), the chat's sidebar row turns yellow
  with an `@` badge (`@2` for two mentions), its tab gets an orange dot and `@`
  instead of the unread dot, a bar such as `🔔 Bob mentioned you in #Study: …`
  appears with an **Open** button, and the computer beeps. Badge and dot clear
  when you open the chat. The bar closes after 8 seconds or
  when you open that chat. The terminal client prints `[MENTION] Bob mentioned you in group: Study`.
- **Autocomplete:** typing `@` lists the people who can read this chat, plus
  `🤖 @Bot`. Use Up/Down, then Enter or Tab (or click); Esc closes the list.
  The full name is inserted, so names with spaces, Thai and emoji are easy to
  mention.
- **Privacy hint:** a mention never shares a message. If you mention someone
  outside the chat, you see "Carol is not in this chat, so they will not see this
  message".

### The rule

The **server** decides who is mentioned and adds a `mentions` list of canonical
usernames to every chat message (`backend/mentions.py`); clients cannot forge it.
The UI uses the same rule only to locate the names for highlighting
(`frontend/ui/mentions.py`); a test checks both copies agree.

- `@` followed by a connected username or `Bot`, ignoring case: `@bob` mentions `Bob`.
- The longest name wins: `@Bob Smith` mentions `Bob Smith`, not `Bob`.
- `@` must start the text or follow a non-letter, so `alice@example.com`
  mentions nobody.
- A name ending in a letter, digit, Thai mark or `_` must not run into another
  such character: `@Bobby` does not mention `Bob`, while `@Bob,`, `@Bob's` and
  `@Bob😀` do.
- Mentions are metadata: they never add recipients. Mentioning someone outside a
  private or group chat neither shows them the message nor notifies them.

## Files

| File | Change |
|---|---|
| `backend/chatbot.py` | New: Gemini (default) and Claude clients, prompt, settings, error messages, offline echo provider, `.env` loading |
| `backend/mentions.py` | New: the server's mention rule |
| `backend/server.py` | `mentions` on every chat message; bot room; `@Bot` answers; worker threads; reserved name `Bot`; `--bot` option |
| `frontend/network_client.py` | Bot room enabled; server `mentions` passed to the UI |
| `frontend/client.py` | `/bot` command, bot room label, `[MENTION]` notice |
| `frontend/ui/mentions.py` | New: highlighting spans and suggestions |
| `frontend/ui/chat_room.py`, `main_window.py`, `theme.py`, `login.py`, `mock_client.py`, `net_interface.py` | Highlighting, notification bar, tab marker, autocomplete, typing indicator, privacy hint, reserved name, mock mentions, readable primary buttons on macOS |

## Tests

Run all tests with `python -m unittest discover -s tests -v`. No test uses the
network or a real key: the server runs the offline echo provider, or Gemini or
Claude against a local fake API that records each request.

| File | Covers |
|---|---|
| `tests/test_mentions.py` | Rule examples (case, longest name, Thai/emoji, emails), server/UI parity, server-derived and unforgeable `mentions`, mentions never add recipients, adapter, terminal notice |
| `tests/test_chatbot.py` | Private bot room and history, `@Bot` in groups and private chats, privacy, reserved name, validation, terminal `/bot`, exact Gemini request (path, key header, system instruction, text-only history), exact Claude request (model, effort, fallbacks), missing key, no connection, quota and API errors, blocked answers, retries, `bot_busy` |
| `tests/test_person3_ui.py` | Hidden Tk windows: highlight, `@` tab marker, notification bar, autocomplete (also Thai and emoji), privacy hint, typing indicator, one question at a time, reserved name at login |

Screenshots of each state, taken from the real app on macOS, are in
[evidence/PERSON3_VISUAL_QA.md](evidence/PERSON3_VISUAL_QA.md).

## Presentation notes: protocols (R1)

- **TCP** carries every chat and chatbot message between clients and the server,
  framed as a 64-byte length header plus UTF-8 JSON. Chat needs ordered,
  reliable delivery, so a lost or reordered question or answer is not acceptable.
- **HTTPS (HTTP over TLS over TCP)** carries the server's requests to the AI
  service: a `POST` with a JSON body to `generativelanguage.googleapis.com` for
  Gemini. TLS encrypts the API key and the question on the internet; HTTP is the
  API's interface; DNS resolves the API's host name first.
- The server is the bridge: it receives a question over the chat socket, makes an
  HTTPS request from a worker thread, and sends the answer back over the socket
  only to the people allowed to read it.
