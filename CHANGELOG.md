# Changelog

All notable changes to this project are documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.6.0] - Unreleased

### Added
- `cedar-intent migrate` CLI subcommand (`--apply`, `--check`,
  default) for upgrading pre-0.6.0 workspaces. Pre-0.6.0 databases
  refuse to open until the migration has run; the CLI provides the
  documented recovery path.
- SQLite `meta` table tracks the current schema version. The version
  is stamped inside the same transaction as the schema change so a
  partially-migrated database either has its declared version or
  does not exist at all.
- SQLite `journal_mode=WAL`, `busy_timeout=5000`, and
  `synchronous=NORMAL` PRAGMAs are set on every connection.
- `update_draft_json` method on the Repository Protocol and both
  backends so the migration populates new columns in place.
- `validate_identifier` and CLI argparse types (`_positive_finite_float`,
  `_non_negative_int`, `_positive_int`) reject path-traversal-shaped
  inputs and negative / infinite numeric flags at parse time.
- Top-level catch wraps non-`CedarIntentError` exceptions in a
  structured JSON envelope when `--json` is set.
- Test suite expanded to 283 tests, including an SSRF truth table
  (22 cases), a pinned-transport test set (5 cases), and a
  verifier-adversarial test set (7 cases).
- Dependabot config (pip + github-actions, weekly).
- Codecov upload on the Python 3.12 lane.
- SBOM (CycloneDX) and sigstore cosign signing in the release
  pipeline; publish job gates on a passing test matrix on the tag.

### Changed
- Version is sourced from `cedar_intent.__version__` at build time
  via `[tool.setuptools.dynamic]`, eliminating drift between the
  package and `pyproject.toml`.
- `DeploymentClient` uses `httpx` with a custom transport that pins
  every HTTP connection to the IP address resolved at SSRF-check
  time. This closes the DNS-rebinding window in which an attacker
  returns a public IP at guard time and a private IP at request time.
- HTTP response bodies are read in bounded chunks, never persisted
  verbatim, and never embedded in error messages. `DeploymentRecord.response`
  now carries `body_sha256` (not `body`) plus `idempotency_key` and
  `retry_count`.
- Redirects are disabled by default; opt in with
  `follow_redirects=True`. The client honours `Retry-After` on 429
  and 503 with exponential backoff up to `max_retries`.
- `BundleExporter.write_directory` refuses symlinked target
  directories, refuses non-empty staging directories, and fsyncs
  both data and directory for durability across power loss.
- `parse_headers` rejects empty names, CR/LF in either name or
  value, names longer than 256 chars, values longer than 8192 chars,
  and reserved names (`Host`, `Authorization`, `Cookie`,
  `Content-Length`, `Transfer-Encoding`).
- The verifier replaces its regex parser with a structured walk
  over `cedarpy.policies_to_json_str`. Conditions are compared by
  canonical JSON form so reordered expressions produce identical
  signatures. Malformed policies emit a `malformed-policy` finding
  rather than silently degrading to `permit(any/any/any)`.
- `LiteLLMGenerator` wraps every piece of user-controlled content in
  fenced `<<<...>>>` delimiters in the user prompt and adds an
  explicit "data only" preamble to the system prompt so hostile
  requirement text or schema JSON cannot impersonate instructions.
- `find_action_namespace` raises `WorkspaceError` when an action id
  is declared in multiple namespaces and `action.namespace` was not
  supplied. Previously the first namespace won by dict iteration
  order, producing non-deterministic compile output across reloads.
- `intent_from_draft` returns `None` or raises `WorkspaceError`
  when stored intent JSON is missing or corrupt. Previously it
  synthesised a permissive `permit(any/any/any)` fallback that
  could ship as a wide-open policy.
- `SqliteRepository` connects with `check_same_thread=False` and
  guards mutating calls with `threading.RLock`.
- `column_exists` validates the table argument against an allow-list
  so the f-string PRAGMA interpolation can never accept user input.
- PyPI metadata in `pyproject.toml` is now complete: readme,
  license, authors, keywords, classifiers, `[project.urls]`.

### Security
- `SECURITY.md` threat model expanded to enumerate DNS rebinding
  pinning, header injection rejection, symlink-replacement refusal,
  bundle hash as corruption detection only (not tamper evidence),
  global-permit fallback removal, and verifier silent-degradation
  fix.
- `docs/deployment.md` carries WARNING callouts for header
  validation, redirect handling, body capture, bundle integrity,
  and DNS rebinding.

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

[Unreleased]: https://github.com/sachin/cedar-intent/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/sachin/cedar-intent/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/sachin/cedar-intent/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/sachin/cedar-intent/releases/tag/v0.4.0
