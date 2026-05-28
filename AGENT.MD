# Development Rules

## Conversational Style

- Keep answers short and concise
- No emojis in commits, issues, PR comments, or code
- No fluff or cheerful filler text
- Technical prose only, be kind but direct (e.g., "Thanks @user" not "Thanks so much @user!")

## Code Quality

- Maintain good code design and split files reasonably. Avoid cramming all code into a single file. 
- Add brief comments for classes, methods, and key implementation steps. Keep comments short and focused on intent.
- Read files in full before making wide-ranging changes, before editing files you have not already fully inspected, and when the user asks you to investigate or audit something. Do not rely only on search snippets for broad changes.
- NEVER remove or downgrade code to fix type errors from outdated dependencies; upgrade the dependency instead
- Always ask before removing functionality or code that appears to be intentional
- Do not preserve backward compatibility unless the user explicitly asks for it


## Commands

- If you create or modify a test file, you MUST run that test file and iterate until it passes.
- When writing tests, run them, identify issues in either the test or implementation, and iterate until fixed.
- NEVER commit unless user asks

## Verification
- Repo-level checks are `uv run ruff check .` then `make test-all`.
- `make test-all` runs tests for `packages/ai`, `packages/agent`, `packages/coding_agent`, `packages/evals`, `packages/tui`, and `packages/visual`.
- Formatting is `uv run ruff format .` or `make format`.

## Python / Packaging
- Prefer Python 3.12 for repo work. `uv.lock` requires `>=3.12` and Ruff targets `py312`.
- The root is a uv-managed virtual workspace for development. Use `uv sync` to install workspace packages and default dev tools such as `ruff` and `pytest`.
