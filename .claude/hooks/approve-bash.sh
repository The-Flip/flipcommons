#!/bin/bash
# PreToolUse hook: auto-approve Bash commands that match allowed prefixes,
# bypassing Claude Code's broken quote-tracking in prefix matching.
#
# This fixes a known bug where single quotes in commands cause
# permission prompts even when the command prefix is explicitly allowed.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -z "$COMMAND" ]; then
  exit 0
fi

# Allowed command prefixes — add more as needed
ALLOWED_PREFIXES=(
  "curl"
  "detect-secrets scan"
  "duckdb"
  "find"
  "gh "
  "git add"
  "git branch"
  "git cherry-pick"
  "git checkout"
  "git commit"
  "git count-objects"
  "git diff"
  "git fetch"
  "git log"
  "git ls-remote"
  "git merge"
  "git mv"
  "git pull"
  "git push"
  "git rebase"
  "git remote"
  "git rev-list"
  "git rev-parse"
  "git rm"
  "git show"
  "git stash"
  "git status"
  "git switch"
  "git tag"
  "grep"
  "ls"
  "make"
  "mv"
  "npm view"
  "npx eslint"
  "npx prettier"
  "npx vitest"
  "pnpm"
  "pre-commit"
  "python3"
  "pyenv versions"
  "uv add"
  "uv pip list"
  "uv run"
  "uv sync"
  "uv tool run"
  "wc"
)

# Normalize a leading `git -C <path>` to plain `git` so it obeys the same per-subcommand
# allowlist below (a bare `git -C` prefix would auto-approve ANY subcommand, e.g.
# `git -C /repo reset --hard`). A quoted path with spaces won't normalize and falls through.
MATCH_COMMAND=$(printf '%s' "$COMMAND" | sed -E 's#^git -C [^ ]+ #git #')

for prefix in "${ALLOWED_PREFIXES[@]}"; do
  if [[ "$MATCH_COMMAND" == "$prefix"* ]]; then
    echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
    exit 0
  fi
done

# Auto-approve scratch-file writes: a simple cat/echo/printf whose redirect targets
# are ALL under /tmp (covers heredoc scaffolding like `cat > /tmp/pr-body.md <<'EOF'`).
# Only line 1 (the command itself) is inspected; the heredoc body is data, not commands,
# and must never be pattern-matched for safety. Any chaining/substitution on the command
# line, or a redirect pointing anywhere but /tmp, falls through to a normal prompt.
FIRST_LINE=$(printf '%s\n' "$COMMAND" | head -n1)
case "$(printf '%s' "$FIRST_LINE" | awk '{print $1}')" in
  cat|echo|printf)
    case "$FIRST_LINE" in
      *'&&'*|*'||'*|*';'*|*'|'*|*'$('*|*'`'*) ;;  # chained/substituted — not simple
      *)
        TARGETS=$(printf '%s' "$FIRST_LINE" | grep -oE '>>?[[:space:]]*[^[:space:]<>|&;()]+' | sed -E 's/^>>?[[:space:]]*//')
        if [ -n "$TARGETS" ]; then
          ALL_TMP=1
          while IFS= read -r target; do
            case "$target" in
              /tmp/*|/private/tmp/*) ;;
              *) ALL_TMP=0; break ;;
            esac
          done <<EOF
$TARGETS
EOF
          if [ "$ALL_TMP" -eq 1 ]; then
            echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
            exit 0
          fi
        fi
        ;;
    esac
    ;;
esac

# Not matched — fall through to normal permission handling
exit 0
