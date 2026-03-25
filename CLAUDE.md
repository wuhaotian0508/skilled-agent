# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A minimal local AI agent runner that uses the OpenAI-compatible chat completions API with tool calling. The agent provides an interactive REPL where a language model can read/write files and execute shell commands on the user's machine, with human confirmation for shell execution.

The codebase is bilingual — comments and UI strings are in Chinese; code identifiers are in English.

## Running

```bash
# Install dependencies (no requirements.txt exists)
pip install openai python-dotenv pyyaml

# Run the interactive agent
python agent.py

# Run the tool-calling demo (non-interactive, hardcoded query)
python demo.py
```

Configuration is via `.env` file (not committed):
- `OPENAI_API_KEY` — required (falls back to `ANTHROPIC_API_KEY`)
- `OPENAI_BASE_URL` — API endpoint (default: `https://api.gpugeek.com/`; `/v1` is auto-appended)
- `OPENAI_MODEL` — model identifier (default: `Vendor2/Claude-4.5-Sonnet`)

## Architecture

### agent.py — Main entry point

Four sequential components:

1. **Skill loader** (`load_skills`) — Scans `skills/` subdirectories for `SKILL.md` files, parses YAML frontmatter (`name`, `description`), and builds an XML string injected into the system prompt so the model knows which skills are available.

2. **Tool definitions** (`TOOLS`) — Three OpenAI function-calling tool schemas:
   - `read_file(path)` — read a local file
   - `write_file(path, content)` — overwrite/create a file
   - `execute_shell(command)` — run a shell command (requires user confirmation via stdin)

3. **Tool handler** (`handle_tool_call`) — Dispatches tool calls to local implementations. Shell execution uses `subprocess.run(shell=True, timeout=30)` with interactive y/n confirmation.

4. **Agent loop** (`main`) — Standard OpenAI tool-calling loop: send messages → if response has `tool_calls`, execute them and append results as `role: "tool"` messages → repeat until the model returns a text response.

### skills/ — Skill SOP documents

Markdown files with YAML frontmatter loaded at startup. The model reads the full SKILL.md via `read_file` when it needs the detailed SOP:
- `skills/dev-assistant/SKILL.md` — file operations and code workflow
- `skills/git-manager/SKILL.md` — git operations, .gitignore management, commit/push/revert flows

### demo.py — Standalone demo

Minimal script demonstrating parallel tool calls with two hardcoded functions (`get_weather`, `get_stock_price`). Not part of the agent system.

## Known Issue

`agent.py` line 205 has a typo: `el` instead of `else`, which prevents the script from running. This must be fixed before the agent loop can work.
