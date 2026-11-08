# Person 4 implementation and acceptance checklist

Reviewed baseline: main commit `49860ac4344dc79075a53d0a15a98a69be42906c`.
Implementation date: 2026-11-07. The original framing and chat fields remain
supported; optional group-join event subscriptions were added.

## Current status

**Core Person 4 implementation is complete.** All 12 functional/visual cases
below have now been checked locally. The automated suite has 56 passing tests,
including 11 real Tkinter integration tests. Visible desktop checks also cover
scrolling, emoji, reply controls, and tab closing/reopening.

**Physical LAN acceptance is still one outstanding release task.** Local tests
use several clients on one computer; they do not establish results on two
physical computers. Chatbot transport and expanded mention behavior were added
afterwards by Person 3; see the end of this file.

## Implemented

- Real `NetworkClient` implementing the UI interface with bounded registration,
  background receive/write workers, a bounded outgoing queue, and clean closure.
- Unique username registration, server-confirmed names, and consistent Unicode
  validation in the login screen. Worker threads do not access Tk widgets.
- Private and group sends using explicit destinations, without relying on a
  shared selected chat. Own messages appear through the server echo only.
- UI mapping of server IDs, sender names, timestamps, reply references, and
  private participants. Private tab keys preserve spaces, hyphens, and emoji.
- Polling of online users, group discovery, and member lists of joined groups.
  Group counts and joined state are independent of whether names are available.
- Existing reply controls, local quoted-message display, missing-original
  placeholders, emoji insertion, and UTF-8 transmission connected to real TCP.
- Server-confirmed join notices in each group's chat log, including the joining
  user's own view. Repeated joins do not duplicate the notice; outsiders do not
  receive it. Notices are separate from replyable messages.
- Sending disabled after leaving; every group can be left.
- Unexpected disconnect returns to login. Intentional close is silent and
  stops workers. Real mode marks the chatbot unavailable; mock mode still works.
- README launch instructions and automated adapter/Tkinter tests.

## Bug list

| ID | Problem / reproduction | Status / owner | Retest evidence |
|---|---|---|---|
| P4-01 | Start desktop UI with `--real`: missing `network_client` import | Fixed, Person 4 | Real Tkinter login against TCP server |
| P4-02 | Private tabs split names at hyphens | Fixed, Person 4 | Private sends/replies with hyphens and emoji in both names |
| P4-03 | Login rejects server-valid spaces/emoji | Fixed, Person 4 | Canonical Unicode name and duplicate-name retry tests |
| P4-04 | UI assumes outsiders can fetch all group member names | Fixed, Person 4 | Counts available before joining; names hidden; sending locked |
| P4-05 | Online/group views never refresh from server | Fixed, Person 4 | Polling sees new connections, joins, leaves, and deleted groups |
| P4-06 | Replies to unseen originals have no visible quote indicator | Fixed, Person 4 | New member receives reply with unavailable-original placeholder |
| P4-07 | Background login worker calls Tk APIs | Fixed, Person 4 | Main-thread queue dispatch; hidden Tk tests capture callback errors |
| P4-08 | Desktop remains in chat after server shutdown | Fixed, Person 4 | Returns to login; one disconnect notification; workers exit |
| P4-09 | Closing the app twice raises a Tcl cleanup error | Fixed, Person 4 | Idempotent close exercised by GUI test cleanup |
| P4-10 | Real chatbot requests have no backend handler | Fixed, Person 3 | Server chatbot room and `@Bot`; `tests/test_chatbot.py`, `tests/test_person3_ui.py` |
| P4-11 | Existing mention matching only covers `@word` names | Fixed, Person 3 | Server-derived `mentions` for spaces, Thai, emoji, and punctuation; notifications; `tests/test_mentions.py` |
| P4-12 | Physical two-computer behavior has no recorded evidence | Pending two devices / Person 4 | Execute checklist below on the team's network |
| P4-13 | Emoji picker stays open after its chat tab closes or group is left | Fixed, Person 4 | GUI regression tests and visible tab-close check |
| P4-14 | Emoji-only messages wrap into unnecessarily narrow bubbles | Fixed, Person 4 | Font-measured bubble width; visible emoji-only row |
| P4-15 | Destroyed Tk widgets can be collected by a background thread during repeated GUI runs | Fixed, Person 4 | Login workers retain no widgets; close releases callbacks and collects destroyed widgets on Tk's thread; full 53-test run passes |

## Automated test evidence

For remote verification, the included `.github/workflows/person4-tests.yml`
runs the suite on GitHub-hosted Windows runners after a push or pull request.
It fails if GUI tests are skipped and uploads the log as an artifact. The
workflow runs when the updated files are pushed to a branch. Check the branch's
**Person 4 tests** run in the repository's Actions tab for its hosted result;
the recorded local test result does not establish a hosted CI result.

Run from the repository root:

```powershell
python -m unittest discover -s tests -v
```

