# Python API reference

`cedar-intent` exposes a typed Python API for every workflow. The
public surface lives in the `cedar_intent` namespace; you should never
need to import from submodules directly.

## Top-level entry points

```python
from cedar_intent import (
    Workspace,
    CedarSchema,
    Requirement,
    PolicyIntent,
    PrincipalScope,
    ActionScope,
    ResourceScope,
    OfflineGenerator,
    LiteLLMGenerator,
    DraftPolicy,
    ExistingPolicy,
    CompiledPolicy,
    Scenario,
    ValidationReport,
    VerificationReport,
    DeploymentManifest,
    DeploymentRecord,
    BundleExporter,
    DeploymentClient,
    verify_policies,
    validate_cedar,
    run_scenarios,
)
```

## Opening a workspace

```python
from pathlib import Path
from cedar_intent import Workspace

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
from cedar_intent import Workspace, Requirement

workspace = Workspace.open(Path("./acme"))

# Add a single requirement from a Markdown file.
requirement = workspace.add_requirement_file(Path("./acme/hr/requirements/HR-042.md"))

# Or load every requirement in the domain's requirements directory.
added = workspace.add_requirement_directory("hr")

print(requirement.id, requirement.domain, requirement.text)
```

Requirement Markdown files use YAML-style front matter:

```markdown
---
id: HR-042
domain: hr
---

Only the album owner can view private photos.
```

## Building policies with the OOP API

```python
from cedar_intent import (
    DraftPolicy,
    PrincipalScope,
    ActionScope,
    ResourceScope,
    CedarSchema,
    PolicyIntent,
    OfflineGenerator,
)

# Build a draft policy directly from scope objects.
draft = DraftPolicy(
    id="hr-hr-042",
    requirement=requirement,
    principal=PrincipalScope(
        kind="specific", type_name="User", entity_id="alice"
    ),
    action=ActionScope(kind="named", name="viewPhoto", namespace="PhotoFlash"),
    resource=ResourceScope(kind="is_type", type_name="PhotoFlash::Photo"),
)

# Run the generator against the draft.
schema = CedarSchema.from_json_file(Path("./acme/hr/schema.json"))
generator = OfflineGenerator()
proposal = draft.generate(schema, generator)

print(proposal.intent)
print(proposal.unresolved)
```

## Generating a draft through the workspace

```python
draft = workspace.create_draft(
    requirement_id="HR-042",
    principal=PrincipalScope(
        kind="specific", type_name="User", entity_id="alice"
    ),
    action=ActionScope(kind="named", name="viewPhoto", namespace="PhotoFlash"),
    resource=ResourceScope(kind="is_type", type_name="PhotoFlash::Photo"),
)

new_draft, result = workspace.generate_draft(
    draft, schema, generator, existing=workspace.list_existing_policies("hr")
)
print(new_draft.cedar)
```

`result` is a `GenerationResult` carrying the model identifier, request
identifier, and token usage.

## Compiling a typed intent

```python
from cedar_intent import (
    PolicyIntent,
    compile_intent,
)

intent = PolicyIntent(
    id="hr-hr-042",
    requirement_id="HR-042",
    effect="permit",
    principal=PrincipalScope(kind="is_type", type_name="PhotoFlash::User"),
    action=ActionScope(kind="named", name="viewPhoto", namespace="PhotoFlash"),
    resource=ResourceScope(kind="is_type", type_name="PhotoFlash::Photo"),
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

If any scenario fails, `apply` raises `WorkspaceError` and the compiled
policy is not persisted.

## Running scenarios standalone

```python
from cedar_intent import Scenario, run_scenarios

scenarios = [
    Scenario(
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
from cedar_intent import verify_policies

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
from cedar_intent import BundleExporter, DeploymentClient

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
client = DeploymentClient(timeout=30)
record = client.deploy(manifest, "https://policy-service.example.com/deploy")
print(record.response)
```

## Storage

```python
from cedar_intent import InMemoryRepository, SqliteRepository
from pathlib import Path

# In-memory repository (tests).
repo = InMemoryRepository()

# SQLite-backed repository.
repo = SqliteRepository(Path("./.cedar-intent/store.db"))
repo.close()

# Both implement the Repository Protocol.
from cedar_intent import Repository

assert isinstance(repo, Repository)
```

The protocol covers requirements, policies, drafts, reports, and
deployments.

## Errors

All exceptions inherit from `CedarIntentError`:

```python
from cedar_intent import (
    CedarIntentError,
    ConfigError,
    RequirementError,
    PolicyError,
    CompilationError,
    ValidationError,
    GeneratorError,
    ScopeError,
    StorageError,
    WorkspaceError,
    DeploymentError,
)

try:
    workspace.deploy("hr", "")
except DeploymentError as error:
    print("deploy failed:", error)
except CedarIntentError as error:
    print("anything else:", error)
```

## Versioning

```python
import cedar_intent

print(cedar_intent.__version__)
```
