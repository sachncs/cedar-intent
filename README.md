<p align="center">
  <h1 align="center">cedrus</h1>
  <p align="center">The Compiler for Authorization Intent — v0.7.0</p>
  <p align="center">
    <a href="#installation"><img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python" alt="Python"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
    <a href="https://github.com/sachncs/cedrus/actions"><img src="https://img.shields.io/github/actions/workflow/status/sachncs/cedrus/ci.yaml?branch=master" alt="CI"></a>
    <a href="https://github.com/sachncs/cedrus/stargazers"><img src="https://img.shields.io/github/stars/sachncs/cedrus" alt="Stars"></a>
  </p>
</p>

cedrus is the **Authorization Compiler** — the operating system
for versioning, drafting, validating, verifying, and deploying
Cedar policies at enterprise scale.

Every policy — its requirement, scope, generated draft, compiled
Cedar, validation report, verification findings, and deployment
record — is a typed, addressable object in a SQLite-backed graph.
Production teams manage Cedar the way engineers manage code: with
versions, reviews, gated merges, and auditable deploys.

Beyond the drafting surface, cedrus ships:

- **Need contract** — the requirement Markdown with front matter
  and stable id. The unit of governance; the contract gates the
  schema validation and the verify-domain pass.
- **Intent** — the typed intermediate representation. The only
  contract between the LLM and the deterministic compiler; the
  compiler never sees prose.
- **Verifier** — the AST-based static check that flags shadowed
  `forbid`s, redundant duplicates, missing action / need /
  entity-type coverage, and malformed Cedar.
- **Deployer** — `Bundle` + `Client` push a SHA-256-signed bundle
  to a local directory or an HTTP endpoint and record the audit row.
  HTTP is DNS-pinned; redirects are off by default; loopback and
  RFC1918 are rejected by the `Guard`.
- **Backwards-compatible storage** — `Memory` (in-process, for
  tests) and `Backend` (SQLite) both implement the `Repository`
  Protocol and round-trip every typed-object CRUD method
  (`Need.save` / `Stored.upsert` / `DraftStored.save` /
  `ReportStored.save` / `Record.save`).
- **Scenario runner** — `Case` / `Run` / `Suite` exercise the policy
  through the Cedar engine and fail `apply` if any scenario fails.
- **Prompt fence** — every piece of user-controlled content in the
  LLM prompt is wrapped in `<<<...>>>` markers with a "data only"
  preamble so hostile requirement text cannot impersonate
  instructions.
- **Harness** — `Dataset` (ground-truth `{inputs, expected}`) +
  `Precondition` (named command hook) + `EvalRun` (recorded scoring
  of a Release against a Dataset). The loop is closed end-to-end.
- **Offline generator** — the deterministic `Offline` heuristic
  for CI / no-LLM environments; `Llm` for production. Selected via
  `CEDAR_INTENT_ONLINE` / `CEDAR_INTENT_MODEL` env vars or
  `--offline` / `--model` CLI flags.
- **Audit chain** — every state transition is recorded in the
  `deployments` table. The audit row carries `body_sha256` (not
  body) plus `idempotency_key` and `retry_count`. SHA-256 is
  corruption detection only; HMAC / Ed25519 is recommended for
  tamper evidence (see [docs/deployment.md](docs/deployment.md)).
- **CLI parity with the Python API** — every `cedrus` subcommand
  has a one-to-one equivalent in the public `cedrus` namespace
  (`init` / `domain` / `requirement` / `policy` / `export` /
  `check` / `verify` / `deploy`).

v0.7.0 is the first release after a full rewrite of the data
model and the verifier. Every backward-compat shim from 0.6.0 is
gone (the `Workspace` alias, the `migrate` subcommand, the
`compile_intent` / `verify_policies` / `extract_entity_types` /
`generate_record_id` / `validate_policies` / `read_bounded` /
`validate_headers` free-function wrappers, the
`cedrus.data.persist` duplicate module). The full what + why
of every change is in [CHANGELOG.md](CHANGELOG.md); the test
suite grew from ~100 tests across ~10 modules to **561 tests
across 21 modules, 91% line coverage**. The 0.4.0 / 0.5.0 / 0.6.0
history is preserved below.

The v0.8.0 release ships a multi-region replication backend
(Postgres via the existing `Repository` interface), a CRDT
settings layer for collaborative workspace editing, and a
gRPC-over-UDS transport for the optional plugin runtime. The
`docs/roadmap.md` carries the full schedule.

---

## Features

