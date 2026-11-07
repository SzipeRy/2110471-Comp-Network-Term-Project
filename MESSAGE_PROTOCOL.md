# TCP JSON message protocol

`backend/server.py`, the terminal client `frontend/client.py`, and the Tkinter adapter `frontend/network_client.py` support registered users, private conversations, and group chats. Launch the real UI with `python -m frontend.ui.app --real`; its default mode remains an offline mock demonstration.

## Framing and limits

```text
[64-byte header][UTF-8 JSON object]
```

The header is the entire encoded JSON body's byte length in decimal, padded on the right with ASCII spaces to exactly 64 bytes. The body must be a JSON object containing 1-1,048,576 bytes (1 MiB). Both sides use exact-length reads and complete writes. UTF-8 text, Thai characters, emoji, and consecutive or fragmented TCP frames are supported. Server-added metadata counts toward the limit.

Restart the server and clients together after updating. Saving a file does not reload an existing server process. `[ERROR] Expected chat_message or disconnect` during registration indicates an older running server; stop it with Ctrl+C and restart `python backend/server.py` on the server device.

## Register before chatting

```json
{"type": "register", "username": "Alice"}
```

The server trims surrounding whitespace and normalizes the name to Unicode NFC. The result must contain 1-20 printable Unicode code points (`len(name)` in Python). Empty names, embedded control characters, and the reserved name `server` are rejected. Names are unique among connected clients after `casefold()` comparison, while accepted spelling and capitalization are preserved.

The server confirms registration only to that client:

```json
{
  "type": "registered",
  "room": "lobby",
  "msg_id": "82d19a8fe94745cb9317c05d9db7f01a",
  "sender_id": "server",
  "text": "Registered as Alice",
  "reply_to": null,
  "timestamp": "2026-11-07T07:30:00.123+00:00",
  "username": "Alice"
}
```

Registration makes the client a member of the public `lobby`, but the terminal has **no selected outgoing conversation** initially. Choose a destination before typing chat text. Registration is allowed once per connection. Disconnecting releases the username and all that connection's group memberships. These are session names, not authenticated accounts; a later connection using the same name does not inherit private sessions or group memberships.

## Terminal commands

| Command | Result |
|---|---|
| `/private <username>` | Select a private conversation with another connected user. |
| `/create <group>` | Create a group, become its first member, and select it. |
| `/join <group>` | Join an existing group and select it. |
| `/group <group>` | Select a group you already belong to. |
| `/groups` or `!GROUPLIST` | List available groups, their member counts, and whether you belong to each. |
| `/members <group>` | List usernames in a group you belong to. |
| `/leave <group>` | Leave a group. If selected, clear the outgoing destination. |
| `/lobby` | Select the public lobby. Messages here are visible to all registered clients. |
| `/reply <msg_id> <text>` | Send a reply in the selected conversation. |
| `!MEMBERLIST` | List all connected, registered usernames, including yourself. |
| `!DISCONNECT` | Close the connection. |
| `/help` | Display the command guide locally. |

Names may contain spaces; the entire argument after a destination command is the name. After a successful selection, ordinary text and `/reply` use that conversation. You continue receiving messages for all groups you belong to and private messages addressed to you, with each destination labeled on screen.

The server processes commands and chat text in order on each connection. Failed `/private`, `/create`, `/join`, or `/group` requests clear the previous outgoing selection. Subsequent text is rejected until a valid destination is selected, preventing accidental delivery into a previous conversation.

## Chat JSON fields

| Field | Meaning |
|---|---|
| `type` | `"chat_message"` for chat. |
| `room_type` | `"group"` or `"private"`; `null` together with `room: null` uses the server-selected conversation. This field distinguishes destinations even if a group and user have the same name. |
| `room` | Group name for group requests; recipient username for explicit private requests. Private broadcasts instead contain the server's opaque conversation ID. |
| `msg_id` | Server-generated UUID4 hexadecimal string; client placeholder is `null`. |
| `sender_id` | Server-confirmed registered username; client placeholder is `null`. |
| `text` | Message text, including an empty string if desired. |
| `reply_to` | A recent message ID in the same conversation, or `null`. |
| `timestamp` | Server receipt time as ISO-8601 UTC with milliseconds; client placeholder is `null`. |

The server replaces any client claims about IDs, sender identity, or timestamps. Client-supplied recipient lists, participants, and extra metadata cannot grant access or alter delivery. Every authorized recipient, including the sender, receives the same broadcast object.

### Send to the selected conversation

This is how ordinary terminal text is sent:

