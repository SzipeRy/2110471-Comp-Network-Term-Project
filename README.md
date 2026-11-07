# 2110471-Comp-Network-Term-Project

Python TCP socket chat project with a terminal client and a separate Tkinter desktop frontend.

See [CHANGE_SUMMARY.md](CHANGE_SUMMARY.md) for the desktop networking features
implemented in this branch, validation results, and work that remains blocked
or requires physical two-computer acceptance.

## Prerequisites

- Python 3.10 or newer (the setup has been verified with Python 3.14).
- Git, if you are cloning the repository.
- An editor such as VS Code.

The instructions below use Windows PowerShell. Run the commands in the project directory containing `requirements.txt`, `backend`, and `frontend`.

## 1. Get the project

Clone the team's repository or download and extract it. Open the `2110471-Comp-Network-Term-Project` directory in your editor, then open a terminal in that directory.

Check that Python is available:

```powershell
python --version
```

## 2. Create your virtual environment

Each team member must create their own `.venv` on their computer:

```powershell
python -m venv .venv
```

`.venv` is a directory containing the project's Python environment and installed packages. It is specific to your computer and is excluded from Git. Do not copy another member's `.venv` or commit it.

## 3. Activate the environment

```powershell
.\.venv\Scripts\Activate.ps1
```

Your terminal prompt should now show `(.venv)`. Activate it again whenever you open a new terminal to work on the project.

If PowerShell blocks the activation script, you can use the environment without activation by calling its Python executable directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

With this approach, replace `python` in the remaining commands with `.\.venv\Scripts\python.exe`.

## 4. Install dependencies

With the environment activated:

```powershell
python -m pip install -r requirements.txt
```