- **Typed intermediate representation** — `Intent` is the single
  contract between every generator and the deterministic compiler.
  The compiler never sees prose.
- **Deterministic Cedar compiler** — `Intent.compile()` is the only
  code that emits Cedar syntax. Calling it twice with the same
  intent produces identical source.
- **Schema-validated generation** — every generated draft is
  verified against the Cedar schema via `cedarpy` before it is
  persisted. Malformed Cedar raises `Compile` (not a silent
  fallback).
- **Static symbolic verifier** — `Verifier(schema).verify(...)`
  flags shadowing, redundancy, missing action / need /
  entity-type coverage, and `malformed-policy` parse failures.
  Exact-signature match only; broader-scope forbids are flagged
  out-of-band.
- **Deployment automation** — `Bundler` writes a SHA-256-signed
  bundle + manifest atomically. `Client` pushes the bundle to a
  local directory or an HTTP endpoint and records the deployment.
  HTTP is DNS-pinned via `httpx`; redirects are off by default.
- **SSRF guard** — every HTTP target is checked against loopback,
  link-local, and RFC1918 ranges by `Guard.check(url)` before the
  request is sent. DNS is resolved once and pinned for the
  connection's lifetime.
- **Harness engineering** — `Dataset` (ground-truth test cases) +
  `Precondition` (named command hook) + `EvalRun` (scored run of a
  Release against a Dataset). The fast iteration loop the OpenAI
  harness-engineering article prescribes.
- **LLM provider abstraction** — `Llm` is a thin wrapper over
  LiteLLM. The prompt fences every piece of user content in
  `<<<...>>>` markers so hostile requirement text or schema JSON
  cannot impersonate instructions.
- **Offline generator** — `Offline` infers `effect` (prohibit /
  deny / forbid → forbid; otherwise permit), extracts the
  `when` clause, and flags unresolved items. No LLM required.
- **SQLite + in-process storage** — `Backend` is the on-disk
  SQLite backend (with `WAL`, `busy_timeout=5000`, `synchronous=
  NORMAL` PRAGMAs and an idempotent migration). `Memory` is the
  in-process backend, implemented as a `Backend` over `:memory:`
  SQLite so every typed-object CRUD method works identically
  against both.
- **REST-style CLI** — `cedrus` is a single console script with
  one subcommand per stage of the pipeline. Every command accepts
  `--json` for machine-readable output.
- **Authorisation header validation** — `Client.validate_headers`
  rejects empty names, CR/LF in either name or value, names
  longer than 256 chars, values longer than 8192 chars, and
  reserved names (`Host`, `Authorization`, `Cookie`,
  `Content-Length`, `Transfer-Encoding`).
- **Atomic schema writes** — `Bundler.write_directory` uses an
  atomic temp-file + `os.replace` pattern so a partial write
  never leaves a torn bundle on disk.
- **Typed errors** — every exception inherits from `Error`.
  `Config`, `Require`, `Fault`, `Compile`, `Validate`, `Generate`,
  `ScopeFault`, `Store`, `SpaceError`, `Deploy`, `Parse` are
  the leaf classes.

---

## Installation

### From source

```bash
git clone https://github.com/sachncs/cedrus.git
cd cedrus
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

### Run from a release

```bash
pip install cedrus
```

**Requirements**: Python 3.11+ (see `pyproject.toml`). The runtime
dependencies are `cedarpy` (the official Python binding to the Cedar
policy engine) and `litellm` (the LLM provider abstraction).

---

## Quick Start

### CLI

```bash
# Initialize a workspace at the current directory.
cedrus init --path .

# Declare a domain with a seeded schema.
cedrus domain add hr

# Write a requirement Markdown file (front matter supplies id + domain).
cat > hr/requirements/HR-042.md <<'EOF'
---
id: HR-042
domain: hr
---

Only the album owner can view private photos.
EOF

# Register the requirement.
cedrus requirement add hr/requirements/HR-042.md --domain hr

# Generate a draft policy deterministically (no LLM needed).
cedrus policy generate HR-042 \
    --domain hr \
    --principal specific --principal-type User --entity-id alice \
    --action named --action-name viewPhoto \
    --resource is_type --resource-type Photo \
    --offline

# Apply the draft (validates + persists + runs scenarios).
cedrus policy apply HR-042 \
    --domain hr \
    --principal specific --principal-type User --entity-id alice \
    --action named --action-name viewPhoto \
    --resource is_type --resource-type Photo \
    --no-scenarios