```json
{
  "type": "chat_message",
  "room_type": null,
  "room": null,
  "msg_id": null,
  "sender_id": null,
  "text": "Hello!",
  "reply_to": null,
  "timestamp": null
}
```

If no destination is selected, the server returns `chat_not_selected`. An omitted `room` and `room_type` also means the selected destination. For compatibility, an explicit group `room` without `room_type` is treated as a group request. The Python helper `create_message(text)` still explicitly targets the public lobby by default; the terminal uses `create_message(text, room=None, room_type=None)` to follow its selected chat.

### Explicit group request

```json
{"type": "chat_message", "room_type": "group", "room": "Study", "text": "For our group", "reply_to": null}
```

The server checks that the group exists and the sender is a member, regardless of their selected chat. The output includes the eight chat fields above and the canonical group spelling.

### Explicit private request and broadcast

```json
{"type": "chat_message", "room_type": "private", "room": "Bob", "text": "For Bob only", "reply_to": null}
```

Only Alice and Bob receive:

```json
{
  "type": "chat_message",
  "room_type": "private",
  "room": "a734fd390a4f4625948700b5aeef2071",
  "msg_id": "c72b1d3f7cde4eb8af36013e4a567901",
  "sender_id": "Alice",
  "text": "For Bob only",
  "reply_to": null,
  "timestamp": "2026-11-07T07:30:01.123+00:00",
  "participants": ["Alice", "Bob"]
}
```

`participants` is server-derived and added only to private chat messages for display. The private `room` ID identifies that pair of live connections; it is not an access token. Knowing an ID does not allow an outsider to join or receive that conversation. Explicit private requests address a username, not a broadcast's opaque room ID. If the peer disconnects, the private selection is cleared. Reusing the same username requires a new selection and creates a new private session.

## Group and selection requests

All requests below require registration. Group names are NFC-normalized, trimmed, contain 1-40 printable code points, and are unique case-insensitively. The creator automatically becomes a member. Groups are open to registered users who explicitly join; no invitation or approval is required. A nonmember receives no messages or member names for the group.

```json
{"type": "create_group", "room": "Study"}
```

```json
{"type": "join_group", "room": "Study"}
```

```json
{"type": "select_chat", "room_type": "group", "room": "Study"}
```

```json
{"type": "select_chat", "room_type": "private", "room": "Bob"}
```

Successful creation, joining, or selection returns a `chat_selected` envelope only to the requester. It includes `room_type`, the canonical `room`, authorized `members`, and `action` (`create_group`, `join_group`, or `select_chat`). The terminal prints `[CHAT] Group: Study` or `[CHAT] Private chat with Bob`.

```json
{"type": "leave_group", "room": "Study"}
```

Leaving requires membership and returns `group_left` only to the requester. The public lobby cannot be left; select another destination to avoid sending there. Other empty groups are deleted. Disconnect removes membership from all groups and deletes any groups made empty. Groups and memberships are in memory and reset when the server restarts.

```json
{"type": "group_list"}
```

The `group_list` response contains a `groups` array, for example:

```json
[{"name": "Study", "joined": true, "member_count": 2}, {"name": "lobby", "joined": true, "member_count": 3}]
```

Group names and counts are discoverable so users can join existing groups. Member names and message contents are not exposed by this list.

```json
{"type": "group_members", "room": "Study"}
```

The `group_members` response includes `room` and a sorted `members` array. The requester must be a member. Only the requester receives it. Repeating a list command refreshes the snapshot; complete membership lists are not pushed automatically. Subscribed clients separately receive the group join announcements below.

## Server-wide member list

`!MEMBERLIST` sends:

```json
{"type": "member_list"}
```

Only the requester receives a `member_list` envelope with `members`, such as `["Alice", "Bob"]`. It includes the requester, preserves registered spelling, sorts by `casefold()`, and excludes unregistered connections. This public list reveals online names, not any private/group message contents. Requesting it before registration returns `registration_required`.

## Group join announcements

Clients can include `"group_events": true` in their registration request to
subscribe to group join announcements. The desktop adapter and interactive
terminal opt in. Clients omitting this option retain the original response
stream. After a successful `join_group` that adds a new member, the server sends
the normal `chat_selected` confirmation first to the joining client, then sends
this event to subscribed members of that group, including the new member:

```json
{
  "type": "group_event",
  "room_type": "group",
  "room": "Study",
  "msg_id": "server-generated-event-id",
  "sender_id": "server",
  "text": "Bob joined the group",
  "reply_to": null,
  "timestamp": "2026-11-07T07:30:01.123+00:00",
  "event": "member_joined",
  "username": "Bob"
}
```

