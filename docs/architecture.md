# Architecture

`cedrus` compiles organizational authorization intent into
validated, deployable Cedar. This document explains how the package
fits together at the module level, how a single requirement flows
from Markdown to a deployed bundle, and which responsibilities belong
to which class.

## Bird's-eye view

```text
                  +---------------+
                  |    Need      |  (Markdown, front matter)
                  +-------+-------+
                          |
                          v
                +-------------------+
                |     Draft      |  (scope-typed: principal / action / resource)
                +---------+---------+
                          |
                draft.generate(schema, generator)
                          |
                          v
                 +---------------------+
                 |     Proposal      |  (typed Intent + unresolved items)
                 +---------+-----------+
                           |
                  intent.compile()  ->  Source
                           |
                           v
                 +---------------------+
                 |    Cedar source    |  (deterministic emitter)
                 +---------+-----------+
                           |
                Validator(schema).validate(...)
                           |
                  Run(scenarios).evaluate(...)
                           |
                   Verifier(schema).verify(...)
                           |
                Bundler.build()   ->   Manifest
                           |
                 Client.deploy(manifest, target)   ->   Record
```

The LLM is intentionally placed at the proposal stage, not the
deployment stage. Everything downstream of the proposal is a
deterministic check.

## Module responsibilities

| Module              | Responsibility                                                         |
| ------------------- | ---------------------------------------------------------------------- |
| `cedrus.error`      | Exception hierarchy rooted at `Error`.                     |
| `cedrus.utils`      | Project-wide identifier generator (`utils.id`).               |
| `cedrus.need`       | Markdown loader, front-matter parser, slug generation, `Need.save` / `get` / `list` classmethods. |
| `cedrus.scope`      | Typed `Principal` / `Action` / `Resource` / `Clause` scope objects, polymorphic `Scope.parse` dispatcher. |
| `cedrus.schema`     | Cedar JSON schema wrapper backed by `cedarpy.Schema`.                    |
| `cedrus.compile`    | `Intent` dataclass, deterministic Cedar source emission via `Intent.compile()`.   |
| `cedrus.validate`   | `Vreport` dataclass, `Validator` wrapper, `cedarpy` integration.                       |
| `cedrus.case`       | `Case` / `Outcome` / `Suite` / `Run` for authorization scenario execution.        |
| `cedrus.generate`   | `Generator` Protocol, `Context` / `Proposal` / `Result` dataclasses, `Offline` and `Llm` implementations. |
| `cedrus.store`      | `Repository` Protocol, `Stored` / `DraftStored` / `ReportStored` row dataclasses, `Backend` (SQLite) and `Memory` (in-process) implementations. |
| `cedrus.policies`   | `Kind` abstract base, `Draft` / `Compiled` / `Existing` policy shapes.            |
| `cedrus.verify`     | Static symbolic verification: shadowing, redundancy, coverage, malformed-policy detection. |
| `cedrus.deploy`     | `Bundler` (write_directory / read_directory), `Guard` SSRF guard, `Client` HTTP / local push, `Record` audit row. |
| `cedrus.data`       | Wire-shape dataclasses for cross-process serialization (`Notes`, `Metadata`, `Payload`, `Receipt`, `Headers`, `Body`, `Target`, `Usage`, `TargetKind`, `Context`, `Proposal`, `Result`, `Unresolved`). |
| `cedrus.space`      | `Space` orchestrator that wires every stage together.                       |
| `cedrus.cli`        | argparse-based CLI with one handler per subcommand.                      |

## Data flow: requirement to deployment

A requirement reaches a deployment bundle through eight stages:

1. **Load.** `Space.add_requirement_file` reads the requirement
   Markdown file. The front matter supplies the stable identifier and
   the domain; the body becomes the natural-language description. A
   workspace without the file can `add_requirement_directory` to load
   every `*.md` in `<workspace>/<domain>/requirements/`.
2. **Scope.** The user (or CLI) supplies principal, action, and
   resource scopes for the draft. These scopes constrain the
   generator to a specific shape.
3. **Generate.** A `Generator` (offline or LiteLLM) receives the
   requirement plus the scopes plus any existing policy intents. It
   produces a typed `Proposal` whose `intent` carries effect,
   when / unless clauses, and refined scope values.
4. **Compile.** `Space.generate_draft` calls `Intent.compile()`,
   which renders the `Intent` into Cedar source text. The compiler
   is the only code that emits Cedar syntax.
5. **Validate.** `Validator(schema).validate([cedar])` parses the
   source and validates it against the schema. Successful validation
   produces a formatted, normalized text.
6. **Test.** Optional authorization scenarios are executed through
   the Cedar engine, producing a `Suite`. The apply step fails if
   any scenario fails.
7. **Verify.** `Verifier(schema).verify(...)` flags shadowed
   `forbid`s, redundant duplicates, missing action coverage, missing
   requirement coverage, missing entity-type coverage, and
   `malformed-policy` parse failures.
8. **Deploy.** The compiled Cedar is bundled with a manifest,
   hashed with SHA-256, and pushed to a local directory or HTTP
   target. The deployment is recorded in the SQLite store as a
   `Record`.

At every stage, a typed object replaces the natural-language input.
That is the contract that keeps the LLM from writing production Cedar.

## Persistence

The SQLite schema (`.cedrus/store.db`) holds five top-level tables
plus the typed-object sub-tables (version 3 of the schema):

- `requirements` — one row per requirement loaded from disk.
- `policies` — one row per compiled policy.
- `drafts` — one row per generator proposal.
- `reports` — one row per validation or scenario run.
- `deployments` — one row per deployment record.
- `principals` / `actions` / `resources` / `clauses` — typed-object
  rows referenced by FK from `policies.intent_id` and the composition
  tables.
- `intents` / `intent_when_clauses` / `intent_unless_clauses` /
  `intent_notes` — typed intent graph.
- `clause_attributes` — attribute bindings for clauses.
- `draft_unresolved` — unresolved items referenced by draft.
- `report_payload` — validation / scenario report payload.
- `deployment_responses` — HTTP deployment response key/value pairs.
- `meta` — schema version stamp.

Foreign keys connect `policies.requirement_id` to `requirements.id`
and cascade on delete (`ON DELETE SET NULL` on the policy side).
Drafts and reports reference policies by identifier string,
allowing them to survive policy deletion.

## Extending the system

- **New generator** — implement the `Generator` Protocol in
  `cedrus.generate.base` and pass it to `Space.generate_draft`.
- **New storage backend** — implement the `Repository` Protocol
  (`fetch`, `execute`, `transaction`, `remove_requirement`,
  `remove_policy`) in `cedrus.store.base` and construct the
  workspace with it.
- **New verification check** — add a method to `Verifier` that
  returns a list of `Finding` and call it from `verify`.
- **New deployment target** — add a branch in `Client.deploy` for
  your protocol, or compose `Bundler` with your own transport.

## Generated identifiers

Everywhere `cedrus` needs a unique identifier for a new row
(draft id, record id, etc.) it calls `cedrus.utils.id()`. The function
returns a 24-character lowercase hex string: an 8-character hex unix
timestamp prefix followed by 16 hex characters of `os.urandom(8)`.
This mirrors the MongoDB / Stripe object_id layout — sort by id to
get insertion order, get a unique id without coordination.

Tests use the same generator; there is no "test mode" that produces
deterministic ids.
