# GitHub Improvements

Audit of this repo's GitHub configuration against best practice for a Django + SvelteKit project. Goal: round out the remaining hygiene after the recent Dependabot + auto-merge work.

## Already in place

- **CI** via GitHub Actions with `dorny/paths-filter` for selective jobs.
- **Dependabot** across all four ecosystems (pip, npm, github-actions, docker) with grouped minor/patch updates — see [.github/dependabot.yml](../../../.github/dependabot.yml).
- **Branch protection** on `main`.
- **Auto-delete head branches** after merge.
- **Allow auto-merge** enabled at the repo level.
- **Dependabot auto-merge workflow** for patch + minor updates — see [.github/workflows/dependabot-auto-merge.yml](../../../.github/workflows/dependabot-auto-merge.yml). Majors still require manual review.

## High-impact gaps

### 1. Secret scanning + push protection

Settings → Code security → enable "Secret scanning" and "Push protection". Blocks commits containing tokens/API keys before they reach the remote. One-minute settings toggle, zero ongoing maintenance, free on public repos.

### 2. CodeQL

No SAST scanner configured. CodeQL auto-detects Python and JS/TS, runs on PRs and weekly, and catches classes of bug that ruff/eslint miss (injection, auth issues, unsafe deserialization). Generated template is adequate as-is — add `.github/workflows/codeql.yml` from the GitHub "Set up code scanning" flow.

### 3. Dependency review action

Dependabot only reacts to merged vulnerabilities by opening follow-up PRs. The [`actions/dependency-review-action`](https://github.com/actions/dependency-review-action) blocks a PR at review time if it introduces a dependency with a known CVE. Single-step addition to CI, complements Dependabot rather than duplicating it.

### 4. Squash-only merge

Settings → General → Pull Requests → uncheck "Allow merge commits" and "Allow rebase merging", keep only "Allow squash merging". History is already squash-style; this just prevents accidents via the web UI.

## Mid-impact

### 5. Concurrency groups on CI

[.github/workflows/ci.yml](../../../.github/workflows/ci.yml) has no `concurrency:` block. Adding:

```yaml
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
```

cancels superseded runs when you push a fixup to a PR. Saves Actions minutes and avoids the "old run passes, new run fails" race.

### 6. GitHub Environments for Railway

Railway deploys currently run outside any named Environment. Wrapping prod in a GitHub Environment unlocks:

- Environment-scoped secrets (separate from repo secrets).
- Required reviewers as a manual approval gate before prod deploys.
- Deployment history visible in the GitHub UI.

Only worth doing once there's a staging target or a reason to want a manual gate. Skip while Railway's own flow is sufficient.

## Minor

- **PR template** — a short `.github/pull_request_template.md` checklist (migrations run? `make codegen`? tests added?) as a self-nag. Low value solo; skip unless forgetting these becomes a pattern.
- **CODEOWNERS** — no value on a single-reviewer repo. Revisit if contributors grow.
- **Issue templates** — only if issues are actually triaged here.
- **Signed commits requirement** — nice-to-have for provenance; not load-bearing given the solo workflow.

## Suggested order

1. **Secret scanning + push protection** (1 min) — pure settings toggle.
2. **Squash-only merge** (1 min) — pure settings toggle.
3. **CodeQL workflow** (5 min) — accept GitHub's generated template.
4. **Dependency review action** (5 min) — single CI step.
5. **Concurrency block on ci.yml** (2 min).
6. **Environments for Railway** — defer until there's a staging target or a reason to want manual approval gates.

Items 1–5 together are ~15 minutes of work and all are low-risk wins.