# Verify statically and build a deployment bundle.
cedrus verify --domain hr
cedrus deploy bundle --domain hr --output dist/hr
cedrus deploy push --domain hr --target dist/hr
```

To use an LLM instead of `Offline`, set:

```bash
export CEDAR_INTENT_ONLINE=1
export CEDAR_INTENT_MODEL="openai/gpt-4o"
cedrus policy generate HR-042 --domain hr ...
```

### Python API

```python
from pathlib import Path
from cedrus import (
    Space, Schema, Need,
    Draft, Intent, Principal, Action, Resource,
    Verifier, Bundler, Client, Offline,
)

# Open a workspace (SQLite-backed).
ws = Space.open(Path("./acme"))

# Load the schema and the requirement.
schema = Schema.from_json_file(Path("./acme/hr/schema.json"))
need = ws.add_requirement_file(Path("./acme/hr/requirements/HR-042.md"))

# Build a scope-typed draft.
draft = Draft(
    id="hr-hr-042",
    requirement=need,
    principal=Principal(kind="specific", type_name="User", entity_id="alice"),
    action=Action(kind="named", name="viewPhoto", namespace="PhotoFlash"),
    resource=Resource(kind="is_type", type_name="PhotoFlash::Photo"),
)

# Generate a typed proposal deterministically.
proposal = draft.generate(schema, Offline())
print(proposal.intent.compile().cedar)

# Validate against the schema.
draft.cedar = proposal.intent.compile().cedar
compiled = ws.apply_for_requirement("HR-042", schema, scenarios=())

# Verify statically.
policies = ws.list_compiled_policies("hr")
report = Verifier(schema).verify(
    policies,
    requirement_ids=["HR-042"],
    action_names=sorted(schema.action_names()),
    entity_type_names=sorted(schema.entity_type_names()),
    domain="hr",
)
print("passed:", report.passed)

# Deploy to a local directory.
manifest = ws.build_bundle("hr")
ws.deploy("hr", target="./dist/hr")
```

---

## Configuration

cedrus is configured via environment variables and CLI flags. Key
settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `CEDAR_INTENT_ONLINE` | `0` | When truthy, prefer the `Llm` generator over `Offline`. |
| `CEDAR_INTENT_MODEL` | (none) | Default LiteLLM model identifier (e.g. `openai/gpt-4o`). |
| `CEDAR_INTENT_OPENAI_API_KEY` | (none) | OpenAI API key. Inherited from `OPENAI_API_KEY` by litellm. |
| `CEDAR_INTENT_ANTHROPIC_API_KEY` | (none) | Anthropic API key. Inherited from `ANTHROPIC_API_KEY` by litellm. |

CLI flags mirror the env vars for one-off invocations:

| Flag | Description |
|------|-------------|
| `--offline` | Force the deterministic `Offline` generator. |
| `--model <provider/name>` | Force the `Llm` generator with the given model. |
| `--timeout <seconds>` | HTTP deployment timeout (positive finite float, default 30). |
| `--allow-loopback` | Permit loopback HTTP targets (test use only). |
| `--allow-private-targets` | Permit RFC1918 HTTP targets. |
| `--skip-verify` | Bypass the verify-domain gate before deployment. |
| `--header "Name: Value"` | Repeatable custom HTTP header for deploy push. |
| `--json` | Emit machine-readable JSON output. |

See [docs/cli.md](docs/cli.md) for the full reference.

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│                    CLI / Python API                │
│         (cedrus init / domain / policy / ...)    │
├──────────────────────────────────────────────────┤
│  Space   (orchestrator: open / create / in_memory) │
│  add_requirement / create_draft / generate_draft  │
│  apply / verify_domain / build_bundle / deploy    │
├──────────────────────────────────────────────────┤
│  Generator   │  Verifier   │  Bundler / Client   │
│  Offline /    │  shadowing  │  atomic writes /   │
│  Llm          │  redundancy │  DNS-pinned HTTP   │
│               │  coverage   │  SSRF Guard        │
├──────────────────────────────────────────────────┤
│  Intent.compile  →  Cedar source                 │
├──────────────────────────────────────────────────┤
│  Scope       │  Validator  │  Case / Run / Suite │
│  Principal  │  cedarpy    │  scenario executor  │
│  Action     │             │                     │
│  Resource   │             │                     │
│  Clause     │             │                     │
├──────────────────────────────────────────────────┤
│  Need         │  Schema        │  Notes / Payload   │
│  Markdown    │  from_mapping  │  Header / Body    │
│  front-mat.  │  from_json_…   │  Target / TargetKind │
│              │                │  Usage / Unresolved  │
├──────────────────────────────────────────────────┤
│  Memory (in-process)  │  Backend (SQLite, on-disk) │
│  :memory: SQLite      │  WAL + busy_timeout +     │
│                       │  synchronous=NORMAL       │
├──────────────────────────────────────────────────┤
│  Repository Protocol (fetch, execute, transaction,  │
│  remove_requirement, remove_policy)               │
└──────────────────────────────────────────────────┘
```