The original suite covers TCP framing, permissions, identity, terminal behavior,
replies, Unicode, and disconnects. Added adapter tests use real TCP connections
and cover polling, privacy, concurrent queued sends, recovery, and fragmented
server frames. Hidden Tkinter tests connect actual widgets to the server and
exercise login, sends, replies, emoji selection, group actions, mock mode, and
disconnect recovery. GUI tests require Tkinter and an available desktop display.

The local test run is recorded in [evidence/TEST_RESULTS.txt](evidence/TEST_RESULTS.txt)
and in `TEST_RESULTS.txt` in the download delivery.
Automated tests run on one Windows computer using loopback; no physical LAN
acceptance result is claimed. The latest run has 56 tests passed, no skips.
See [local visual evidence](evidence/LOCAL_VISUAL_QA.md) for screenshots and the
observed desktop results.

## Completed local acceptance checks

These are local functional results for the same scenarios originally listed
only as unrun LAN cases. **Passed locally** means observed with the real server
on this Windows computer; physical LAN acceptance has a separate gate below.

Test names refer to [terminal/server tests](tests/test_chat.py),
[adapter tests](tests/test_network_client.py), and
[Tkinter integration tests](tests/test_ui_integration.py).

| Case | Behavior | Local result | Evidence |
|---|---|---|---|
| LAN-01 | Multiple clients register and see canonical usernames | Passed locally | `test_online_list_updates_after_connect_and_abrupt_close`; Unicode private-chat test |
| LAN-02 | Duplicate and overlength usernames are rejected; retry works | Passed locally | Registration retry tests; GUI invalid-username/port and duplicate-name tests |
| LAN-03 | Private delivery reaches both participants once and excludes outsiders | Passed locally | `test_unicode_private_messages_replies_and_own_echo_exclude_outsider`; GUI own-echo test |
| LAN-04 | Group discovery shows every group's member list (R9) while hiding messages from outsiders (R11) | Passed locally | `test_group_discovery_shows_members_but_not_messages_and_refreshes_after_leave`; GUI group privacy test |
| LAN-05 | Join enables sending; leave stops reception and locks the input | Passed locally | Adapter group test; GUI join/leave test and picker-close-on-leave regression |
| LAN-06 | Switching private/group tabs sends only to each tab's destination | Passed locally | `test_switching_private_and_group_tabs_keeps_destinations_separate` |
| LAN-07 | Reply selection, cancellation, sending, references, and quote rendering | Passed locally | `test_reply_menu_cancel_then_send_and_quote`; native context-menu/cancel check |
| LAN-08 | Thai, emoji-only text, and emoji replies survive both directions | Passed locally | `test_emoji_only_and_thai_text_round_trip_both_directions`; picker test; visible emoji row |
| LAN-09 | Concurrent messages and incoming messages while input is idle | Passed locally | Adapter concurrent-send test; terminal idle-receive test; GUI incoming-message and visible Send checks |
| LAN-10 | Client closure updates the user list; a new session can reconnect | Passed locally | Online-list, worker-close, session-reuse, and server-assigned identity tests |
| LAN-11 | Server shutdown returns the GUI to login; restarting permits chat again | Passed locally | Extended `test_duplicate_name_can_retry_and_disconnect_returns_to_login` reconnects the same GUI and sends after restart |
| LAN-12 | Long text, scrolling, emoji rendering, reply menu, and tab closing/reopening | Passed locally | GUI long-text/tab-history test plus [visible desktop evidence](evidence/LOCAL_VISUAL_QA.md) |

## Two-computer acceptance and evidence

Each computer installs Python/Tkinter and the same source revision. On computer A,
run `python backend/server.py`. Find A's LAN IPv4 address using `ipconfig`.
Start `python -m frontend.ui.app --real` on both devices. A can connect to
`127.0.0.1`; B connects to A's LAN address. Both use port `5050`. Allow Python
through A's private-network firewall. A third client, on either computer, is
needed to demonstrate exclusion from private/group conversations.

Record device/OS/Python versions, server IP and port, source revision, tester,
date, expected and actual results, and screenshots/log references for each case.
Do not mark physical acceptance passed until it was actually observed.

**Release gate LAN-PHYSICAL: Not run — requires two physical computers.** Repeat
LAN-01 through LAN-12 above on the two devices, including a third client for
privacy checks. Record both devices' results and screenshots in one acceptance
record. This is additional hardware/network validation of already implemented,
locally verified behavior, rather than 12 unfinished implementation tasks.

## Remaining dependencies

- Chatbot transport, mention behavior, and AI/prompt documentation: done by
  Person 3, see [CHATBOT_AND_MENTIONS.md](CHATBOT_AND_MENTIONS.md). A live
  chatbot demo needs `GEMINI_API_KEY` (free from Google AI Studio) on the
  server computer.
- Physical two-computer screenshots and final demo acceptance: requires the
  team's devices and LAN; the checklist is ready.
- UI screenshot selection/presentation polish: coordinate with Person 2 after
  the physical acceptance run. Local desktop screenshots are already available.
