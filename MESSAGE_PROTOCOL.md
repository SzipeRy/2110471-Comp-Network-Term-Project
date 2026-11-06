# TCP JSON message protocol

`backend/server.py` and `frontend/client.py` exchange UTF-8 JSON objects. Terminal input is converted into JSON by the client; the server broadcasts JSON, and the client formats it for display.

## TCP framing

Each frame contains:

```text
[64-byte header][UTF-8 JSON body]
```

The header is the body's byte length written as decimal digits and padded on the right with ASCII spaces to exactly 64 bytes. The length counts the **entire encoded JSON object**, including its field names and metadata. It does not count the header. Each side reads exactly the header length and then exactly the advertised body length, so TCP fragmentation and consecutive frames are supported.

The JSON body must be an object and must contain between 1 and 1,048,576 bytes (1 MiB). The limit applies in both directions. The server may reject a request near this limit if adding its metadata would make the broadcast too large. JSON is serialized with `ensure_ascii=False`, preserving Thai text and emoji as UTF-8.

This protocol replaces the earlier plain-text protocol and now requires username registration. Restart the server and all clients together after updating; older clients that skip registration cannot participate in chat.

If entering a username produces `[ERROR] Expected chat_message or disconnect`, the running server is an older version that does not recognize `register`. Saving the updated file does not reload an existing server process. Stop the server with Ctrl+C, run `python backend/server.py` again, and reconnect the clients. For a server on another device, update and restart the server on that device. Updated clients report this version mismatch directly instead of asking for another username.

## Username registration before joining

A newly connected client must choose a username before sending or receiving lobby chat. The terminal prompts for a name, or accepts `--username Alice` on the command line. A rejected name can be corrected on the same connection.

Client request:

```json
{"type": "register", "username": "Alice"}
```

The server trims surrounding whitespace and applies Unicode NFC normalization. The resulting name must have 1-20 Unicode code points (`len(name)` in Python) and contain only printable characters. This counts characters rather than UTF-8 bytes; some combined emoji and written characters contain multiple code points. Spaces inside a name are allowed; embedded newlines, tabs, and other non-printable characters are rejected. `server` is reserved for server responses.

Names must be unique among connected, registered clients, compared with `casefold()` after normalization. For example, `Alice` and `alice` cannot be registered at the same time. The server preserves the accepted spelling and capitalization for display.

Server confirmation, sent only to the registering client and before any lobby messages:

```json
{
  "type": "registered",
  "room": "lobby",
  "msg_id": "82d19a8fe94745cb9317c05d9db7f01a",
  "sender_id": "server",
  "text": "Joined the lobby as Alice",
  "reply_to": null,
  "timestamp": "2026-11-07T07:30:00.123+00:00",
  "username": "Alice"
}
```

`username` is an additional field for registration requests and confirmations. The terminal waits for this confirmation before starting its chat receive loop. Registration is allowed once per connection; reconnect to choose a different name. Names are released on disconnect, including an abrupt connection close. Names are session display identities, not authenticated accounts, and may be reused after the previous client disconnects.

## Chat message fields

| Field | JSON type | Meaning |
|---|---|---|
| `type` | string | `"chat_message"` for a chat request or broadcast. |
| `room` | string | Destination room. Currently only `"lobby"` is supported. All registered clients belong to this shared room. |
| `msg_id` | string in broadcasts; null in client requests | Server-generated UUID4 in 32-character hexadecimal form. Identifies this message, including when another message replies to it. |
| `sender_id` | string in broadcasts; null in client requests | The registered username, taken from the server's connection registry. Every recipient, including the sender, sees the same accepted name. |
| `text` | string | Message content. Empty strings, line breaks, Thai characters, and emoji are supported. |
| `reply_to` | string or null | The `msg_id` being replied to, or `null` for a normal message. A supplied ID must contain 1–128 characters. |
| `timestamp` | string in broadcasts; null in client requests | Server receipt time as an ISO-8601 UTC timestamp with milliseconds and the `+00:00` offset. |

