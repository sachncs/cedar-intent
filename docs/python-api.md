# Python API reference

`cedrus` exposes a typed Python API for every workflow. The
public surface lives in the `cedrus` namespace; you should never
need to import from submodules directly.

## Top-level entry points

```python
from cedrus import (
    Workspace,
    Schema,
    Need,
    Intent,
    Principal,
    Action,
    Resource,
    Offline,
    Llm,
    Draft,
    Existing,
    Compiled,
    Case,
    Vreport,
    Report,
    Manifest,
    Record,
    Bundler,
    Client,
    verify_policies,
    validate_cedar,
    run_scenarios,
)
```

## Opening a workspace

```python
from pathlib import Path
from cedrus import Workspace

# On-disk workspace (SQLite-backed).
workspace = Workspace.open(Path("./acme"))

# Brand-new workspace with SQLite storage.
workspace = Workspace.create(Path("./new-workspace"))

# In-memory workspace for tests or ephemeral sessions.
workspace = Workspace.in_memory(Path("./ephemeral"))
```

## Loading requirements

```python
from pathlib import Path
from cedrus import Workspace, Need

workspace = Workspace.open(Path("./acme"))

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

## Building policies with the OOP API

```python
from cedrus import (
    Draft,
    Principal,
    Action,
    Resource,
    Schema,
    Intent,
    Offline,
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

# Run the generator against the draft.
schema = Schema.from_json_file(Path("./acme/hr/schema.json"))
generator = Offline()
proposal = draft.generate(schema, generator)

print(proposal.intent)
print(proposal.unresolved)
```

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
    draft, schema, generator, existing=workspace.list_existing_policies("hr")
)
print(new_draft.cedar)
```

`result` is a `Result` carrying the model identifier, request
identifier, and token usage.

## Compiling a typed intent

```python
from cedrus import (
    Intent,
    compile_intent,
)

intent = Intent(
    id="hr-hr-042",
    requirement_id="HR-042",
    effect="permit",
    principal=Principal(kind="is_type", type_name="PhotoFlash::User"),
    action=Action(kind="named", name="viewPhoto", namespace="PhotoFlash"),
    resource=Resource(kind="is_type", type_name="PhotoFlash::Photo"),
)

source = compile_intent(intent)
print(source.cedar)
```

`compile_intent` is deterministic; calling it twice with the same
intent produces identical Cedar.

## Validating and applying

```python
# Validate without applying.
report = workspace.validate_policies("hr", schema)
print(report.passed, report.errors)

# Apply with optional scenarios.
scenarios = workspace.load_scenarios("hr")
compiled = workspace.apply_for_requirement(
    "HR-042", schema, scenarios=scenarios
)
print(compiled.id, compiled.cedar)
```

If any scenario fails, `apply` raises `Space` and the compiled
policy is not persisted.

## Running scenarios standalone

```python
from cedrus import Case, run_scenarios

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

report = run_scenarios([compiled.cedar], entities=[], scenarios=scenarios, schema=schema)
print(report.passed)
```

## Verification

```python
from cedrus import verify_policies

policies = workspace.list_compiled_policies("hr")
requirement_ids = [r.id for r in workspace.list_requirements("hr")]
report = verify_policies(
    domain="hr",
    policies=policies,
    requirement_ids=requirement_ids,
    action_names=sorted(schema.action_names()),
    entity_type_names=sorted(schema.entity_type_names()),
)

print(report.passed)
for finding in report.findings:
    print(finding.severity, finding.kind, finding.message)
```

`report.passed` is `True` when no warning-level findings exist.

## Deployment

```python
from cedrus import Bundler, Client

# Build a deployment manifest.
manifest = workspace.build_bundle("hr", metadata={"channel": "production"})
print(manifest.bundle_hash)

# Write the bundle to a directory.
workspace.write_bundle(manifest, Path("./dist/hr"))

# Push the bundle to a local or HTTP target.
record = workspace.deploy(
    "hr",
    target="./dist/hr",
    timeout=30,
)
print(record.id, record.status, record.target_kind)

# Or push directly via the client.
client = Client(timeout=30)
record = client.deploy(manifest, "https://policy-service.example.com/deploy")
print(record.response)
```

## Storage

```python
from cedrus import Memory, Sqlite
from pathlib import Path

# In-memory repository (tests).
repo = Memory()

# SQLite-backed repository.
repo = Sqlite(Path("./.cedrus/store.db"))
repo.close()

# Both implement the Repository Protocol.
from cedrus import Repository

assert isinstance(repo, Repository)
```

The protocol covers requirements, policies, drafts, reports, and
deployments.

## Errors

All exceptions inherit from `Error`:

```python
from cedrus import (
    Error,
    Config,
    Require,
    Policy,
    Compile,
    Validate,
    Generate,
    ScopeFault,
    Store,
    Space,
    Deploy,
)

try:
    workspace.deploy("hr", "")
except Deploy as error:
    print("deploy failed:", error)
except Error as error:
    print("anything else:", error)
```

## Versioning

```python
import cedrus

print(cedrus.__version__)
```

## Deployment: SSRF guard and pinned transport

The `Client` rejects targets in loopback, link-local, and
RFC1918 ranges by default. Each connection is pinned to the IP
address resolved at SSRF-check time so a DNS rebind between the
guard and the request cannot redirect the deployment into a private
network. Redirects are disabled by default.

```python
from cedrus import Client, Deploy

client = Client(
    timeout=30,
    allow_private_targets=False,
    allow_loopback=False,
)

# Default guard rejects loopback, link-local, and RFC1918.
record = client.deploy(manifest, "https://policy-service.example.com/deploy")

# Tests can opt into loopback:
test_client = Client(
    allow_loopback=True,
    timeout=5,
)
record = test_client.deploy(manifest, "http://127.0.0.1:8080/deploy")

# Internal deployments to a private network require the explicit opt-in:
internal_client = Client(allow_private_targets=True)
record = internal_client.deploy(manifest, "http://policy.svc.cluster.local/deploy")
```

If the guard rejects a target, the deployment raises
`Deploy` with the blocked network. Response bodies are read
in bounded chunks and never embedded in error messages; only a
SHA-256 of the body is recorded on the `Record`.
