# Contributing to cedrus

Thank you for your interest in improving `cedrus`. This document
covers the workflow for proposing changes, the local development setup,
and the quality gates every contribution must pass.

## Code of conduct

All contributors are expected to follow our
[Code of Conduct](CODE_OF_CONDUCT.md). Be respectful, assume good
faith, and focus on the work.

## Reporting issues

Before opening an issue, search the existing tracker to avoid
duplicates. When filing a new issue, use the provided templates:

- **Bug report** — include a minimal reproduction, expected vs
  observed behavior, environment details (Python version, OS, model
  provider), and the full command or code snippet.
- **Feature request** — describe the problem you are trying to solve,
  the proposed solution, and any alternatives you considered.

For security vulnerabilities, follow [SECURITY.md](SECURITY.md) instead
of opening a public issue.

## Development setup

```bash
git clone https://github.com/sachin/cedrus.git
cd cedrus
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

## Pull request workflow

1. Fork the repository and create a feature branch from `main`.
2. Make focused, atomic commits. Each commit should build and pass the
   full test suite on its own.
3. Write tests for every new feature, bug fix, or behavior change.
   Untested code will not be merged.
4. Run the local quality gates before pushing:

   ```bash
   ruff check .
   mypy
   pytest --cov=cedrus --cov-report=term-missing
   ```

   Coverage must stay above 88%. The full suite must pass on every
   supported Python version.

5. Open a pull request against `main`. Use the provided PR template.
6. Address review feedback with follow-up commits. Avoid force-pushes
   after review has started.

## Coding standards

- **Style** — Google-style docstrings on every public class, method,
  and function. Argparse-style is fine for one-line module docstrings.
- **Naming** — descriptive, intention-revealing names. No leading
  underscores on public API; reserve underscores for truly private
  internals that no external module should ever reference.
- **Exceptions** — raise the most specific `Error`
  subclass available. Never use bare `except Exception`.
- **Logging** — prefer `logging.getLogger(__name__)` over `print`
  for any non-CLI output.
- **Tests** — colocate unit tests next to the module they exercise.
  Use `pytest`, not `unittest`.
- **Coverage** — new code must keep overall coverage at or above 88%.
- **Type hints** — every public symbol carries explicit type hints.
  `mypy --strict` must pass.

## Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` for new features
- `fix:` for bug fixes
- `docs:` for documentation-only changes
- `test:` for test-only changes
- `refactor:` for code changes that neither fix a bug nor add a feature
- `chore:` for tooling or metadata changes
- `ci:` for CI configuration

The subject line is 72 characters or fewer, written in the imperative
mood ("Add generator module", not "Added"). The body explains the
"why" and references any issues it resolves.

## Release process

1. Bump `__version__` in `cedrus/__init__.py` and the version in
   `pyproject.toml`.
2. Update `CHANGELOG.md` with the release notes.
3. Tag the release: `git tag -s vX.Y.Z`.
4. Push the tag: `git push origin vX.Y.Z`.

The CI pipeline will publish the package to PyPI.

## Code review

Reviews focus on correctness, clarity, and tests. Expect to revise.
Maintainers may request changes or close pull requests that do not
align with the project direction.

## Security touchpoints

When you modify one of the security-critical files below, the review
checklist expands to include the listed concerns.

| File | Review checklist |
|------|-------------------|
| `cedrus/deployment.py` | DNS pinning closes SSRF rebind window; no body bytes in errors; redirects disabled by default; idempotency key recorded; retries bounded; symlink targets refused; atomic writes use fsync. |
| `cedrus/verification.py` | Structured AST parser (cedarpy) replaces regex; malformed policies emit `malformed-policy` finding; condition signatures normalized via canonical JSON. |
| `cedrus/generator/litellm.py` | User content fenced in `<<<...>>>` delimiters; system prompt explicitly forbids instructions inside markers. |
| `cedrus/workspace.py` | `intent_from_draft` returns None or raises Space on corrupt stored JSON; never synthesizes a permissive `permit(any/any/any)` fallback. `find_action_namespace` raises on ambiguous action names. |
| `cedrus/storage/sqlite.py` | `column_exists` validates table against allow-list; transactions wrap multi-statement writes; `check_same_thread=False` paired with RLock; WAL + busy_timeout PRAGMAs. |
| `cedrus/cli.py` | Top-level catch wraps non-Error exceptions in JSON envelope; `parse_headers` rejects CR/LF and reserved names; `validate_identifier` rejects path-traversal-shaped inputs. |
