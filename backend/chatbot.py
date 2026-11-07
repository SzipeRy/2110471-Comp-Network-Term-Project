"""AI chatbot used by backend/server.py (Person 3).

Clients reach the bot only through the chat server's TCP socket. The server calls
Chatbot.reply() from a worker thread, so a slow answer never blocks a socket
handler, and only the server talks to the AI service (HTTPS). Clients need no key.

Configuration, from environment variables or a .env file next to requirements.txt:
  CHATBOT_PROVIDER   "gemini" (default), "claude", or "echo" (offline replies for tests/demos).
  GEMINI_API_KEY     Gemini API key from Google AI Studio (GOOGLE_API_KEY also works).
  ANTHROPIC_API_KEY  Claude API key, for CHATBOT_PROVIDER=claude.
  CHATBOT_MODEL      Model ID (default gemini-3.5-flash-lite, or claude-opus-5-5 for Claude).
  CHATBOT_EFFORT     Claude only: low (default, quickest replies), medium, high, xhigh or max.
Keys are needed on the server computer only.
"""
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BOT_NAME = "Bot"            # reserved username; write @Bot to ask in any chat
BOT_ROOM = "chatbot"        # room of each user's private chatbot conversation
PROVIDERS = ("gemini", "claude", "echo")
DEFAULT_PROVIDER = "gemini"
DEFAULT_MODELS = {"gemini": "gemini-3.5-flash-lite", "claude": "claude-opus-5-5"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = "low"      # chat answers should arrive quickly
MAX_TOKENS = 16000          # Claude: thinking counts toward this limit, so leave room for it
MAX_HISTORY_MESSAGES = 20   # per chatbot room: the last 10 questions and answers
MAX_QUESTION_CHARS = 4000
MAX_ANSWER_CHARS = 20000    # keeps every answer far below the 1 MiB frame limit
GEMINI_URL = "https://generativelanguage.googleapis.com"
GEMINI_BLOCKED = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
TIMEOUT = 60                # seconds per attempt

SYSTEM_PROMPT = """\
You are Bot, the AI assistant built into a chat application that students made \
for a computer networks course. People talk to you in a private chatbot room, and \
they can also write @Bot in their private and group chats to ask you something there.

Reply in the language of the message you are answering, for example Thai or \
English. Keep replies short and conversational, usually one to five sentences, \
unless someone asks for more detail. The chat window shows plain text only, so do \
not use Markdown: no bold, headings, tables or code fences. Simple lists that \
start with "-" are fine.

In a chat between people you see only the message that mentioned you, not the \
rest of the conversation, and everyone in that chat can read your answer. If a \
question depends on earlier messages you cannot see, say so briefly. You cannot \
send messages to other users, join groups or look up who is online, so never claim \
to have done so. If you are not sure of something, say so."""

REFUSED = "Sorry, I can't help with that request."
NOT_CONFIGURED = ("The AI chatbot is not set up on this server yet. The server operator "
                  "needs to set ANTHROPIC_API_KEY and restart the server.")
NOT_CONFIGURED_GEMINI = ("The AI chatbot is not set up on this server yet. The server operator "
                         "needs to set GEMINI_API_KEY and restart the server.")
MISSING_PACKAGE = ("The chat server is missing the anthropic package. The server operator "
                   "needs to run: python -m pip install -r requirements.txt")
MODEL_NOT_FOUND = ("The configured AI model was not found. "
                   "The server operator needs to check CHATBOT_MODEL.")
TOO_MANY = "The AI service is receiving too many requests. Please try again in a minute."
UNREACHABLE = "The chat server could not reach the AI service. Please try again shortly."
SERVICE_ERROR = "The AI service returned an error. Please try again shortly."
EMPTY = "(The AI returned an empty answer.)"
FAILED = "Sorry, the chatbot ran into a problem. Please try again."


def load_env_file(path):
    """Read KEY=VALUE lines from a .env file without overriding variables already set."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        key, sep, value = line.strip().partition("=")
        key = key.removeprefix("export ").strip()
        if sep and key and not key.startswith("#") and key not in os.environ:
            os.environ[key] = value.strip().strip("'\"")


def gemini_key():
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


class GeminiError(Exception):
    """An error answer from the Gemini API; code None means no API key is set."""

    def __init__(self, code=None, status="", message=""):
        super().__init__(f"{code} {status}".strip())
        self.code, self.status, self.message = code, status, message

    def explanation(self):
        if self.code is None:
            return NOT_CONFIGURED_GEMINI
        if self.code in (401, 403) or "API_KEY" in self.message or "API key" in self.message:
            return ("The server's Gemini API key was rejected. "
                    "The server operator needs to check GEMINI_API_KEY.")
        if self.code == 404:
            return MODEL_NOT_FOUND
        if self.code == 429:
            return ("The AI service's free quota is used up for now. Please try again in a "
                    "minute, or tomorrow if today's limit is reached.")
        return SERVICE_ERROR if self.code >= 500 else FAILED


class Chatbot:
    def __init__(self, provider=DEFAULT_PROVIDER, model=None, effort=None):
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown chatbot provider {provider!r}; choose one of: {', '.join(PROVIDERS)}")
        self.provider = provider
        self.model = model or os.environ.get("CHATBOT_MODEL") or DEFAULT_MODELS.get(provider)
        self.effort = effort or os.environ.get("CHATBOT_EFFORT") or DEFAULT_EFFORT
        if self.effort not in EFFORTS:
            raise ValueError(f"CHATBOT_EFFORT must be one of: {', '.join(EFFORTS)}")
        self._lock = threading.Lock()
        self._client = None
        self._anthropic = None

    def describe(self):
        if self.provider == "echo":
            return "echo provider: offline test replies, no AI"
        if self.provider == "gemini":
            text = f"Gemini {self.model}"
            if not gemini_key():
                text += "; warning: GEMINI_API_KEY is not set"
            return text
        text = f"Claude {self.model} (effort {self.effort})"
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            text += "; warning: ANTHROPIC_API_KEY is not set"
        return text

    def reply(self, conversation, user, place):
        """Answer the last user message. Returns (text, ok) and never raises.

        conversation alternates {"role": "user"|"assistant", "content": text} and
        ends with the question. Failures come back as a chat-friendly explanation.
        """
        try:
            if self.provider == "echo":
                turn = sum(1 for message in conversation if message["role"] == "user")
                return f"Echo #{turn} for {user} in {place}: {conversation[-1]['content']}", True
            system = f"{SYSTEM_PROMPT}\n\nYou are talking with {user} in {place}."
            ask = self._ask_gemini if self.provider == "gemini" else self._ask_claude
            return ask(system, conversation), True
        except Exception as exc:  # the user always gets an answer, never a hung chat
            return self._explain(exc), False

    # ---------- Gemini: one HTTPS request to the generateContent REST API ----------
    def _ask_gemini(self, system, conversation):
        key = gemini_key()
        if not key:
            raise GeminiError()
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "model" if message["role"] == "assistant" else "user",
                          "parts": [{"text": message["content"]}]} for message in conversation],
        }
        base = os.environ.get("GEMINI_BASE_URL", GEMINI_URL).rstrip("/")
        request = urllib.request.Request(
            f"{base}/v1beta/models/{urllib.parse.quote(self.model)}:generateContent",
            data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": key})
        for attempt in range(3):  # Google sometimes answers 503 while a model is busy
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                if exc.code < 500 or attempt == 2:
                    raise self._gemini_error(exc) from None
                time.sleep(1 + attempt)
        candidates = data.get("candidates") or []
        if not candidates:  # the question itself was blocked
            return REFUSED if (data.get("promptFeedback") or {}).get("blockReason") else EMPTY
        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        # Thought summaries (if any) are not shown; the chat keeps the answer text only.
        text = "".join(part.get("text", "") for part in parts if not part.get("thought")).strip()
        reason = candidate.get("finishReason")
        if not text:
            return REFUSED if reason in GEMINI_BLOCKED else EMPTY
        if reason == "MAX_TOKENS":
            text += " …(answer cut off)"
        return text

    @staticmethod
    def _gemini_error(exc):
        try:
            error = json.loads(exc.read().decode("utf-8")).get("error") or {}
        except (OSError, ValueError, AttributeError):
            error = {}
        details = json.dumps(error.get("details") or [])
        return GeminiError(exc.code, error.get("status", ""), f"{error.get('message', '')} {details}")

    # ---------- Claude: the official anthropic SDK ----------
    def _claude(self):
        with self._lock:
            if self._client is None:
                import anthropic  # first use only: the server starts quickly without it
                self._anthropic = anthropic
                self._client = anthropic.Anthropic(timeout=float(TIMEOUT), max_retries=2)
            return self._client

    def _ask_claude(self, system, conversation):
        response = self._claude().beta.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=conversation,
            output_config={"effort": self.effort},
            # If a safety classifier declines, the API retries on its recommended model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            return REFUSED
        # Thinking blocks come back empty by default; the chat shows and keeps text only.
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if response.stop_reason == "max_tokens":
            text += " …(answer cut off)"
        return text or EMPTY

    def _explain(self, exc):
        # Log the error type (and HTTP status) only: questions and answers stay out of the console.
        detail = f" {exc}" if isinstance(exc, GeminiError) and exc.code else ""
        print(f"[BOT ERROR] {type(exc).__name__}{detail}", flush=True)
        if isinstance(exc, GeminiError):
            return exc.explanation()
        if self.provider == "gemini" and isinstance(exc, OSError):  # no connection or timeout
            return UNREACHABLE
        if isinstance(exc, ImportError):
            return MISSING_PACKAGE
        if isinstance(exc, TypeError) and "authentication" in str(exc):
            return NOT_CONFIGURED  # the SDK found no API key or other credentials
        api = self._anthropic
        if api is None:
            return FAILED
        explanations = [
            (getattr(api, "CredentialsError", ()), NOT_CONFIGURED),
            (api.AuthenticationError, "The server's Claude API key was rejected. "
                                      "The server operator needs to check ANTHROPIC_API_KEY."),
            (api.PermissionDeniedError, "The server's Claude API key is not allowed to use this model."),
            (api.NotFoundError, MODEL_NOT_FOUND),
            (api.RateLimitError, TOO_MANY),
            (api.APIConnectionError, UNREACHABLE),
            (api.APIStatusError, SERVICE_ERROR),
        ]
        return next((text for kind, text in explanations if isinstance(exc, kind)), FAILED)