The client helper always builds all seven fields. A raw chat request must contain `type` and `text`; omitted `room` defaults to `"lobby"`, and omitted `reply_to` defaults to `null`.

The server generates `msg_id` and `timestamp`, and sets `sender_id` to the connection's registered username. Values supplied by the client for these fields are ignored and replaced, so a chat message cannot claim another user's name. Extra request fields are not forwarded. The server constructs one broadcast object and sends the same object to every registered client, including the sender; the client displays its own message from that echo.

### Client → server

```json
{
  "type": "chat_message",
  "room": "lobby",
  "msg_id": null,
  "sender_id": null,
  "text": "Hello everyone!",
  "reply_to": null,
  "timestamp": null
}
```

### Server → all clients

```json
{
  "type": "chat_message",
  "room": "lobby",
  "msg_id": "c72b1d3f7cde4eb8af36013e4a567901",
  "sender_id": "Alice",
  "text": "Hello everyone!",
  "reply_to": null,
  "timestamp": "2026-11-06T07:30:00.123+00:00"
}
```

## Replies

The terminal shows each received message's ID. Reply with:

```text
/reply c72b1d3f7cde4eb8af36013e4a567901 Hello back!
```

The client places that ID in `reply_to`. The server preserves the reference and assigns the reply its own new `msg_id`. Replies remain visible to everyone in the lobby; replying does not change the destination.

The networking API can also send a reply:

```python
send(conn, create_message("Hello back!", reply_to=original_msg_id))
```

The server does not store message history or verify that a referenced ID exists. `reply_to` currently carries the relationship; quoting the original content or looking up older messages requires future history/UI support.

## Disconnect

Typing `!DISCONNECT`, pressing Ctrl+C, or reaching terminal input EOF sends this control object before the client closes:

```json
{"type": "disconnect"}
```

Only the `type` field is required for this control message, which is also accepted before registration. It is not broadcast and receives no acknowledgment. The server closes the connection and releases the username for reuse. An ordinary `chat_message` whose `text` happens to equal `"!DISCONNECT"` remains a chat message.

## Error responses

For a complete JSON object with an unsupported operation or invalid chat fields, the server sends an error only to the requesting client and keeps that connection available for subsequent requests:

```json
{
  "type": "error",
  "room": "lobby",
  "msg_id": "82d19a8fe94745cb9317c05d9db7f01a",
  "sender_id": "server",
  "text": "Only the lobby room is available",
  "reply_to": null,
  "timestamp": "2026-11-06T07:30:01.456+00:00",
  "code": "unsupported_room"
}
```

`code` is an extra field on error responses. It provides a stable machine-readable reason:

| Code | Meaning |
|---|---|
| `unsupported_type` | The request type is missing or is not `register`, `chat_message`, or `disconnect`. |
| `registration_required` | The connection must register a username before sending chat messages. |
| `invalid_username` | The name is not text, is empty, exceeds 20 code points after normalization, contains non-printable characters, or is reserved. |
| `username_taken` | A connected client already owns the name (case-insensitive). |
| `already_registered` | The connection already registered a name; reconnect to choose another. |
| `unsupported_room` | The requested room is not `lobby`. |
| `invalid_message` | `text` or `reply_to` has an invalid type or value. |
| `message_too_large` | Server metadata would make the outgoing JSON body exceed 1 MiB. |

Malformed headers, invalid lengths, invalid UTF-8/JSON, non-object JSON, truncated frames, and closed connections cause that client's connection to close. Other clients continue operating. A client rejects an oversized outgoing JSON body locally before sending it.

## Current scope and UI mapping

The `room` field prepares the protocol for group routing. Group creation, joining specific groups, membership lists, private routing, and persistent history are not implemented yet. Requests for other rooms are rejected rather than broadcast to the lobby.

The separate Tkinter UI still uses its mock client. Its existing contract uses `room_type`, `room_id`, `message_id`, and `sender`; this wire protocol uses the requested `room`, `msg_id`, and `sender_id`. Future real-client integration must map these fields (for example, `room` → `room_id`, `msg_id` → `message_id`, and `sender_id` → `sender`) and supply the UI's room type.
