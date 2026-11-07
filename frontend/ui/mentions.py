"""@username helpers for the Tkinter UI (Person 3).

The server decides who a message mentions and sends the canonical names in the
message's "mentions" list. The UI uses the same rule (backend/mentions.py, see
MESSAGE_PROTOCOL.md) only to find where those names appear, for highlighting,
and to suggest names while typing. tests/test_mentions.py checks both copies agree.
"""
import unicodedata

MAX_NAME_LENGTH = 20
MAX_SUGGESTIONS = 6


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


def split_mentions(text, names):
    """Split text into [(part, mentioned name or None)] for highlighting."""
    parts, last = [], 0
    for start, end, name in mention_spans(text, names):
        if start > last:
            parts.append((text[last:start], None))
        parts.append((text[start:end], name))
        last = end
    if last < len(text):
        parts.append((text[last:], None))
    return parts


def mention_query(before_cursor):
    """(index of "@", partial name) while the user is typing a mention, else None."""
    at = before_cursor.rfind("@")
    if at == -1 or (at > 0 and is_name_char(before_cursor[at - 1])):
        return None
    query = before_cursor[at + 1:]
    return (at, query) if len(query) <= MAX_NAME_LENGTH else None


def suggest(query, candidates):
    """Names starting with query (ignoring case), or [] once the only match is typed in full."""
    key = query.casefold()
    names = sorted({name for name in candidates if name.casefold().startswith(key)}, key=str.casefold)
    if len(names) == 1 and names[0].casefold() == key:
        return []
    return names[:MAX_SUGGESTIONS]
