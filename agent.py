"""
agent.py
A coding agent built with no framework -- just the raw Gemini API with
function calling. It can list files, read files, write/edit/delete files,
and run shell commands (tests, installs, scripts) inside a sandboxed
workspace folder, iterating on its own until the task is done.

Usage:
    python agent.py                      -> interactive REPL
    python agent.py "fix the bug in main.py and re-run the tests"  -> one-off task
"""

import os
import sys
import json
import time
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()  # must run before importing tools, which reads env vars at import time

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

import tools

MODEL = os.environ.get("MODEL", "gemini-3.5-flash-lite")
MAX_TURNS = int(os.environ.get("MAX_TURNS", "25"))

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

SESSIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".sessions")
os.makedirs(SESSIONS_DIR, exist_ok=True)

# ---- Tool schemas ----
list_files_decl = types.FunctionDeclaration(
    name="list_files",
    description="List all files under a directory in the workspace, recursively.",
    parameters={
        "type": "object",
        "properties": {"directory": {"type": "string", "description": "Relative path, default '.'"}},
    },
)

read_file_decl = types.FunctionDeclaration(
    name="read_file",
    description="Read a file's full contents, with line numbers, from the workspace.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Path relative to the workspace"}},
        "required": ["path"],
    },
)

write_file_decl = types.FunctionDeclaration(
    name="write_file",
    description=(
        "Create a new file or fully overwrite an existing one. Shows a diff "
        "and asks the user to approve before writing (unless auto-approved)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the workspace"},
            "content": {"type": "string", "description": "Full file content"},
        },
        "required": ["path", "content"],
    },
)

edit_file_decl = types.FunctionDeclaration(
    name="edit_file",
    description=(
        "Make a targeted edit to an existing file by replacing one exact, "
        "unique string with another. Prefer this over write_file for small "
        "changes -- it fails loudly if old_str isn't unique instead of guessing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the workspace"},
            "old_str": {"type": "string", "description": "Exact text to find (must be unique in the file)"},
            "new_str": {"type": "string", "description": "Text to replace it with"},
        },
        "required": ["path", "old_str", "new_str"],
    },
)

delete_file_decl = types.FunctionDeclaration(
    name="delete_file",
    description="Delete a file from the workspace. Asks for approval first.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Path relative to the workspace"}},
        "required": ["path"],
    },
)

run_command_decl = types.FunctionDeclaration(
    name="run_command",
    description=(
        "Run a shell command inside the workspace (e.g. run tests, install "
        "a package, execute a script). Asks for approval first. Returns "
        "exit code, stdout, and stderr."
    ),
    parameters={
        "type": "object",
        "properties": {"command": {"type": "string", "description": "Shell command to run"}},
        "required": ["command"],
    },
)

TOOLS = types.Tool(
    function_declarations=[
        list_files_decl,
        read_file_decl,
        write_file_decl,
        edit_file_decl,
        delete_file_decl,
        run_command_decl,
    ]
)

TOOL_FUNCTIONS = {
    "list_files": lambda **kw: tools.list_files(**kw),
    "read_file": lambda **kw: tools.read_file(**kw),
    "write_file": lambda **kw: tools.write_file(**kw),
    "edit_file": lambda **kw: tools.edit_file(**kw),
    "delete_file": lambda **kw: tools.delete_file(**kw),
    "run_command": lambda **kw: tools.run_command(**kw),
}

SYSTEM_PROMPT = (
    "You are a coding agent working inside a sandboxed project workspace. "
    "You can list files, read files, write/edit/delete files, and run shell "
    "commands (e.g. to run tests or install dependencies). "
    "Work step by step: explore the codebase first (list_files, read_file) "
    "before making changes. Prefer edit_file over write_file for small, "
    "targeted changes to existing files -- only use write_file for new files "
    "or full rewrites. After making a change, verify it where possible (e.g. "
    "run tests or re-read the file). If a command fails, read the error "
    "carefully, fix the actual cause, and try again -- don't just retry the "
    "same thing. Explain what you did and why at the end."
)


_usage_totals = {"input": 0, "output": 0, "cached": 0}


def _track_usage(response):
    meta = getattr(response, "usage_metadata", None)
    if not meta:
        return
    _usage_totals["input"] += getattr(meta, "prompt_token_count", 0) or 0
    _usage_totals["output"] += getattr(meta, "candidates_token_count", 0) or 0
    _usage_totals["cached"] += getattr(meta, "cached_content_token_count", 0) or 0


def _generate_with_retry(contents, config, retries: int = 4, base_delay: float = 5.0):
    for attempt in range(1, retries + 1):
        try:
            response = client.models.generate_content(model=MODEL, contents=contents, config=config)
            _track_usage(response)
            return response
        except genai_errors.ServerError as e:
            if attempt == retries:
                raise
            delay = base_delay * attempt
            print(f"[agent] Gemini overloaded (attempt {attempt}/{retries}), retrying in {delay:.0f}s...")
            time.sleep(delay)
        except genai_errors.ClientError as e:
            if getattr(e, "code", None) != 429 or attempt == retries:
                raise
            delay = base_delay * attempt
            print(f"[agent] Rate limited (attempt {attempt}/{retries}), retrying in {delay:.0f}s...")
            time.sleep(delay)


