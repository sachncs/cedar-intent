# Python API reference

`cedrus` exposes a typed Python API for every workflow. The public
surface lives in the `cedrus` namespace; you should never need to
import from submodules directly.

## Top-level entry points

```python
from cedrus import (
    # Orchestrator
    Space,
    Domain,

    # Schema + validation
    Schema,
    Vreport,
    Validator,

    # Requirements
    Need,

    # Scopes
    Principal,
    Action,
    Resource,
    Clause,
    Scope,
    ScopeFault,

    # Compiled intent
    Intent,
    Source,
    Compile,

    # Verification
    Verifier,
    Report,
    Finding,
    Extraction,
    Parse,

    # Scenarios
    Case,
    Outcome,
    Suite,
    Run,

    # Generation
    Context,
    Generator,
    Proposal,
    Result,
    Offline,
    Llm,

    # Policies
    Kind,
    Draft,
    Compiled,
    Existing,

    # Storage
    Backend,
    Memory,
    Repository,

    # Deployment
    Bundler,
    Client,
    Guard,
    Manifest,
    Record,
    Pin,
    Transport,

    # Errors
    Error,
    Config,
    Require,
    Fault,
    Generate,
    Validate,
    Store,
    Deploy,
    SpaceError,
)
```

## Opening a workspace

```python
from pathlib import Path
from cedrus import Space

# On-disk workspace (SQLite-backed).
workspace = Space.open(Path("./acme"))

# Brand-new workspace with SQLite storage.
workspace = Space.create(Path("./new-workspace"))

# In-memory workspace for tests or ephemeral sessions. State is
# lost when the object is garbage-collected.
workspace = Space.in_memory()
```

`Space.open` raises `SpaceError` if the path does not exist or the
SQLite store is unreachable. `Space.create` makes the directory and
the `.cedrus/` subdirectory; it does not initialize a domain.

## Loading requirements

```python
# Add a single requirement from a Markdown file.
requirement = workspace.add_requirement_file(Path("./acme/hr/requirements/HR-042.md"))

# Or load every requirement in the domain's requirements directory.
added = workspace.add_requirement_directory("hr")

print(requirement.id, requirement.domain, requirement.text)
```

Need Markdown files use YAML-style front matter:

```markdown
---
id: HR-042
domain: hr
---

Only the album owner can view private photos.
```

The `id` and `domain` are read from the front matter. When `id` is
absent, the filename stem is used. When `domain` is absent, the
first path component under the workspace root is used (falling back
to `"default"` when the file is at the workspace root).

## Building policies with the OOP API

```python
from cedrus import (
    Draft,
    Compiled,
    Existing,
    Principal,
    Action,
    Resource,
    Intent,
    Offline,
    Schema,
)

# Build a draft policy directly from scope objects.
draft = Draft(
    id="hr-hr-042",
    requirement=requirement,
    principal=Principal(
        kind="specific", type_name="User", entity_id="alice"
    ),
    action=Action(kind="named", name="viewPhoto", namespace="PhotoFlash"),
    resource=Resource(kind="is_type", type_name="PhotoFlash::Photo"),
)

# Run the deterministic generator against the draft.
schema = Schema.from_mapping(
    {
        "PhotoFlash": {
            "entityTypes": {"User": {}, "Photo": {}},
            "actions": {"viewPhoto": {}},
        }
    }
)
proposal = draft.generate(schema, Offline())

print(proposal.intent)
print(proposal.unresolved)
```

`Draft.generate` returns a `Proposal` whose `intent` is a fully
typed `Intent` (the Cedar source can be rendered with
`proposal.intent.compile().cedar`).

## Generating a draft through the workspace

```python
draft = workspace.create_draft(
    requirement_id="HR-042",
    principal=Principal(
        kind="specific", type_name="User", entity_id="alice"
    ),
    action=Action(kind="named", name="viewPhoto", namespace="PhotoFlash"),
    resource=Resource(kind="is_type", type_name="PhotoFlash::Photo"),
)

new_draft, result = workspace.generate_draft(
    draft, schema, Offline(),
    existing=workspace.list_existing_policies("hr"),
)
print(new_draft.cedar)
```

`new_draft` is a `Draft` (the in-memory policy shape) and the
generated `DraftStored` is also persisted to the repository. `result`
is a `Result` carrying the model identifier, request identifier, and
token usage (wrapped in `cedrus.data.Usage`).

## Compiling a typed intent

```python
from cedrus import Intent, Principal, Action, Resource

intent = Intent(
    id="hr-hr-042",
    requirement_id="HR-042",
    effect="permit",
    principal=Principal(kind="is_type", type_name="PhotoFlash::User"),
    action=Action(kind="named", name="viewPhoto", namespace="PhotoFlash"),
    resource=Resource(kind="is_type", type_name="PhotoFlash::Photo"),
)

source = intent.compile()
print(source.cedar)
```

`intent.compile()` is deterministic; calling it twice with the same
intent produces identical Cedar. `Source.intent_id` carries the
origin intent id; `Source.compiled_at` is a `datetime`.

## Validating and applying

