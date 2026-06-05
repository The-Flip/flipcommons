# Contributing

## Getting Started

Set up your environment per [README.md](README.md).

## Workflow

- **Create a branch** (e.g., `feature/new-icons`, `fix/login-bug`, `docs/api-guide`)
- **Make your changes** and write tests
- **Validate locally**

```bash
make lint        # Format + lint backend and frontend
make test        # Run pytest + vitest
```

- **Commit** — pre-commit hooks run formatting, linting, and secret detection automatically
- **Push and open a Pull Request** against `main`
- **Wait for CI** — GitHub Actions runs tests
- **Merge** when CI passes (self-merge is fine)
- **Wait for deploy** — Merging to `main` deploys the PR. Railway builds the image and swaps out the container only if verification checks pass. You can confirm it's live:
  - `/__health` returns OK
  - `version.json` shows your commit SHA

## Rolling back

There's no true rollback. Instead, create a new branch, make a compensating commit that reverts your change, submit another PR and merge again.

## Working with Railway

For build/deploy mechanics and env config, see [Hosting.md](docs/Hosting.md).