def _session_path(session_id: str) -> str:
    return os.path.join(SESSIONS_DIR, f"{session_id}.json")


def save_session(session_id: str, contents) -> None:
    serializable = [c.model_dump(mode="json", exclude_none=True) for c in contents]
    with open(_session_path(session_id), "w", encoding="utf-8") as f:
        json.dump({
            "session_id": session_id,
            "model": MODEL,
            "workspace": tools.WORKSPACE_DIR,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "contents": serializable,
        }, f, indent=2)


def load_session(session_id: str):
    with open(_session_path(session_id), "r", encoding="utf-8") as f:
        data = json.load(f)
    return [types.Content.model_validate(c) for c in data["contents"]]


def print_banner(session_id: str):
    box_lines = [
        "Coding Agent (no framework)",
        "",
        f"model:      {MODEL}   (type /model to change)",
        f"workspace:  {tools.WORKSPACE_DIR}",
        f"session:    {session_id}",
        f"auto-approve: {tools.AUTO_APPROVE}",
    ]
    width = max(len(line) for line in box_lines) + 2
    print("+" + "-" * width + "+")
    for line in box_lines:
        print(f"| {line.ljust(width - 2)} |")
    print("+" + "-" * width + "+")
    print("\nType a task, '/model' to switch models, or 'exit' to quit.\n")


def print_usage_summary():
    total = _usage_totals["input"] + _usage_totals["output"]
    print(
        f"\nToken usage: total={total:,} "
        f"input={_usage_totals['input']:,} (+{_usage_totals['cached']:,} cached) "
        f"output={_usage_totals['output']:,}"
    )


def run_agent(user_message: str, contents=None, max_turns: int = MAX_TURNS):
    """
    Runs the agent loop for one task. `contents` lets a REPL carry the
    conversation across multiple tasks (persistent memory of the session).
    Returns (final_text, contents) so the caller can continue the conversation.
    """
    if contents is None:
        contents = []
    contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

    for loop_index in range(1, max_turns + 1):
        print(f"\n===== Loop {loop_index} =====")
        response = _generate_with_retry(
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, tools=[TOOLS]),
        )

        candidate = response.candidates[0]
        contents.append(candidate.content)

        response_text = "".join(part.text for part in candidate.content.parts if part.text)
        if response_text:
            print(f"[agent says] {response_text}\n")

        function_calls = [part.function_call for part in candidate.content.parts if part.function_call]

        if not function_calls:
            return response_text, contents

        print(f"[loop] calling: {[fc.name for fc in function_calls]}")

        function_response_parts = []
        for fc in function_calls:
            func = TOOL_FUNCTIONS.get(fc.name)
            args = dict(fc.args)
            print(f"[tool] {fc.name}({ {k: (v[:80] + '...' if isinstance(v, str) and len(v) > 80 else v) for k, v in args.items()} })")
            try:
                result = func(**args)
            except Exception as e:
                result = {"error": str(e)}
            function_response_parts.append(
                types.Part.from_function_response(name=fc.name, response={"result": result})
            )

        contents.append(types.Content(role="user", parts=function_response_parts))

    return "Reached max turns without a final answer.", contents


def repl(contents=None, session_id=None):
    global MODEL
    session_id = session_id or uuid.uuid4().hex[:12]
    print_banner(session_id)

    while True:
        try:
            task = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not task:
            continue
        if task.lower() in ("exit", "quit"):
            break
        if task == "/model":
            new_model = input(f"Current model: {MODEL}\nNew model: ").strip()
            if new_model:
                MODEL = new_model
                print(f"Switched to {MODEL}\n")
            continue

        answer, contents = run_agent(task, contents=contents)
        print(f"\nagent> {answer}\n")
        save_session(session_id, contents)

    print_usage_summary()
    if contents:
        print(f"To continue this session, run: python agent.py --resume {session_id}")


if __name__ == "__main__":
    if not os.environ.get("GEMINI_API_KEY"):
        print("Set GEMINI_API_KEY first (see .env.example).")
        print("Get a free key (no credit card) at: https://aistudio.google.com/apikey")
        raise SystemExit(1)

    if len(sys.argv) > 2 and sys.argv[1] == "--resume":
        resume_id = sys.argv[2]
        try:
            contents = load_session(resume_id)
            print(f"Resumed session {resume_id} ({len(contents)} prior messages).\n")
        except FileNotFoundError:
            print(f"No session found with id {resume_id}. Starting fresh.\n")
            contents = None
            resume_id = None
        repl(contents=contents, session_id=resume_id)
    elif len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
        print(f"you> {task}\n")
        answer, contents = run_agent(task)
        print(f"\nagent> {answer}")
        session_id = uuid.uuid4().hex[:12]
        save_session(session_id, contents)
        print_usage_summary()
        print(f"To continue this session, run: python agent.py --resume {session_id}")
    else:
        repl()
