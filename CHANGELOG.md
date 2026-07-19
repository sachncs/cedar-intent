# Changelog

All notable changes to this project are documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Apache 2.0 `LICENSE` file.
- `NOTICE` file crediting cedarpy, litellm, and the Cedar language project.
- `README.md` with the seven-step quick start, workspace layout, and
  architecture diagram.
- `CONTRIBUTING.md` describing the fork-branch-PR workflow, local
  setup, conventional-commit style, coding standards, and the release
  process.
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1) adapted for this project.
- `SECURITY.md` documenting the supported-version matrix, the private
  reporting channel, the threat model, and operator hardening
  guidance.
- `CHANGELOG.md` (this file).
- `.github/ISSUE_TEMPLATE/bug_report.md` for structured bug submissions.
- `.github/ISSUE_TEMPLATE/feature_request.md` for feature proposals.
- `.github/ISSUE_TEMPLATE/design_proposal.md` for design discussions.
- `.github/PULL_REQUEST_TEMPLATE.md` enforcing coding standards,
  quality gates, and changelog discipline.
- `.github/workflows/ci.yml` running ruff, mypy strict, pytest on
  Python 3.11 and 3.12 with a 90% coverage gate, and verifying that
  every required documentation file is present.
- `.github/workflows/release.yml` building and publishing the package
  to PyPI on tagged releases with PEP 740 attestations.
- `docs/architecture.md` explaining the requirement-to-deployment
  pipeline and the module responsibility table.
- `docs/cli.md` documenting every CLI subcommand, flag, and exit code.
- `docs/python-api.md` walking through workspaces, drafts, generators,
  compilation, validation, scenarios, verification, and deployment.
- `docs/deployment.md` covering the bundle format, integrity hash,
  local and HTTP targets, recommended workflow, and failure handling.
- `docs/verification.md` documenting the semantics and limitations of
  shadowing, redundancy, and coverage checks.
- `docs/coverage.md` with the current line coverage table.
- `examples/photoflash/` full PhotoFlash scenario with schema,
  requirements, scenarios, baseline policy, and `scripts/run.sh`.
- `examples/todo/` minimal two-role single-resource workspace with
  `run.sh`.
- `examples/api_examples.py` runnable Python snippets exercising the
  public API end to end.
- `.cedar-intent/` and `.cedar-intent/*` entries in `.gitignore`.

### Changed
- Replaced `<your-org>` placeholders with `sachin/cedar-intent` across
  `README.md`, `CHANGELOG.md`, and `CONTRIBUTING.md`.

## [0.4.0] - 2026-06-01

### Added
- Initial prototype with deterministic compiler, LiteLLM-backed
  generator, SQLite-backed workspace, and CLI for end-to-end
  requirement-to-Cedar drafting.

[Unreleased]: https://github.com/sachin/cedar-intent/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/sachin/cedar-intent/releases/tag/v0.4.0
