# Changelog

All notable changes to this project are documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Initial open-source release of `cedar-intent`.
- Python library and `cedar-intent` CLI.
- Abstract `Policy` base class with `DraftPolicy`, `ExistingPolicy`,
  and `CompiledPolicy` subclasses.
- `Generator` Protocol with `OfflineGenerator` (deterministic, no
  network) and `LiteLLMGenerator` (LiteLLM with structured JSON output,
  retries, fallbacks, and timeouts).
- `Repository` Protocol with `InMemoryRepository` (tests) and
  `SqliteRepository` (default on-disk).
- `Workspace` orchestrator tying requirements, drafts, compilation,
  validation, scenario testing, verification, and deployment together.
- Static verification: shadowing detection (forbid dominating
  permit), redundancy detection (equivalent scopes and effect), and
  coverage analysis for actions, requirements, and entity types.
- Deployment automation: `BundleExporter` (SHA-256-signed bundles)
  and `DeploymentClient` (local directory and HTTP targets).
- CLI subcommands: `init`, `domain`, `requirement`, `policy`,
  `export`, `check`, `verify`, `deploy`.
- Online and offline modes controlled by `CEDAR_INTENT_ONLINE` and
  `CEDAR_INTENT_MODEL` environment variables.
- Full test suite (213 tests) with 96% line coverage, strict mypy,
  and ruff linting.
- Documentation: architecture overview, Python API reference, CLI
  reference, deployment guide, verification semantics.

## [0.4.0] - 2026-06-01

### Added
- Initial prototype with deterministic compiler, LiteLLM-backed
  generator, SQLite-backed workspace, and CLI for end-to-end
  requirement-to-Cedar drafting.

[Unreleased]: https://github.com/sachin/cedar-intent/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/sachin/cedar-intent/releases/tag/v0.4.0
