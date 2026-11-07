# Tkinter networking, replies, emoji, and integration tests

The desktop UI can now communicate with the existing TCP server through a real
client adapter. Run one server and launch a separate desktop process for each
client using `python -m frontend.ui.app --real`.

## Done

- Background TCP receive/write workers, registration, error handling, bounded
  outgoing requests, and clean disconnect/reconnect behavior.
- Private and group messaging connected to the desktop UI with server-confirmed
  message IDs, sender names, timestamps, and own-message echoes.
- Online-user and group refresh, group create/join/leave, and member names shown
  only for groups the client has joined.
- Reply selection/cancellation, quote display, and unavailable-original fallback.
- Server-confirmed group join announcements in the chat log, delivered only to
  group members, without duplicate notices for repeated joins or room selection.
- Emoji picker and UTF-8 Thai/emoji handling, including emoji-only bubble sizing
  and popup cleanup when closing a tab or leaving a group.
- Unicode username validation and private conversation keys that preserve spaces
  and punctuation.
- Terminal, network-adapter, and Tkinter integration coverage: 56 tests passed
  locally on Windows/Python 3.14.5; native desktop checks and screenshots included.
- GitHub Actions workflow that runs the suite on a hosted Windows runner,
  rejects skipped GUI tests, and uploads a detailed test log.
- Updated setup/run instructions, bug list, acceptance checklist, and evidence.

## Not done / blocked

- **Physical two-computer LAN acceptance:** not run. Repeat the documented cases
  on the team's two devices, including a third client for privacy checks, and
  record the actual network/device evidence.
- **Real chatbot transport and AI integration, expanded mentions:** since done
  by Person 3; see [CHATBOT_AND_MENTIONS.md](CHATBOT_AND_MENTIONS.md).
- **Final presentation:** Person 2 still needs to select final UI/demo screenshots;
  local visual evidence is available, with LAN demo evidence still outstanding.

## Validation and evidence

- Local suite: `python -m unittest discover -s tests -v` — 56 passed, no skips.
- Hosted CI: see this branch's **Person 4 tests** run in the repository's Actions
  tab; local results do not establish the outcome of the hosted run.
- [Recorded local test results](evidence/TEST_RESULTS.txt).
- [Local visual checks and screenshots](evidence/LOCAL_VISUAL_QA.md).
- [Detailed Person 4 status and acceptance cases](PERSON4_STATUS.md).

The original framing and chat contract remain supported. Join announcements add
an optional `group_events` registration flag and a `group_event` envelope, while
clients omitting the flag retain their previous response stream. This branch
does not add authenticated accounts, TLS, or persistent message history.
