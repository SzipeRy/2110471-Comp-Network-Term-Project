"""@username mentions (Person 3). The server alone decides who a message mentions.

The rule, shared with frontend/ui/mentions.py and documented in MESSAGE_PROTOCOL.md:

- A mention is "@" followed by a connected username or "Bot", ignoring case.
- "@" must start the text or follow a character that cannot be part of a name,
  so "alice@example.com" mentions nobody.
- The longest matching name wins: "@Bob Smith" mentions "Bob Smith", not "Bob".
- A name ending in a letter, digit, combining mark or "_" must not run straight
  into another such character: "@Bobby" does not mention "Bob", while "@Bob,",
  "@Bob's" and "@Bob😀" do.

Mentions are metadata only: they never add recipients to a private or group chat.
"""
import unicodedata


def is_name_char(char):
    """Letters, digits, underscore and combining marks such as Thai vowels and tones."""
    return char.isalnum() or char == "_" or unicodedata.category(char).startswith("M")


def mention_spans(text, names):
    """Yield (start, end, name) for each mention of one of names, from left to right."""
    candidates = sorted({name for name in names if name}, key=lambda name: (-len(name), name.casefold()))
    folded = [(name, name.casefold()) for name in candidates]
    at = text.find("@")
    while at != -1:
        span = None
        if at == 0 or not is_name_char(text[at - 1]):
            for name, key in folded:
                end = at + 1 + len(name)
                runs_on = end < len(text) and is_name_char(name[-1]) and is_name_char(text[end])
                if text[at + 1:end].casefold() == key and not runs_on:
                    span = (at, end, name)
                    break
        if span:
            yield span
        at = text.find("@", span[1] if span else at + 1)


def find_mentions(text, names):
    """Canonical names mentioned in text, each once, sorted case-insensitively."""
    found = {name for _, _, name in mention_spans(unicodedata.normalize("NFC", text), names)}
    return sorted(found, key=str.casefold)
