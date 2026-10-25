# 2110471-Comp-Network-Term-Project

Python socket programming project with Flask for the backend and Tkinter for the desktop frontend.

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
|   `-- user.py
|-- .venv/             # Local environment; excluded from Git
|-- .gitignore
|-- requirements.txt   # Shared Python dependencies
|-- project_plan.md
`-- README.md
```

`backend/server.py` and `frontend/user.py` currently contain placeholder functions. This setup prepares the environment; the server and GUI still need to be implemented. Flask handles HTTP, while raw TCP socket communication must be implemented separately if required by the project.

## Working as a team

- Share source files, `requirements.txt`, and documentation through Git.
- Each member follows these setup instructions to create their own environment.
- When dependencies are added or changed, update `requirements.txt` and commit it. Other members should rerun `python -m pip install -r requirements.txt` after pulling those changes.
- Keep `.venv`, Python cache files, and `.env` files out of Git; the project's `.gitignore` already excludes them.

To leave an activated virtual environment:

```powershell
deactivate
```
