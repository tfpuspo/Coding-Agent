# Coding Agent (no framework, real tool execution)

A coding agent built from scratch with the raw Gemini API and function
calling -- no LangChain, no CrewAI, no framework. It can explore a codebase,
read/write/edit files, and run real shell commands (tests, installs,
scripts), iterating on its own until a task is done.

## How it works

1. You give it a task ("fix the bug in main.py").
2. Gemini decides which tool to call first (usually `list_files` or `read_file`).
3. The tool actually runs on your machine and the result goes back to Gemini.
4. Gemini decides the next step -- maybe `edit_file`, maybe `run_command` to
   test the fix. This repeats until it has a final answer or hits the turn limit.
5. Every write/edit/delete/command asks you to approve it first (shows a
   diff or the exact command), unless you set `AUTO_APPROVE=true`.

## Safety model

Everything is sandboxed to `WORKSPACE_DIR` (default: `./workspace`). The
agent physically cannot read, write, or run commands outside that folder --
every path is resolved and checked before use. Point `WORKSPACE_DIR` at a
real project folder once you trust it; keep it pointed at the throwaway
`workspace/` folder while you're still testing.

## 1. Install

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure

```bash
cp .env.example .env
```
Fill in `GEMINI_API_KEY` (free at https://aistudio.google.com/apikey).
Everything else has a sensible default.

## 3. Run it

**Interactive mode** (like a real coding session -- keeps context across tasks):
```bash
python agent.py
```
```
you> what files are in this project?
you> read main.py and tell me what it does
you> there's a bug in the add function, fix it and verify with a test run
you> exit
```

**One-off task mode:**
```bash
python agent.py "fix the bug in main.py, then run it to confirm it works"
```

## Included: a sample bug to try it on

`workspace/main.py` ships with a deliberate bug (`add()` subtracts instead
of adding) so you have something to point the agent at immediately:

```bash
python agent.py "there's a bug in main.py, find it, fix it, and run it to prove the fix works"
```

Watch it: read the file, spot the bug, propose an edit (you'll be asked to
approve the diff), then run `python main.py` itself to confirm the fix.

## Session persistence & resuming

Every run (REPL or one-off task) saves its full conversation to
`.sessions/<session_id>.json`. At the end of a session you'll see:
```
To continue this session, run: python agent.py --resume abc123def456
```
Run that command to pick the conversation back up with full context of
everything discussed and done previously -- same idea as `codex resume`.

## Switching models mid-session

Inside the REPL, type:
```
/model
```
and enter a new model name. Useful if you hit a quota/deprecation error on
one model and want to switch without restarting.

## Approval flow

When the agent wants to write, edit, delete a file, or run a command, you get:
```
>>> APPROVE? Apply this edit to 'main.py'?
    [y] yes, once   [a] yes, always for this   [n] no:
```
- `y` -- approve just this one action
- `a` -- approve this action AND remember it, so the agent won't ask again
  this session for the same file (write/edit) or same command name (run_command)
- `n` (or anything else) -- reject

## Token usage

At the end of each REPL session (or one-off task), you'll see a summary:
```
Token usage: total=14,773 input=13,593 (+127,232 cached) output=1,180
```



| Tool | What it does |
|---|---|
| `list_files` | Recursively lists files in a directory |
| `read_file` | Reads a file with line numbers |
| `write_file` | Creates a new file or fully overwrites one (shows a diff, asks approval) |
| `edit_file` | Replaces one exact, unique string in a file (safer than a full rewrite) |
| `delete_file` | Deletes a file (asks approval) |
| `run_command` | Runs a shell command in the workspace, e.g. `pytest`, `pip install x`, `python script.py` (asks approval, has a timeout) |

## Config reference (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | (required) | Your free Gemini API key |
| `WORKSPACE_DIR` | `./workspace` | The only folder the agent can touch |
| `MODEL` | `gemini-3.5-flash-lite` | Which Gemini model to use |
| `MAX_TURNS` | `25` | Max tool-calling loops per task before giving up |
| `COMMAND_TIMEOUT` | `60` | Seconds before a shell command is killed |
| `AUTO_APPROVE` | `false` | If `true`, skips all approval prompts -- use with caution |

## A note on models

Google's Gemini model lineup and free-tier quotas have been shifting fast.
If you hit a `404 ... no longer available` or `429 RESOURCE_EXHAUSTED`
error, check which models are currently enabled for your account at
https://aistudio.google.com/apikey and update `MODEL` in `.env` accordingly.

## Extending it

This is intentionally minimal so you can see exactly how it works. Natural
next additions: a `search_files` tool (grep-like), a `git_diff`/`git_commit`
tool, or splitting `run_command` into safer, narrower tools (`run_tests`,
`install_package`) if you want less freedom for the agent.
