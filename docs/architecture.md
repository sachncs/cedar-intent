# Architecture

This document explains how `cedar-intent` fits together at the module
level, how a single requirement flows from Markdown to a deployed Cedar
bundle, and which responsibilities belong to which class.

## Bird's-eye view

```text
                    +---------------+
                    |  Requirement  |
                    +-------+-------+
                            |
                            v
                  +-------------------+
                  |   DraftPolicy     |  (scope-typed: principal/action/resource)
                  +---------+---------+
                            |
              Policy.generate(schema, generator)
                            |
                            v
                 +---------------------+
                 |    DraftProposal     |  (typed PolicyIntent + unresolved)
                 +---------+-----------+
                           |
                Policy.compile()  -> CompiledSource
                           |
                           v
                +--------------------+
                |   Cedar source     |  (deterministic emitter)
                +---------+----------+
                          |
            CedarSchema.validate()  -> ValidationReport
                          |
                  Scenario.test()  -> TestReport
                          |
              Workspace.verify_domain()  -> VerificationReport
                          |
              BundleExporter.build()  -> DeploymentManifest
                          |
            DeploymentClient.deploy()  -> DeploymentRecord
```

The LLM is intentionally placed at the proposal stage, not the
deployment stage. Everything downstream of the proposal is a
deterministic check.

## Module responsibilities

| Module              | Responsibility                                                         |
| ------------------- | ---------------------------------------------------------------------- |
| `errors`            | Exception hierarchy rooted at `CedarIntentError`.                     |
| `requirements`      | Markdown loading, front-matter parsing, slug generation, ID handling.    |
| `scopes`            | Typed principal / action / resource / condition scope objects.           |
| `schema`            | Cedar JSON schema wrapper backed by `cedarpy.Schema`.                    |
| `compiler`          | Deterministic Cedar source emission from a typed `PolicyIntent`.        |
| `validation`        | Cedar parsing and schema validation via `cedarpy`.                       |
| `scenarios`         | Authorization scenario loading and execution through the Cedar engine.  |
| `generator.base`    | `Generator` Protocol and shared `DraftProposal` / context dataclasses. |
| `generator.offline` | Deterministic generator that infers effect and conditions from text.    |
| `generator.litellm` | LiteLLM-backed generator with structured JSON output.                    |
| `storage.base`      | `Repository` Protocol and stored-row dataclasses.                        |
| `storage.memory`    | Dict-backed repository for tests.                                       |
| `storage.sqlite`    | SQLite-backed repository with idempotent migrations.                     |
| `policies.base`     | Abstract `Policy` base class.                                           |
| `policies.draft`    | `DraftPolicy` with principal / action / resource scopes.                |
| `policies.existing` | `ExistingPolicy` imported from raw Cedar source.                         |
| `policies.compiled` | `CompiledPolicy` after validation and scenario tests.                    |
| `verification`      | Static symbolic verification: shadowing, redundancy, coverage.          |
| `deployment`        | Bundle export and HTTP/local deployment client.                          |
| `workspace`         | Top-level orchestrator that wires everything together.                   |
| `cli`               | argparse-based CLI with one handler per subcommand.                      |

## Data flow: requirement to deployment

A requirement reaches a deployment bundle through seven stages:

1. **Load.** The workspace reads the requirement Markdown file. The
   front matter supplies the stable identifier and the domain; the
   body becomes the natural-language description.
2. **Scope.** The user (or CLI) supplies principal, action, and
   resource scopes for the draft. These scopes constrain the
   generator to a specific shape.
3. **Generate.** A `Generator` (offline or LiteLLM) receives the
   requirement plus the scopes plus any existing policy intents. It
   produces a typed `DraftProposal` whose `intent` carries effect,
   when/unless clauses, and refined scope values.
4. **Compile.** The deterministic compiler renders the `PolicyIntent`
   into Cedar source text. The compiler is the only code that emits
   Cedar syntax.
5. **Validate.** Cedar parses the source and validates it against the
   schema. Compilation produces formatted, normalized text.
6. **Test.** Optional authorization scenarios are executed through the
   Cedar engine, producing a `TestReport`. The apply step fails if
   any scenario fails.
7. **Verify.** Static verification flags shadowed `forbid`s, redundant
   duplicates, and missing coverage.
8. **Deploy.** The compiled Cedar is bundled with a manifest, hashed
   with SHA-256, and pushed to a local directory or HTTP target.
   The deployment is recorded in the SQLite store.

At every stage, a typed object replaces the natural-language input.
That is the contract that keeps the LLM from writing production Cedar.

## Persistence

The SQLite schema (`.cedar-intent/store.db`) holds five tables:

- `requirements` — one row per requirement loaded from disk.
- `policies` — one row per compiled policy.
- `drafts` — the full history of generator proposals per policy.
- `reports` — the full history of validation and scenario reports.
- `deployments` — the full audit log of bundle deployments.

Foreign keys connect `policies.requirement_id` to `requirements.id`
and cascade on delete. Drafts and reports reference policies by
identifier string, allowing them to survive policy deletion.

## Extending the system

- **New generator** — implement the `Generator` Protocol in
  `cedar_intent.generator.base` and pass it to `Workspace.generate_draft`.
- **New storage backend** — implement the `Repository` Protocol in
  `cedar_intent.storage.base` and construct the workspace with it.
- **New verification check** — add a function returning a list of
  `VerificationFinding` and call it from `verify_policies`.
- **New deployment target** — extend `DeploymentClient.deploy` with a
  new branch for your protocol, or compose `BundleExporter` with your
  own transport.
