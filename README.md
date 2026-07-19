# cedar-intent

[![CI](https://img.shields.io/badge/CI-passing-brightgreen)](.github/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Coverage](https://img.shields.io/badge/coverage-96%25-brightgreen)](docs/coverage.md)

Compile organizational authorization intent into validated, deployable
[Cedar](https://www.cedarpolicy.com) policies.

`cedar-intent` is a Python library and CLI that turns natural-language
authorization requirements into typed policy drafts, validates them
against a Cedar schema, runs authorization scenarios through the Cedar
engine, performs static verification, and exports the result as a
deployment bundle for applications that embed Cedar.

The LLM proposes. Cedar validates. Humans approve. Git remembers.

## Why cedar-intent

Authorization policies are the most safety-critical code most teams
write, yet they are typically authored by hand from English requirements,
reviewed by humans in pull requests, and deployed by ad-hoc shell
scripts. `cedar-intent` makes that loop auditable:

- Requirements live as Markdown with stable identifiers, in a Git-tracked
  workspace.
- A typed intermediate representation (`PolicyIntent`) is the only
  contract between the LLM and the compiler.
- The deterministic compiler emits Cedar source, which is then validated
  against the schema with `cedarpy` and exercised against authorization
  scenarios.
- Static verification flags shadowed `forbid` policies, redundant
  duplicates, and uncovered actions or entity types.
- Deployments are produced as a SHA-256-signed bundle plus a manifest so
  integrity is verifiable end to end.

## Installation

```bash
pip install cedar-intent
```

This installs the library and the `cedar-intent` console script. The
runtime dependencies are `cedarpy` (the official Python binding to the
Cedar policy engine) and `litellm` (the LLM provider abstraction).

For local development:

```bash
git clone https://github.com/<your-org>/cedar-intent.git
cd cedar-intent
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

## Quick start

### 1. Initialize a workspace

```bash
mkdir acme && cd acme
cedar-intent init --path .
```

This creates a `.cedar-intent/store.db` SQLite database inside the
workspace.

### 2. Declare a domain

```bash
cedar-intent domain add hr
```

This creates a `hr/` directory with an empty schema, a `requirements/`
folder, and a `policies/` folder.

### 3. Write a schema

`hr/schema.json`:

```json
{
  "PhotoFlash": {
    "entityTypes": {
      "User": {},
      "Photo": {
        "shape": {
          "type": "Record",
          "attributes": { "private": { "type": "Boolean" } }
        }
      }
    },
    "actions": {
      "viewPhoto": {
        "appliesTo": {
          "principalTypes": ["User"],
          "resourceTypes": ["Photo"]
        }
      }
    }
  }
}
```

### 4. Write a requirement

`hr/requirements/HR-042.md`:

```markdown
---
id: HR-042
domain: hr
---

Only the album owner can view private photos.
```

Register the requirement:

```bash
cedar-intent requirement add hr/requirements/HR-042.md --domain hr
```

### 5. Generate a draft policy

```bash
cedar-intent policy generate HR-042 \
    --domain hr \
    --principal specific \
    --principal-type User \
    --entity-id alice \
    --action named \
    --action-name viewPhoto \
    --resource is_type \
    --resource-type Photo \
    --offline
```

This calls the deterministic `OfflineGenerator` (no LLM needed) and
produces a Cedar draft scoped to your chosen principal, action, and
resource.

To use an LLM instead, set:

```bash
export CEDAR_INTENT_ONLINE=1
export CEDAR_INTENT_MODEL="openai/gpt-4o"
cedar-intent policy generate HR-042 --domain hr ...
```

### 6. Apply the draft

```bash
cedar-intent policy apply HR-042 \
    --domain hr \
    --principal specific \
    --principal-type User \
    --entity-id alice \
    --action named \
    --action-name viewPhoto \
    --resource is_type \
    --resource-type Photo \
    --no-scenarios
```

This validates the Cedar against the schema, persists the compiled
policy, and records it in the deployment history.

### 7. Verify and deploy

```bash
cedar-intent verify --domain hr
cedar-intent deploy bundle --domain hr --output dist/hr
cedar-intent deploy push --domain hr --target http://policy-service/deploy
```

The CLI emits JSON output with `--json` for CI consumption:

```bash
cedar-intent --json check
cedar-intent --json verify --domain hr --strict
```

## Workspace layout

A workspace is a directory holding one or more domains plus a
hidden `.cedar-intent/` folder with the SQLite store.

```text
acme/
├── .cedar-intent/
│   └── store.db
└── hr/
    ├── schema.json
    ├── scenarios.json
    ├── requirements/
    │   └── HR-042.md
    └── policies/
        └── *.cedar
```

Each domain owns its own Cedar schema. Requirements carry a stable
identifier sourced from YAML-style front matter in the Markdown file.
Compiled Cedar policies live as plain `.cedar` files inside
`policies/`.

## Architecture

```text
                    Requirement
                         │
                         ▼
                  DraftPolicy (scope-typed)
                         │
              Policy.generate(schema, generator)
                         │
                         ▼
                 DraftProposal (intent + unresolved)
                         │
                Policy.compile() → Cedar source
                         │
        CedarSchema.validate() → ValidationReport
                         │
                 Scenario.test() → TestReport
                         │
           Workspace.verify_domain() → VerificationReport
                         │
            BundleExporter.build() → DeploymentManifest
                         │
       DeploymentClient.deploy() → DeploymentRecord
```

The LLM never writes Cedar directly. It produces a typed `PolicyIntent`
that the deterministic compiler renders. Cedar validation, scenario
testing, and static verification gate every deployment.

## Documentation

- [Architecture overview](docs/architecture.md)
- [Python API reference](docs/python-api.md)
- [CLI reference](docs/cli.md)
- [Deployment guide](docs/deployment.md)
- [Verification semantics](docs/verification.md)
- [Examples](examples/)

## Development

Run the test suite:

```bash
pytest
```

Run the tests with coverage:

```bash
pytest --cov=cedar_intent --cov-report=term-missing
```

Lint and type-check:

```bash
ruff check .
mypy
```

## Contributing

We welcome contributions. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
process, [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community norms,
and [SECURITY.md](SECURITY.md) for how to report vulnerabilities.

## Versioning

We follow [Semantic Versioning](https://semver.org/). The current
release is tracked in [CHANGELOG.md](CHANGELOG.md) and exposed as
`cedar_intent.__version__`.

## License

cedar-intent is released under the Apache License, Version 2.0. See
[LICENSE](LICENSE) for the full text. The [NOTICE](NOTICE) file
credits the upstream Cedar language project and key dependencies.

## Acknowledgments

- The [Cedar](https://www.cedarpolicy.com) policy language and its
  reference engine, both Apache 2.0 licensed.
- The [cedarpy](https://github.com/k9securityio/cedar-py) Python
  bindings that bridge Python and the Rust Cedar engine.
- [LiteLLM](https://github.com/BerriAI/litellm) for the provider
  abstraction that lets cedar-intent work with any LLM backend.
