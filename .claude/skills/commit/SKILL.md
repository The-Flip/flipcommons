---
name: commit
description: Generates commit messages and creates commits. Use when writing commit messages, committing changes, or reviewing staged changes.
---

# Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/) format.

## Format

```text
<type>(<scope>): <description>

[optional body]
```

## Types

- `feat`: User-facing features or behavior changes (must change production code)
- `fix`: Bug fixes (must change production code)
- `docs`: Documentation only
- `style`: Code style/formatting (no logic changes)
- `refactor`: Code restructuring without behavior change
- `test`: Adding or updating tests
- `chore`: CI/CD, tooling, dependency bumps, configs (no production code)

## Scopes

Optional. Use when it adds clarity. Examples: `backend`, `frontend`, `api`, `auth`, `ci`.

## Examples

```text
feat(frontend): add user login page
fix(api): correct CSRF token handling on POST requests
refactor(backend): simplify database URL configuration
chore: add pre-commit hooks
docs: update quickstart instructions
test(api): add health endpoint integration test
```

## Instructions

1. Run `git diff --staged` to see staged changes
2. Analyze the changes and determine the appropriate type
3. Write a concise description (under 72 characters) - adhere to "title and body quality" below.
4. Add body only if the "why" isn't obvious from the description - adhere to "title and body quality" below.

## Commit title and body quality

**No references to plan docs**. Neither plans in `/docs/plans/` nor `~/.claude/plans/`. Future readers of git history will not have access to these. Instead, describe the actual change or goal or idea.

**No planning ephemera** — phase/step labels like "PRE3", "REF1", "POST2", "phase", "step N". These are scaffolding from plan docs, not durable facts about the code. Those labels mean nothing to a future reader of git history; they age out the moment the plan is done. Instead, describe the actual change.

## Verifying the commit actually happened

Pre-commit hooks fail often in this repo (ruff, mypy/dmypy, prettier, markdownlint, detect-secrets, frontend lint+check+test, backend pytest, agent-docs-regen). A failed commit does NOT advance HEAD — but the failure is easy to miss if you only skim `git commit` output.

After every `git commit`, run this in the same Bash call so the result is unambiguous:

```sh
git commit -m "..." ; echo "EXIT=$?" ; git rev-parse --short HEAD
```

The commit succeeded only if **all three** hold:

- `EXIT=0`
- HEAD moved (compare to the short SHA before the commit)
- `git status` is clean afterward

If any of those fail, the commit did not happen. Read the hook output to classify the failure and recover.

### The autofix trap

Several hooks rewrite files and then fail the commit, leaving the fixes unstaged in the working tree:

- `ruff check --fix` and `ruff format` (backend Python)
- `prettier --write` (markdown)
- `end-of-file-fixer`, `trailing-whitespace`, `mixed-line-ending`
- `agent-docs-regen` (rewrites `CLAUDE.md` / `AGENTS.md` and runs `git add` on them)

Look for `"files were modified by this hook"` or `"Failed"` in the output. Recovery: `git add` the modified paths and create a NEW commit (never `--amend` after a hook failure — the prior commit didn't happen, so amend would rewrite the wrong commit).

### Other common failures

- **mypy daemon out of sync** — symptom: errors that don't match the code. Fix: `make mypy-restart`, then retry.
- **frontend tests / backend pytest fail** — fix the test or the code; do not skip with `--no-verify`.
- **`no-commit-to-branch`** — you're on `main`. Switch to a feature branch.
- **`check-added-large-files`** — a file exceeds 1000 KB. Don't commit it; reconsider whether it belongs in git.
- **`agent-docs-no-direct-edit`** — you edited `CLAUDE.md` or `AGENTS.md` directly. Edit `docs/AGENTS.src.md` instead.

## Project-specific notes

- Do NOT stage `frontend/src/lib/api/schema.d.ts` — it is gitignored and should never be committed.
