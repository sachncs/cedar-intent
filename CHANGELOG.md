# Changelog

All notable changes to this project are documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.5.0] - 2026-07-20

### Added
- Static symbolic verification for Cedar policy sets. The verifier
  flags shadowed ``forbid`` policies, redundant duplicates, and
  coverage gaps for actions, requirements, and entity types.
  See `docs/verification.md`.
- Deployment automation. A ``BundleExporter`` builds a
  SHA-256-signed deployment manifest from compiled policies. A
  ``DeploymentClient`` pushes the bundle to a local directory or an
  HTTP endpoint and records the deployment in the workspace.
- CLI subcommands for the new features: ``verify``, ``deploy push``,
  ``deploy bundle``, ``deploy history``.
- Workspace helper methods: ``build_bundle``, ``write_bundle``,
  ``deploy``, ``list_deployments``, ``verify_domain``.

### Changed
- Replaced `<your-org>` placeholders with `sachin/cedar-intent` across
  `README.md`, `CHANGELOG.md`, and `CONTRIBUTING.md`.
- Tightened exception handling in ``LiteLLMGenerator.generate`` to
  catch only ``openai.APIError`` and ``TimeoutError`` instead of
  broad ``Exception``.
- Split combined ``TypeError`` / ``ValueError`` catches in
  ``CedarSchema.__post_init__`` and ``validate_cedar`` so the error
  message reflects the actual failure mode.
- Inlined the lazy imports inside ``Policy.intent_for_verification``
  for clarity.
- Documented every public module, class, function, and method with
  Google-style docstrings. Module docstrings explain the rationale
  for each design choice (deterministic compiler, scope class
  hierarchy, schema validation strategy, and so on).

### Added (Open-source release)
- Apache 2.0 `LICENSE` file.
- `NOTICE` file crediting cedarpy, litellm, and the Cedar language
  project.
- `README.md` with the seven-step quick start, workspace layout, and
  architecture diagram.
- `CONTRIBUTING.md` describing the fork-branch-PR workflow, local
  setup, conventional-commit style, coding standards, and the release
  process.
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1) adapted for this
  project.
- `SECURITY.md` documenting the supported-version matrix, the
  private reporting channel, the threat model, and operator
  hardening guidance.
- `CHANGELOG.md` (this file).
- `.github/ISSUE_TEMPLATE/bug_report.md` for structured bug
  submissions.
- `.github/ISSUE_TEMPLATE/feature_request.md` for feature
  proposals.
- `.github/ISSUE_TEMPLATE/design_proposal.md` for design
  discussions.
- `.github/PULL_REQUEST_TEMPLATE.md` enforcing coding standards,
  quality gates, and changelog discipline.
- `.github/workflows/ci.yml` running ruff, mypy strict, pytest on
  Python 3.11 and 3.12 with a 90% coverage gate, and verifying that
  every required documentation file is present.
- `.github/workflows/release.yml` building and publishing the package
  to PyPI on tagged releases with PEP 740 attestations.
- `docs/architecture.md` explaining the requirement-to-deployment
  pipeline and the module responsibility table.
- `docs/cli.md` documenting every CLI subcommand, flag, and exit
  code.
- `docs/python-api.md` walking through workspaces, drafts,
  generators, compilation, validation, scenarios, verification, and
  deployment.
- `docs/deployment.md` covering the bundle format, integrity hash,
  local and HTTP targets, recommended workflow, and failure
  handling.
- `docs/verification.md` documenting the semantics and limitations
  of shadowing, redundancy, and coverage checks.
- `docs/coverage.md` with the current line coverage table.
- `examples/photoflash/` full PhotoFlash scenario with schema,
  requirements, scenarios, baseline policy, and `scripts/run.sh`.
- `examples/todo/` minimal two-role single-resource workspace with
  `run.sh`.
- `examples/api_examples.py` runnable Python snippets exercising the
  public API end to end.
- `.cedar-intent/` and `.cedar-intent/*` entries in `.gitignore`.

## [0.4.0] - 2026-06-01

### Added
- Initial prototype with deterministic compiler, LiteLLM-backed
  generator, SQLite-backed workspace, and CLI for end-to-end
  requirement-to-Cedar drafting.

[Unreleased]: https://github.com/sachin/cedar-intent/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/sachin/cedar-intent/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/sachin/cedar-intent/releases/tag/v0.4.0