The username and group name use server-confirmed spelling. Existing members
pressing Join again, selecting/reopening a room, group discovery, and list
refreshes do not emit events. Leaving and joining again emits a new event.
Outsiders and members who have left do not receive the event. Events are not
stored in the reply-reference index and cannot be quoted as chat messages.
The desktop maps them to non-replyable `system_message` rows in the group log.
There is no announcement history download and no new event for automatic lobby
membership during registration.

## Replies

`reply_to` must be `null` or a 1-128 character string. The server keeps the last 10,000 accepted message IDs and their conversation contexts, without storing message bodies. A reply must refer to an ID in that index and the same group instance or private session. Unknown, expired, and cross-conversation IDs all return `invalid_reply` without broadcasting the reply text. Recreating a deleted group or reconnecting to a private peer does not reuse the old context. The reply receives a new message ID.

There is no message-history download or quoted-content lookup. A new group member does not receive earlier messages. Private and group chat text is not written into the server's shared console log.

## Disconnect and errors

```json
{"type": "disconnect"}
```

Disconnect is accepted before or after registration and has no acknowledgment. Typing `!DISCONNECT`, Ctrl+C, or terminal EOF sends it before closing where possible. A literal `chat_message` with command-looking text remains ordinary text.

Errors are sent only to the requester using the standard envelope with `type: "error"`, `sender_id: "server"`, and an extra `code` field. They do not close a valid framed connection.

| Code | Meaning |
|---|---|
| `unsupported_type` | Unknown or missing request type. |
| `registration_required` | Register before chat, selection, or list/group operations. |
| `invalid_username` | Invalid or reserved name. |
| `username_taken` | Another connected user owns the name. |
| `already_registered` | Reconnect to choose a different username. |
| `invalid_group` | Invalid group name or attempt to leave the public lobby. |
| `group_exists` | The requested new group already exists. |
| `group_not_found` | The named group does not exist. |
| `not_group_member` | Group sending, selection, member listing, or leaving requires membership. |
| `invalid_recipient` | Invalid recipient name or attempt to privately chat with yourself. |
| `user_not_found` | The private recipient is not connected. |
| `unsupported_room_type` | Use `private` or `group`. |
| `chat_not_selected` | Choose a valid destination before sending implicit chat text. |
| `invalid_message` | Invalid text or reply-reference type/length. |
| `invalid_reply` | Reply ID is unavailable or belongs to another conversation. |
| `message_too_large` | The final JSON exceeds 1 MiB. |

Malformed headers, invalid lengths, invalid UTF-8/JSON, non-object JSON, and truncated frames close only the offending connection.

## Permission boundaries and UI integration

The server derives recipients from its own connection and membership registries. Private chat delivers to exactly the sender and selected peer. Group chat delivers to current members only, with membership rechecked before delivery. Membership changes serialize with sends so a client receives no further group frames after its leave confirmation. A selected destination does not grant membership; explicit JSON requests undergo the same checks as terminal commands.

These permissions govern delivery between connected clients. The transport is raw TCP, without TLS or authenticated persistent accounts. The server operator controls the server process. Group creation/joining is open, while reading and sending require membership.

The Tkinter adapter maps `msg_id` to `message_id`, `sender_id` to `sender`, and group
`room` to `room_id`. For private messages, the UI uses a JSON-encoded pair of
canonical usernames as its local tab key; the adapter constructs it from the
server-derived `participants`. Outgoing private requests address the peer's
username, never that local key or the server's opaque session ID. Server reply
validation continues to use the live conversation context.

The UI receives `GroupInfo(joined, member_count, members)` values. `members` is
`None` when names are unavailable, including groups the user has not joined.
The adapter polls `member_list` and `group_list` every two seconds, then requests
`group_members` only for joined groups. Successful create/join/leave responses
also update the local membership display. Opted-in clients additionally receive
server-pushed `group_event` join announcements; full lists still use polling.

All post-registration writes use a single background writer, and a separate
receiver performs exact-length reads and invokes callbacks. Tk widgets are
updated through the application's queue on the Tk main thread. Quotes use only
messages received in that local tab; unavailable originals have a placeholder.
The client does not manufacture IDs or display optimistic duplicates.

Chatbot integration, persistent accounts/history, and invitation-only groups
remain future work. Mention highlighting retains the existing `@word` matching;
mention behavior for usernames containing spaces or punctuation still needs
Person 3's agreed rules.
