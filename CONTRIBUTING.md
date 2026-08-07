# Contributing to tupacss

Thanks for helping out! 🔐

## Setup

```bash
git clone https://github.com/albertorota/tupacss && cd tupacss
uv sync            # creates .venv with all dev dependencies
uv run pytest      # run the test suite
uv run ruff check .
```

Try your changes against a throwaway vault so you never touch your real one:

```bash
export TUPACSS_VAULT=/tmp/tupacss-dev TUPACSS_PASSPHRASE=dev
uv run tupacss init && uv run tupacss
```

## Guidelines

- **Tests**: every behaviour change needs a test. The suite must stay green on
  Linux and macOS, Python 3.11+.
- **Dependencies**: the runtime dependency budget is `click`, `cryptography`,
  `textual`. PRs adding runtime dependencies need a very good reason.
- **Style**: `ruff check .` must pass (it runs in CI). Line length 100.
- **Security-sensitive code** (`crypto.py`, `session.py`, `vault.py`): keep it
  boring and reviewable. If you found a vulnerability, please use GitHub's
  private security advisories instead of a public issue.
- **Commits**: small and focused; imperative mood ("add env diff command").

## Releasing (maintainers)

1. Bump `version` in `pyproject.toml` and `src/tupacss/__init__.py`.
2. Update `CHANGELOG.md`.
3. Tag: `git tag v0.x.y && git push --tags`.
4. Create a GitHub release — the `publish.yml` workflow uploads to PyPI via
   trusted publishing.
