# 2110471-Comp-Network-Term-Project

Python TCP socket chat project with a terminal client and a separate Tkinter desktop frontend.

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

This installs Flask and its dependencies. Python's `socket` module is included in Python. Tkinter normally comes with the official Windows Python installation; neither needs to be installed with pip.

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
|   `-- server.py
|-- frontend/
|   |-- client.py        # Working terminal chat client
|   `-- ui/              # Tkinter UI (currently uses a mock client)
|-- tests/
|   `-- test_chat.py     # TCP broadcast integration tests
|-- .venv/             # Local environment; excluded from Git
|-- .gitignore
|-- requirements.txt   # Shared Python dependencies
|-- project_plan.md
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

Every connected client receives every message, including its own message echoed by the server. Messages show the sender's IP address and port. Type `!DISCONNECT` or press Ctrl+C to leave.

For clients on another computer on the same network, replace the example address with the server computer's LAN IPv4 address:

```powershell
python frontend/client.py --host 192.168.1.100
```

The server listens on all IPv4 interfaces by default. If Windows prompts, allow Python through the firewall on your private network. Both commands accept `--port` (default `5050`); both sides must use the same port.

The protocol uses a 64-byte, space-padded decimal length followed by UTF-8 message bytes in both directions. Messages are limited to 1 MiB before the server adds the sender label. This is a shared chat room; private and group routing are future work. The Tkinter UI still uses its mock client and is not connected to this terminal chat implementation.

Run the loopback integration tests:

```powershell
python -m unittest discover -s tests -v
```

## Working as a team

- Share source files, `requirements.txt`, and documentation through Git.
- Each member follows these setup instructions to create their own environment.
- When dependencies are added or changed, update `requirements.txt` and commit it. Other members should rerun `python -m pip install -r requirements.txt` after pulling those changes.
- Keep `.venv`, Python cache files, and `.env` files out of Git; the project's `.gitignore` already excludes them.

To leave an activated virtual environment:

```powershell
deactivate
```
