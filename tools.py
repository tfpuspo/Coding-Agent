"""
tools.py
The real capabilities of the coding agent: read/write/edit files, list
directories, run shell commands. Everything is confined to WORKSPACE_DIR
so the agent can't wander outside the project folder you point it at.

Destructive actions (write_file, edit_file, delete_file, run_command) ask
for your confirmation in the terminal before doing anything, unless
AUTO_APPROVE=true is set in .env.
"""

import os
import subprocess
import difflib

WORKSPACE_DIR = os.path.realpath(os.environ.get("WORKSPACE_DIR", os.path.join(os.getcwd(), "workspace")))
AUTO_APPROVE = os.environ.get("AUTO_APPROVE", "false").strip().lower() == "true"
COMMAND_TIMEOUT = int(os.environ.get("COMMAND_TIMEOUT", "60"))

os.makedirs(WORKSPACE_DIR, exist_ok=True)

IGNORE_DIRS = {".git", "__pycache__", "node_modules", "venv", ".venv", ".pytest_cache"}

# Tracks "always allow" choices for this session, so the agent stops asking
# about the same file or command prefix once you've said "always".
_always_allowed_paths: set[str] = set()
_always_allowed_commands: set[str] = set()


def _resolve(path: str) -> str:
    """Resolve a path relative to WORKSPACE_DIR and block escaping it."""
    full = os.path.realpath(os.path.join(WORKSPACE_DIR, path))
    if not (full == WORKSPACE_DIR or full.startswith(WORKSPACE_DIR + os.sep)):
        raise ValueError(f"Path '{path}' resolves outside the workspace -- refusing.")
    return full


def _confirm(action_description: str, remember_key: str | None = None, remember_set: set | None = None) -> bool:
    """
    Ask for approval. Options: y = approve once, a = approve and remember
    (won't ask again this session for this same key), n = reject.
    """
    if AUTO_APPROVE:
        print(f"[auto-approved] {action_description}")
        return True

    if remember_key is not None and remember_set is not None and remember_key in remember_set:
        print(f"[remembered 'always'] {action_description}")
        return True

    answer = input(
        f"\n>>> APPROVE? {action_description}\n"
        f"    [y] yes, once   [a] yes, always for this   [n] no: "
    ).strip().lower()

    if answer == "a" and remember_key is not None and remember_set is not None:
        remember_set.add(remember_key)
        return True
    return answer == "y"


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------
def list_files(directory: str = ".") -> dict:
    """List files and folders under `directory` (relative to the workspace), recursively."""
    root = _resolve(directory)
    if not os.path.exists(root):
        return {"error": f"Directory not found: {directory}"}

    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        rel_dir = os.path.relpath(dirpath, WORKSPACE_DIR)
        for f in filenames:
            rel_path = os.path.normpath(os.path.join(rel_dir, f))
            entries.append(rel_path)

    return {"workspace": WORKSPACE_DIR, "files": sorted(entries)}


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------
def read_file(path: str) -> dict:
    """Read a file's contents (relative to the workspace), with line numbers."""
    full = _resolve(path)
    if not os.path.isfile(full):
        return {"error": f"File not found: {path}"}
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        numbered = "".join(f"{i+1:5d}\t{line}" for i, line in enumerate(lines))
        return {"path": path, "content": numbered, "line_count": len(lines)}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------
def write_file(path: str, content: str) -> dict:
    """Create a new file or fully overwrite an existing one (relative to the workspace)."""
    full = _resolve(path)
    exists = os.path.isfile(full)

    if exists:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            old_content = f.read()
        diff = "\n".join(difflib.unified_diff(
            old_content.splitlines(), content.splitlines(),
            fromfile=f"{path} (current)", tofile=f"{path} (new)", lineterm=""
        ))
        preview = diff if diff else "(no textual changes)"
    else:
        preview = f"(new file, {len(content.splitlines())} lines)"

    print(f"\n--- {path} ---\n{preview}\n")
    if not _confirm(f"{'Overwrite' if exists else 'Create'} file '{path}'?", remember_key=path, remember_set=_always_allowed_paths):
        return {"status": "rejected_by_user", "path": path}

    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return {"status": "written", "path": path, "bytes": len(content.encode("utf-8"))}


# ---------------------------------------------------------------------------
# edit_file
# ---------------------------------------------------------------------------
def edit_file(path: str, old_str: str, new_str: str) -> dict:
    """
    Replace an exact, unique occurrence of `old_str` with `new_str` in a file
    (relative to the workspace). Safer than write_file for small changes since
    it fails loudly if the match isn't unique instead of guessing.
    """
    full = _resolve(path)
    if not os.path.isfile(full):
        return {"error": f"File not found: {path}"}

    with open(full, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    count = content.count(old_str)
    if count == 0:
        return {"error": "old_str not found in file -- no changes made."}
    if count > 1:
        return {"error": f"old_str matches {count} locations -- must be unique. No changes made."}

    new_content = content.replace(old_str, new_str, 1)
    diff = "\n".join(difflib.unified_diff(
        content.splitlines(), new_content.splitlines(),
        fromfile=f"{path} (current)", tofile=f"{path} (new)", lineterm=""
    ))
    print(f"\n--- {path} ---\n{diff}\n")

    if not _confirm(f"Apply this edit to '{path}'?", remember_key=path, remember_set=_always_allowed_paths):
        return {"status": "rejected_by_user", "path": path}

    with open(full, "w", encoding="utf-8") as f:
        f.write(new_content)
    return {"status": "edited", "path": path}


# ---------------------------------------------------------------------------
# delete_file
# ---------------------------------------------------------------------------
def delete_file(path: str) -> dict:
    """Delete a file (relative to the workspace)."""
    full = _resolve(path)
    if not os.path.isfile(full):
        return {"error": f"File not found: {path}"}

    if not _confirm(f"DELETE file '{path}'? This cannot be undone."):
        return {"status": "rejected_by_user", "path": path}

    os.remove(full)
    return {"status": "deleted", "path": path}


# ---------------------------------------------------------------------------
# run_command
# ---------------------------------------------------------------------------
def run_command(command: str) -> dict:
    """
    Run a shell command inside the workspace directory (e.g. run tests,
    install packages, run a script). Times out after COMMAND_TIMEOUT seconds.
    """
    command_prefix = command.strip().split()[0] if command.strip() else command
    if not _confirm(
        f"RUN COMMAND in {WORKSPACE_DIR}:\n    {command}",
        remember_key=command_prefix,
        remember_set=_always_allowed_commands,
    ):
        return {"status": "rejected_by_user", "command": command}

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
        )
        return {
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout[-8000:],  # cap output to keep context manageable
            "stderr": result.stderr[-4000:],
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {COMMAND_TIMEOUT}s: {command}"}
    except Exception as e:
        return {"error": str(e)}