cedrus is composed of layered modules:

| Layer | Description |
|-------|-------------|
| **API** | `cli.py` (argparse subcommands), `python-api.md` (typed surface) |
| **Space** | Orchestrator class that wires every stage of the pipeline. `Space.open` / `Space.create` / `Space.in_memory`. |
| **Generators** | `Offline` (deterministic heuristic) and `Llm` (LiteLLM-backed, prompt-fenced). `Generator` Protocol. |
| **Compiler** | `Intent.compile()` is the only code that emits Cedar syntax. |
| **Verifier** | AST-based static check via `cedarpy.policies_to_json_str`. Detects shadowing, redundancy, coverage gaps, malformed policies. |
| **Storage** | `Memory` (in-process) and `Backend` (SQLite). `Repository` Protocol; typed-object CRUD methods live on each row class. |
| **Scenarios** | `Case` / `Outcome` / `Suite` / `Run` — authorization scenario execution through the Cedar engine. |
| **Deploy** | `Bundler` (write / read) + `Client` (push) + `Guard` (SSRF check) + `Record` (audit row). |
| **Errors** | `Error` base + leaf classes (`Config`, `Require`, `Fault`, `Compile`, `Validate`, `Generate`, `ScopeFault`, `Store`, `SpaceError`, `Deploy`, `Parse`). |

---

## Project Structure

```
cedrus/
├── cedrus/                          # The library (public API: import cedrus)
│   ├── __init__.py                  # Single import surface
│   ├── __main__.py                  # `python -m cedrus` entry point
│   ├── case.py                      # Case / Outcome / Suite / Run
│   ├── cli.py                       # argparse CLI
│   ├── compile.py                   # Intent dataclass + deterministic compiler
│   ├── data/                        # Wire-shape dataclasses
│   │   ├── transit.py               # Context, Proposal, Result
│   │   ├── unresolved.py            # Unresolved items
│   │   └── wire.py                  # Notes, Metadata, Payload, Headers, Body, Receipt, Target, TargetKind, Usage
│   ├── deploy.py                    # Bundler, Guard, Client, Pin, Record, Manifest, Transport
│   ├── domain.py                    # Domain data container
│   ├── error.py                     # Exception hierarchy
│   ├── generate/                    # Generator Protocol + Offline + Llm
│   │   ├── base.py                  # Context, Proposal, Result, Generator Protocol
│   │   ├── offline.py               # Deterministic generator
│   │   └── litellm.py               # LiteLLM-backed generator
│   ├── need.py                      # Markdown loader + Need class
│   ├── policies/                    # Draft / Compiled / Existing + Kind base
│   │   ├── base.py                  # Kind abstract base
│   │   ├── draft.py
│   │   ├── compiled.py
│   │   └── existing.py
│   ├── scope.py                     # Principal, Action, Resource, Clause, Scope
│   ├── schema.py                    # Cedar JSON schema wrapper
│   ├── space.py                     # Space orchestrator
│   ├── store/                       # Repository Protocol + Memory + Backend
│   │   ├── base.py                  # Repository Protocol + typed-object row classes
│   │   ├── memory.py                # in-process :memory: SQLite
│   │   └── sqlite.py                # on-disk SQLite (Backend)
│   ├── utils.py                     # id() — project-wide identifier generator
│   ├── validate.py                  # Vreport + Validator
│   └── verify.py                    # Verifier + Finding + Report + Extraction
├── docs/                            # mdBook-style documentation
│   ├── architecture.md
│   ├── cli.md
│   ├── coverage.md
│   ├── deployment.md
│   ├── python-api.md
│   └── verification.md
├── examples/                        # runnable end-to-end examples
├── tests/                           # 561 tests across 21 files
├── CHANGELOG.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
├── LICENSE                          # Apache 2.0
├── NOTICE
├── pyproject.toml
└── README.md
```

---

## Development

```bash
# Format, lint, and test
.venv/bin/ruff check .
.venv/bin/pytest
.venv/bin/pytest --cov=cedrus --cov-report=term-missing

# Regenerate the coverage report
.venv/bin/python -m pytest tests/ --cov=cedrus --cov-report=term > docs/coverage.md

# Run a specific subset
.venv/bin/pytest tests/test_verification.py -v
```

