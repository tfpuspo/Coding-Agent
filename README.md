# Coding Agent (no framework, real tool execution)

A CLI-based coding agent built from scratch on the raw Gemini API with
function calling -- no LangChain, no CrewAI. It reads/writes/edits files and
runs shell commands inside a sandboxed workspace, iterating until the task
is done -- all from your terminal, no GUI or web interface.

## Why this project

A minimal, from-scratch demo of how a coding agent actually works -- no
framework hiding the mechanics. It shows the raw loop: the LLM picks a
tool, the tool runs for real, the result feeds back, and it repeats until
the task is done.

## Stack

- **Language:** Python
- **Interface:** CLI (interactive REPL or one-off task via terminal) -- no GUI or web app
- **LLM:** Google Gemini (`google-genai` SDK), via function calling
- **Config:** `python-dotenv` for `.env` management
- **No frameworks** -- no LangChain, no CrewAI, no agent SDK. Tool
  definitions, the loop, and approval logic are all hand-written.

**Key design choices:**
- Sandboxed to a single `WORKSPACE_DIR` -- can't touch anything outside it
- Human-in-the-loop approval before any write/edit/delete/command
- Session persistence to JSON -- conversations can be resumed later

## How it works

Give it a task -> Gemini picks a tool (`list_files`, `read_file`, `edit_file`,
`write_file`, `delete_file`, `run_command`) -> the tool runs for real ->
Gemini uses the result to decide the next step. Repeats until done or the
turn limit is hit. Every write/edit/delete/command asks for your approval
first, unless `AUTO_APPROVE=true`.

All of this is sandboxed to `WORKSPACE_DIR` (default `./workspace`) -- the
agent can't touch anything outside it.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then add your GEMINI_API_KEY
```

## Run it

```bash
python agent.py                 # interactive REPL
python agent.py "fix the bug in main.py"   # one-off task
```

Try it on the included sample bug:
```bash
python agent.py "there's a bug in main.py, find it, fix it, and run it to prove the fix works"
```

## Extras

- **Sessions**: every run is saved to `.sessions/`. Resume with
  `python agent.py --resume <session_id>`.
- **Switch models mid-session**: type `/model` in the REPL.
- **Approval prompts**: `y` = approve once, `a` = approve and remember, `n` = reject.

## Config (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | (required) | Your Gemini API key |
| `WORKSPACE_DIR` | `./workspace` | The only folder the agent can touch |
| `MODEL` | `gemini-3.5-flash-lite` | Which Gemini model to use |
| `MAX_TURNS` | `25` | Max tool-calling loops per task |
| `COMMAND_TIMEOUT` | `60` | Seconds before a shell command is killed |
| `AUTO_APPROVE` | `false` | Skip approval prompts if `true` |

## Tools

| Tool | What it does |
|---|---|
| `list_files` | Lists files recursively |
| `read_file` | Reads a file with line numbers |
| `write_file` | Creates/overwrites a file (shows diff, asks approval) |
| `edit_file` | Replaces one exact string in a file |
| `delete_file` | Deletes a file (asks approval) |
| `run_command` | Runs a shell command (asks approval, has a timeout) |