This installs Flask, the Anthropic SDK (used only when the server's AI chatbot runs on Claude), and their dependencies. Python's `socket` module is included in Python. Tkinter normally comes with the official Windows Python installation; neither needs to be installed with pip.

## 5. Verify Flask and Tkinter

Check Flask:

```powershell
python -m flask --version
```

Check Tkinter:

```powershell
python -m tkinter
```

The Tkinter command should open a small demonstration window. Close it when finished. If Tkinter is missing, modify or reinstall Python with the **tcl/tk and IDLE** component enabled.

## 6. Select the interpreter in VS Code

1. Press `Ctrl+Shift+P`.
2. Choose **Python: Select Interpreter**.
3. Select this project's `.venv\Scripts\python.exe`. If it is not listed, choose **Enter interpreter path** and locate that file.

## Project structure

```text
2110471-Comp-Network-Term-Project/
|-- backend/
|   |-- server.py
|   |-- chatbot.py       # AI chatbot (Gemini or Claude API), called by the server
|   `-- mentions.py      # @username rule
|-- frontend/
|   |-- client.py        # Working terminal chat client
|   |-- network_client.py # Real Tkinter TCP adapter
|   `-- ui/              # Tkinter UI with real and mock modes
|-- tests/
|   `-- test_chat.py     # TCP chat, routing, and permission tests
|-- .venv/             # Local environment; excluded from Git
|-- .gitignore
|-- requirements.txt   # Shared Python dependencies
|-- project_plan.md
|-- MESSAGE_PROTOCOL.md # JSON fields and TCP framing
|-- CHATBOT_AND_MENTIONS.md # AI chatbot and @mention features
`-- README.md
```

## Run the terminal chat

Start the server in one terminal:

```powershell
python backend/server.py
```

Open two or more additional terminals and run this command in each:

```powershell
python frontend/client.py
```

Each client is prompted to choose a username before chatting. Names must contain 1-20 printable characters after surrounding whitespace is trimmed and Unicode is normalized. Names must be unique among connected clients (case-insensitive); invalid or taken names prompt you to choose again. The name `server` is reserved. Thai text and emoji are supported; the length is measured in Unicode code points rather than UTF-8 bytes.

You can also supply a name directly:

```powershell
python frontend/client.py --username Alice
```

After registration, choose a private conversation or group before sending text. The terminal prints the command guide, which you can display again with `/help`.

| Command | Action |
|---|---|
| `/private Bob` | Enter a private chat with connected user Bob. |
| `/create Study` | Create a group, join it, and enter it. |
| `/join Study` | Join and enter an existing group. |
| `/group Study` | Enter a group you already belong to. |
| `/groups` or `!GROUPLIST` | Show available groups and mark groups you have joined. |
| `/members Study` | Show members of a group you belong to. |
| `/leave Study` | Leave a group and stop receiving its messages. |
| `/lobby` | Enter the public lobby, visible to every registered user. |
| `/reply <msg_id> <text>` | Reply to a recent message in the selected conversation. |
| `/bot <question>` | Ask the AI chatbot privately. Write `@Bot` in a chat to ask it there. |
| `!DISCONNECT` | Disconnect. |

For example, Alice types `/create Study`, Bob types `/join Study`, and they can then exchange ordinary text. Carol receives none of those messages until she explicitly joins Study. Alice can switch to `/private Bob` for messages delivered only to Alice and Bob, then `/group Study` to return to the group. Names with spaces are supported: `/private Bob Smith` or `/create Study Team`.

Every authorized recipient, including the sender, sees the same server-confirmed sender name, destination, and message ID. You receive messages for all groups you belong to, even while a different chat is selected. A failed destination change clears the outgoing selection, so subsequent text cannot accidentally go to your previous chat. Private and group messages are never broadcast to outsiders; the server checks permissions on every request. Groups are open to registered users who explicitly join, without invitations.

Reconnect to choose a different username. Disconnecting releases the name and all group memberships; empty groups are deleted. Names and groups are session state and reset when the server restarts.

Type `!MEMBERLIST` to see the currently connected, registered usernames, including your own. The server sends the sorted list only to you. Run the command again to refresh it after someone joins or disconnects. Connections that have not registered a username are excluded.

For clients on another computer on the same network, replace the example address with the server computer's LAN IPv4 address:

```powershell
python frontend/client.py --host 192.168.1.100
```

The server listens on all IPv4 interfaces by default. If Windows prompts, allow Python through the firewall on your private network. Both commands accept `--port` (default `5050`); both sides must use the same port.

The protocol uses a 64-byte, space-padded decimal length followed by a UTF-8 JSON object in both directions. The entire JSON body is limited to 1 MiB. Chat messages contain `type`, `room_type`, `room`, `msg_id`, `sender_id`, `text`, `reply_to`, and `timestamp`; private broadcasts also contain server-derived `participants`. The server assigns identity, message IDs, UTC timestamps, and permitted recipients. Replies must reference a recent message in the same conversation. See [MESSAGE_PROTOCOL.md](MESSAGE_PROTOCOL.md) for the complete JSON contract, control requests, and permission rules. Restart both server and clients after updating.

Private and group routing work in both the terminal client and the real Tkinter frontend.

## Run the desktop chat

Start the server from the repository root:

```powershell
python backend/server.py
```

In a separate terminal, from the same repository root:

```powershell
python -m frontend.ui.app --real
```

Enter `127.0.0.1`, port `5050`, and your username for same-computer testing.
On another computer, enter the server computer's LAN IPv4 address instead. Each
computer needs its own Python environment and the same project version. Allow
Python through the server's private-network firewall when prompted.

Click an online user to open a private tab. Use **+ New / join group** to create
or join groups, then click a group in the sidebar. The public `lobby` includes
every registered user. Group member names are shown only after joining; outsiders
see the group name and member count. Online users, group discovery, and joined
group membership refresh approximately every two seconds.

When someone joins a group, its members see a system message such as **Bob joined
the group** inside that group's chat. The new member sees it too. Clicking Join
again or reopening a tab does not repeat it. Restart the server and clients
after installing this update so group join announcements are supported.

Right-click a message and choose **Reply**; press the reply bar's **X** to cancel.
Use the emoji button to insert an emoji at the input cursor, then press **Send**
or Enter. Messages appear when echoed by the server. If a referenced message was
sent before you joined, its quote reads **Original message unavailable**.

Leaving a group disables sending there. Closing a tab preserves its local
messages and does not leave the group. Closing the application disconnects;
reconnecting starts a new session without earlier message history. If the server
disconnects, the application returns to login.

Type `@` to mention someone: a list of the chat's members (and `🤖 @Bot`)
appears; pick with Up/Down and Enter, Tab, or a click. A mentioned user sees
their name highlighted, an `@` badge on the chat in the sidebar and on its tab,
and a notification bar with **Open**. Click **🤖 Chatbot** in the sidebar for a private AI chat, or write
`@Bot` in any chat to let everyone there see the answer.

For an offline UI demonstration with simulated messages:

```powershell
python -m frontend.ui.app
```

The older launch form, `python -m ui.app --real` from `frontend/`, also works.
See [PERSON4_STATUS.md](PERSON4_STATUS.md) for the bug list, test evidence, and
the remaining two-computer acceptance checklist.

### Set up the AI chatbot

The chatbot uses Google's Gemini API by default, and only the server computer
needs a key. Create a free key at <https://aistudio.google.com/apikey>: sign in
with a Google account, accept the terms, and copy the key. Before starting the
server:

```powershell
$env:GEMINI_API_KEY = "your-key"
python backend/server.py
```

On macOS or Linux use `export GEMINI_API_KEY="your-key"`. Alternatively, put
`GEMINI_API_KEY=your-key` in a `.env` file in this folder (Git ignores it). The
server then prints `[CHATBOT] Gemini gemini-3.5-flash-lite`. On the free tier,
Google may use what is sent to the bot to improve its products, so do not send
the bot anything private.

To use Claude instead, set `CHATBOT_PROVIDER=claude` and `ANTHROPIC_API_KEY`.
Without a key the chat still works and the bot explains how to configure it. For
an offline demonstration, `python backend/server.py --bot echo` makes the bot
repeat each question instead of calling the AI. See
[CHATBOT_AND_MENTIONS.md](CHATBOT_AND_MENTIONS.md) for the models, prompt,
settings, and privacy notes.

## Check the project without running Python on your computer

Commit the source files, including `.github/`, to a GitHub branch. The **Person 4
tests** workflow runs automatically on pushes and pull requests using a
GitHub-hosted Windows computer and Python 3.14. Open the repository's **Actions**
tab, select the latest **Person 4 tests** run, and inspect the **chat-tests** job.
The summary reports test counts; the **person4-test-results** artifact contains
the detailed log. Skipped GUI tests count as a failure, so a green run includes
actual Tkinter checks. The workflow also supports manual dispatch once it is on
the repository's default branch.

This checks behavior in GitHub's environment. It does not publish a clickable
browser version of the Tkinter desktop UI or replace physical two-computer LAN
acceptance. For a visual review without running anything, open
`evidence/LOCAL_VISUAL_QA.md` and its screenshots, and
`evidence/PERSON3_VISUAL_QA.md` for the chatbot and mentions.

Run the loopback integration tests:

```powershell
python -m unittest discover -s tests -v
```

The suite includes terminal/server tests, real network-adapter tests, hidden
Tkinter integration tests, and chatbot/mention tests that use an offline bot or
a local fake of the Gemini or Claude API (no key or internet needed). The GUI tests require Tkinter and an available desktop
display; they are skipped if a Tk display cannot be initialized. They do not
replace acceptance testing on two physical computers.

## Working as a team

- Share source files, `requirements.txt`, and documentation through Git.
- Each member follows these setup instructions to create their own environment.
- When dependencies are added or changed, update `requirements.txt` and commit it. Other members should rerun `python -m pip install -r requirements.txt` after pulling those changes.
- Keep `.venv`, Python cache files, and `.env` files out of Git; the project's `.gitignore` already excludes them.

To leave an activated virtual environment:

```powershell
deactivate
```
