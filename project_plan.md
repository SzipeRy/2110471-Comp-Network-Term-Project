# Computer Network Term Project Plan

## Scope

- Backend: Python
- Client frontend: Tkinter
- Transport: TCP sockets
- Required baseline: unique users, online-user list, private chat, group chat, group membership, and correct message privacy
- Additional features: Chatbot, `@username` mentions, replies, and emoji

## Team Responsibilities

### Person 1 - Server and Backend

- Build the multi-client TCP server.
- Manage usernames, connected clients, and disconnections.
- Implement private-message routing.
- Implement group creation, joining, member lists, and group routing.
- Validate permissions and message destinations.
- Write server-side tests.

### Person 2 - Tkinter Client Interface

- Build the login screen and main Tkinter window.
- Display connected users and groups.
- Build private and group chat rooms.
- Display incoming and outgoing messages.
- Add text input, send controls, and basic error messages.
- Prepare UI screenshots for the presentation.

### Person 3 - Chatbot and Mentions

- Integrate and document the AI chatbot model/API.
- Build the chatbot chat room and response display.
- Implement `@username` detection, highlighting, and notifications.
- Test mentions in private and group chats.
- Prepare the AI feature explanation and prompt/model documentation.

### Person 4 - Client Networking, Reply, Emoji, and Integration

- Build the client TCP connection and background receive loop.
- Implement JSON/message serialization and message IDs.
- Add reply-to-message and quoted-message display.
- Add the emoji picker and UTF-8 emoji handling.
- Run two-computer integration tests and maintain the bug list.
- Prepare the final test evidence and run instructions.

## Shared Message Contract

```json
{
  "type": "chat_message",
  "room_type": "private",
  "room_id": "Alice-Bob",
  "message_id": "unique-id",
  "sender": "Alice",
  "text": "@Bob Hello 😀",
  "reply_to": null,
  "mentions": ["Bob"],
  "timestamp": "ISO-8601 timestamp"
}
```

Person 1 and Person 4 must agree on this protocol before feature development begins. The server should preserve feature metadata without implementing the client UI.

## 14-Day Timeline

| Day | Person 1 | Person 2 | Person 3 | Person 4 |
|---|---|---|---|---|
| 1 | Design server and TCP protocol | Sketch UI and chat rooms | Choose AI approach; define mentions | Design client network module |
| 2 | TCP server skeleton | Tkinter application skeleton | Chatbot/mention module skeleton | TCP client and JSON framing |
| 3 | User registration and online list | Login and user-list UI | Mention detection | Receive thread and error handling |
| 4 | Private routing | Private chat room | Mention highlighting/notifications | Message IDs and timestamps |
| 5 | Group creation/list/join | Group UI | Test mentions in groups | Connect group actions to server |
| 6 | Group routing and privacy | Group chat room | Chatbot request/response design | Private/group integration tests |
| 7 | Complete baseline and server tests | Complete baseline UI | Prepare chatbot integration | Verify required features |
| 8 | Add chatbot request handler | Add chatbot chat room | Integrate AI model/API | Add chatbot message support |
| 9 | Validate chatbot requests | Improve chatbot UI | Prompts, fallback, and errors | Test chatbot over TCP |
| 10 | Preserve `reply_to` metadata | Reply display | Mentions in replies | Implement reply interaction |
| 11 | Validate UTF-8 messages | Emoji rendering | Test emoji/mention behavior | Emoji picker and sending |
| 12 | Multi-client stability tests | UI polish | AI and mention tests | End-to-end testing and bug fixes |
| 13 | Architecture/protocol slides | UI screenshots/demo flow | AI explanation and prompt | Test evidence and run guide |
| 14 | Final server fixes | Final UI fixes | Final chatbot fixes | Final two-computer test and release check |

## Milestones

- **Day 2:** Client and server connect.
- **Day 6:** Private and group chat work.
- **Day 7:** All required baseline functions are complete.
- **Day 11:** All four additional features are implemented.
- **Day 14:** Final demonstration works on two physical computers and presentation materials are ready.