---

## Testing

```bash
.venv/bin/pytest                              # full suite
.venv/bin/pytest tests/test_verification.py   # single module
.venv/bin/pytest --cov=cedrus --cov-report=term-missing

# Run with coverage report in the terminal
.venv/bin/python -m pytest --cov=cedrus --cov-report=term-missing
```

The test suite has 561 tests across 21 modules. Coverage is
**91%** (277 / 2937 stmts uncovered). The remaining gaps are mostly
defensive error paths in `deploy.py` (HTTP transport edge cases),
the verifier AST helper edge cases, and `space.apply` failure
paths. See [docs/coverage.md](docs/coverage.md) for the per-module
breakdown.

---

## Build

```bash
.venv/bin/pip install -e ".[test]"      # editable install
.venv/bin/python -c "import cedrus"      # smoke test the import
```

`pyproject.toml` is the build manifest. The project ships as a
single `cedrus` package with one console script (`cedrus`).

---

## Release

Tagged `vX.Y.Z` releases are produced by GitHub Actions. Each
release:

- Runs the full test matrix on Python 3.11 and 3.12 with a 90%
  coverage gate.
- Builds an sdist and a wheel via `python -m build`.
- Publishes to PyPI via `pypa/gh-action-pypi-publish`.
- Generates a SBOM (CycloneDX) and signs the release with `sigstore
  cosign` (keyless; the bundle ships next to the wheel).
- Creates a GitHub Release with auto-generated notes from the
  commit log.

See [CHANGELOG.md](CHANGELOG.md) for the full release history.
The 0.7.0 entry is the first release after the full data-model
rewrite.

---

## Tech Stack

| Category | Technology |
|----------|------------|
| Language | Python 3.11+ |
| HTTP Routing | `argparse` (stdlib) |
| Cedar Engine | [cedarpy](https://github.com/k9securityio/cedar-py) (Python bindings to the Rust Cedar engine) |
| LLM SDK | [litellm](https://github.com/BerriAI/litellm) (provider abstraction) |
| Storage | [stdlib sqlite3](https://docs.python.org/3/library/sqlite3.html) (CGo-free, ships with Python) |
| HTTP Client | [httpx](https://www.python-httpx.org/) (with custom DNS-pinning transport) |
| Lint/Format | [ruff](https://docs.astral.sh/ruff/) |
| Type-check | [mypy](https://mypy-lang.org/) (relaxed strict) |
| Releases | [GitHub Actions](https://github.com/features/actions) + [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/) + [sigstore cosign](https://www.sigstore.dev/) |
| Containerization | Docker (multi-stage) |

---

## Documentation

Full documentation lives in **[docs/](docs/)**:

- [Architecture overview](docs/architecture.md) — the requirement-to-deployment pipeline, module responsibility table, persistence schema, and extension points
- [Python API reference](docs/python-api.md) — workspace, drafts, generators, compilation, validation, scenarios, verification, deployment
- [CLI reference](docs/cli.md) — every subcommand, flag, environment variable, and exit code
- [Deployment guide](docs/deployment.md) — bundle format, integrity hash, local and HTTP targets, recommended workflow, failure handling, SSRF + DNS-pinning warnings
- [Verification semantics](docs/verification.md) — every check kind (shadowing, redundancy, coverage, malformed), what each detects, and what each doesn't
- [Coverage report](docs/coverage.md) — live per-module coverage table (91% total)

---

## Roadmap

- **v0.8.0** — Multi-region replication (Postgres via the existing
  `Repository` interface, no domain-package changes). CRDT settings
  for collaborative workspace editing. gRPC-over-UDS transport for
  the optional plugin runtime. See `docs/roadmap.md` for the
  detailed schedule.
- **v1.0.0** — Stable API. Final review of all public surfaces.
  No breaking changes after this point.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/](docs/) for the development workflow, coding standards,
changelog discipline, and the release process.

## Security

See [SECURITY.md](SECURITY.md). Report vulnerabilities via the GitHub
Security Advisories workflow — **do not open a public issue.**

## Support

- **Issues**: [GitHub Issues](https://github.com/sachncs/cedrus/issues)
- **Discussions**: [GitHub Discussions](https://github.com/sachncs/cedrus/discussions)

## License

cedrus is released under the Apache License, Version 2.0. See
[LICENSE](LICENSE) for the full text. The [NOTICE](NOTICE) file
credits the upstream Cedar language project and key dependencies
(cedarpy, litellm).
