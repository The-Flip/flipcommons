# Codex Worktrees

This workflow is for Codex multi-session work only. It is not a general repo policy for every AI tool or local coding workflow.

Use separate git worktrees when multiple Codex sessions need to work in parallel or when the primary checkout is already dirty.

## Recommended Setup

- Create one branch per Codex session from the active feature branch, not from `main`.
- Create one coordinator branch if multiple worker branches will later be merged and normalized together.
- Treat the primary checkout as occupied if another AI session is already using it.
- Do implementation in dedicated worktrees, then merge the coordinator branch back into the active feature branch.

## Frontend Setup In Worktrees

- Give each worktree its own `frontend/node_modules`.
- Prefer a real `pnpm install --offline` in each worktree, backed by the shared pnpm store.
- Do not rely on symlinked `node_modules` for Vitest or Vite-heavy work. It is brittle and can fail in surprising ways.

## Generated Frontend Types

`frontend/src/lib/api/schema.d.ts` is generated and gitignored. Fresh worktrees will not have it automatically.

- Run `make codegen` in the worktree when practical.
- If generation is unnecessary or expensive for the current task, provide a local symlink or copy from an existing checkout that already has the generated file.
- Do not commit `schema.d.ts`.

## Git In Worktrees

Git fsmonitor can cause noisy IPC errors in secondary worktrees.

- Prefer `git -c core.fsmonitor=false ...` for scripted or AI-driven git commands inside auxiliary worktrees.
- If fsmonitor problems are persistent, disable it in the affected worktree before continuing.

## Shared Test Infrastructure

- Default to local helpers first.
- Only extract shared test infrastructure after at least two concrete uses are known.
- Keep cross-suite helper decisions centralized in the coordinator branch or session.

This applies especially to:

- `IntersectionObserver` mocks
- drag/drop helpers
- render helpers
- common fixtures
- jsdom setup additions

## Integration Pattern

When parallel Codex sessions are involved:

1. Create worker branches from the active feature branch.
2. Implement in separate worktrees.
3. Keep unrelated local changes in the primary checkout untouched.
4. Merge worker branches into the coordinator branch first.
5. Run the relevant tests after each merge into the coordinator branch.
6. Normalize style and shared helpers only after seeing real duplication.
7. Merge the coordinator branch back into the active feature branch.

## Why This Matters

This setup reduces collisions between AI sessions, avoids polluting the primary checkout, and keeps integration decisions intentional instead of accidental.
