# CLI reference

The `cedar-intent` command-line tool exposes every operation the library
supports. Every command accepts `--json` for machine-readable output
and reads its workspace from `--workspace <path>` (default: the current
directory).

## Global flags

| Flag          | Description                                                   |
| ------------- | ------------------------------------------------------------- |
| `--workspace` | Filesystem path to the workspace (defaults to `cwd`).        |
| `--json`      | Emit machine-readable JSON output.                            |

Exit codes:

- `0` — success
- `1` — `CedarIntentError` raised at any layer
- `2` — argparse validation error

## `cedar-intent init`

```text
cedar-intent init --path <path>
```

Create a new workspace at `<path>`. The workspace contains a hidden
`.cedar-intent/` directory with the SQLite store.

```bash
cedar-intent --workspace /tmp init --path /tmp/acme
```

Output:

```json
{
  "initialized": "/tmp/acme"
}
```

## `cedar-intent domain`

```text
cedar-intent domain add <name>
cedar-intent domain list
```

`add <name>` creates `<name>/schema.json`, `<name>/requirements/`, and
`<name>/policies/` directories. `list` enumerates the domains present
in the workspace.

```bash
cedar-intent domain add hr
cedar-intent domain list
```

## `cedar-intent requirement`

```text
cedar-intent requirement add <path> --domain <name>
cedar-intent requirement list [--domain <name>]
```

`add` copies the Markdown file into the workspace's requirements
directory and registers it in storage. The requirement's identifier
comes from the front matter `id` field, falling back to the filename
stem. `list` shows registered requirements, optionally filtered by
domain.

```bash
cedar-intent requirement add hr/requirements/HR-042.md --domain hr
cedar-intent requirement list --domain hr
```

## `cedar-intent policy`

The `policy` command has three subcommands.

### `policy draft`

```text
cedar-intent policy draft <requirement-id> --domain <name> [scope flags]
```

Build an in-memory draft policy from the requirement and the supplied
scopes. No LLM is invoked. The draft is not persisted.

```bash
cedar-intent policy draft HR-042 \
    --domain hr \
    --principal specific --principal-type User --entity-id alice \
    --action named --action-name viewPhoto \
    --resource is_type --resource-type Photo
```

### `policy generate`

```text
cedar-intent policy generate <requirement-id> --domain <name> [scope flags] [generator flags]
```

Run the configured generator against the requirement and persist the
resulting Cedar draft. The generator is chosen by flags and
environment:

- `--offline` forces the deterministic `OfflineGenerator`.
- `--model <provider/name>` enables the `LiteLLMGenerator`.
- `CEDAR_INTENT_ONLINE=1` enables the `LiteLLMGenerator` when no
  `--offline` flag is present.
- `CEDAR_INTENT_MODEL=<provider/name>` supplies the model.

```bash
# Offline, deterministic
cedar-intent policy generate HR-042 --domain hr \
    --principal specific --principal-type User --entity-id alice \
    --action named --action-name viewPhoto \
    --resource is_type --resource-type Photo \
    --offline

# Online, model-supplied
CEDAR_INTENT_ONLINE=1 CEDAR_INTENT_MODEL=openai/gpt-4o \
cedar-intent policy generate HR-042 --domain hr \
    --principal specific --principal-type User --entity-id alice \
    --action named --action-name viewPhoto \
    --resource is_type --resource-type Photo
```

### `policy apply`

```text
cedar-intent policy apply <requirement-id> --domain <name> [scope flags] [--no-scenarios]
```

Validate the most recent draft for `<requirement-id>` against the
schema, optionally run authorization scenarios, and persist the
compiled policy. Fails if:

- No draft exists for the requirement.
- The draft has unresolved items.
- Cedar validation fails.
- Any scenario fails.

```bash
cedar-intent policy apply HR-042 --domain hr \
    --principal specific --principal-type User --entity-id alice \
    --action named --action-name viewPhoto \
    --resource is_type --resource-type Photo \
    --no-scenarios
```

## `cedar-intent export`

```text
cedar-intent export --domain <name> --output <path>
```

Write the compiled Cedar policies for `<domain>` to `<path>` as a
single concatenated file. Validates before writing.

```bash
cedar-intent export --domain hr --output dist/hr.cedar
```

## `cedar-intent check`

```text
cedar-intent check [--domain <name>]
```

Validate every domain in the workspace, or the specified domain.
Useful as a CI gate.

```bash
cedar-intent --json check
```

## `cedar-intent verify`

```text
cedar-intent verify --domain <name> [--strict]
```

Run static verification on the compiled policies for `<domain>`.
Reports shadowing, redundancy, and coverage gaps. With `--strict`,
exits non-zero when any warning is reported.

```bash
cedar-intent --json verify --domain hr
cedar-intent verify --domain hr --strict
```

## `cedar-intent deploy`

```text
cedar-intent deploy push --domain <name> --target <path-or-url> [--timeout N] [--header Name: Value]...
cedar-intent deploy bundle --domain <name> --output <directory>
cedar-intent deploy history [--domain <name>]
```

- `push` writes a bundle and either saves it to a local directory
  (when `--target` is a path) or POSTs it to an HTTP endpoint
  (when `--target` is `http://...` or `https://...`). Each push is
  recorded in the deployment history.
- `bundle` writes the bundle without recording a deployment.
- `history` lists past deployments.

```bash
# Local deployment
cedar-intent deploy bundle --domain hr --output dist/hr
cedar-intent deploy push --domain hr --target /opt/policies/hr

# HTTP deployment with custom headers
cedar-intent deploy push --domain hr \
    --target https://policy-service.example.com/deploy \
    --header "Authorization: Bearer ..." \
    --header "X-Environment: production"

# History
cedar-intent --json deploy history --domain hr
```

## Scope flags

The `policy` subcommands share a common set of scope arguments. The
default principal / action / resource is `any` for every subcommand.

### Principal flags

| Flag               | Choices                                       |
| ------------------ | --------------------------------------------- |
| `--principal`      | `any`, `type`, `specific`, `in_group`, `is_type` |
| `--principal-type` | Type name (when kind is `type`, `is_type`, ...) |
| `--entity-id`      | Entity id (when kind is `specific`)         |
| `--group-type`     | Group type (when kind is `in_group`)         |
| `--group-id`       | Group id (when kind is `in_group`)           |

### Action flags

| Flag             | Choices                       |
| ---------------- | ----------------------------- |
| `--action`       | `any`, `named`, `in_group`     |
| `--action-name`  | Action name (when named)     |
| `--action-group` | Action group (when in_group) |

### Resource flags

| Flag               | Choices                                       |
| ------------------ | --------------------------------------------- |
| `--resource`       | `any`, `type`, `specific`, `in_parent`, `is_type` |
| `--resource-type`  | Resource type name                           |
| `--entity-id`      | Entity id (when kind is `specific`)         |
| `--parent-type`    | Parent type (when kind is `in_parent`)       |
| `--parent-id`      | Parent id (when kind is `in_parent`)         |

## Environment variables

| Variable                | Purpose                                                    |
| ----------------------- | ---------------------------------------------------------- |
| `CEDAR_INTENT_ONLINE`   | When truthy, prefer `LiteLLMGenerator` over offline.        |
| `CEDAR_INTENT_MODEL`    | Default LiteLLM model identifier.                          |