```python
# Validate every compiled policy for the domain.
report = workspace.validate_policies("hr", schema)
print(report.passed, report.errors)

# Compile + validate + run scenarios + persist the compiled policy.
scenarios = workspace.load_scenarios("hr")
compiled = workspace.apply_for_requirement(
    "HR-042", schema, scenarios=scenarios
)
print(compiled.id, compiled.cedar)
```

If any scenario fails, `apply_for_requirement` raises `SpaceError` and
the compiled policy is **not** persisted. The reports are written
regardless so the failure is auditable.

## Running scenarios standalone

```python
from cedrus import Case, Run

scenarios = [
    Case(
        name="alice-can-view",
        principal='PhotoFlash::User::"alice"',
        action='PhotoFlash::Action::"viewPhoto"',
        resource='PhotoFlash::Photo::"p1"',
        context={},
        expected="Allow",
    ),
]

report = Run(scenarios).evaluate(
    schema, [compiled.cedar], entities=[],
)
print(report.passed)
```

## Verification

```python
from cedrus import Verifier

policies = workspace.list_compiled_policies("hr")
requirement_ids = [r.id for r in workspace.list_requirements("hr")]

report = Verifier(schema).verify(
    policies,
    requirement_ids=requirement_ids,
    action_names=sorted(schema.action_names()),
    entity_type_names=sorted(schema.entity_type_names()),
    domain="hr",
)

print(report.passed)
for finding in report.findings:
    print(finding.severity, finding.kind, finding.message)
```

`report.passed` is `True` when no warning-level findings exist. See
[`verification.md`](verification.md) for the semantics of every
finding kind.

The standalone helpers are also exposed:

- `Verifier(schema).shadow(policies)` — shadowing only.
- `Verifier(schema).redundant(policies)` — redundancy only.
- `Verifier(schema).types(policies)` — referenced entity-type names.
- `Verifier(schema).coverage_action(policies, names)` — covered /
  uncovered action pairs.
- `Verifier(schema).coverage_need(policies, ids)` — covered /
  uncovered requirement ids.

## Deployment

```python
from cedrus import Bundler, Client

# Build a deployment manifest.
manifest = workspace.build_bundle("hr", metadata={"channel": "production"})
print(manifest.bundle_hash)

# Write the bundle to a directory.
workspace.write_bundle(manifest, Path("./dist/hr"))

# Push the bundle to a local or HTTP target (also runs verify_domain
# unless skip_verify=True).
record = workspace.deploy(
    "hr",
    target="./dist/hr",
    timeout=30,
)
print(record.id, record.status, record.target_kind)

# Or push directly via the client (bypasses the verify gate).
client = Client(timeout=30)
record = client.deploy(manifest, "https://policy-service.example.com/deploy")
print(record.response)
```

## Storage

```python
from cedrus import Memory, Backend, Repository
from pathlib import Path

# In-memory repository (tests; built on :memory: SQLite).
repo = Memory()

# SQLite-backed repository.
repo = Backend(Path("./.cedrus/store.db"))
repo.close()

# Both implement the Repository Protocol.
assert isinstance(repo, Repository)
```

The protocol covers `fetch`, `execute`, `transaction`,
`remove_requirement`, and `remove_policy`. Every typed-object CRUD
method (`Need.save` / `Stored.upsert` / `DraftStored.save` /
`ReportStored.save` / `Record.save`) routes through the same SQL
primitives so both `Memory` and `Backend` get identical behaviour.

## Errors

All exceptions inherit from `Error`:

```python
from cedrus import (
    Error,
    Config,
    Require,
    Fault,
    Compile,
    Validate,
    Generate,
    ScopeFault,
    Store,
    SpaceError,
    Deploy,
)

try:
    workspace.deploy("hr", "")
except Deploy as error:
    print("deploy failed:", error)
except Error as error:
    print("anything else:", error)
```

`SpaceError` is the alias for `cedrus.error.Space` (renamed in
the public API so it doesn't collide with the `Space` orchestrator
class).

## SSRF guard and pinned transport

`Client` rejects targets in loopback, link-local, and RFC1918 ranges
by default. Each connection is pinned to the IP address resolved at
SSRF-check time so a DNS rebind between the guard and the request
cannot redirect the deployment into a private network. Redirects are
disabled by default.

```python
from cedrus import Client

client = Client(
    timeout=30,
    allow_private_targets=False,
    allow_loopback=False,
)

# Default guard rejects loopback, link-local, and RFC1918.
record = client.deploy(manifest, "https://policy-service.example.com/deploy")

# Tests can opt into loopback:
test_client = Client(allow_loopback=True, timeout=5)
record = test_client.deploy(manifest, "http://127.0.0.1:8080/deploy")

# Internal deployments to a private network require the explicit opt-in:
internal_client = Client(allow_private_targets=True)
record = internal_client.deploy(manifest, "http://policy.svc.cluster.local/deploy")
```

If the guard rejects a target, the deployment raises `Deploy` with
the blocked network. Response bodies are read in bounded chunks and
never embedded in error messages; only a SHA-256 of the body is
recorded on the `Record`.

## Versioning

```python
import cedrus

print(cedrus.__version__)
```
