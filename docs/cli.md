# CLI reference

The `cedrus` command-line tool exposes every operation the library
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
- `1` — `Error` raised at any layer
- `2` — argparse validation error

## `cedrus init`

```text
cedrus init --path <path>
```

Create a new workspace at `<path>`. The workspace contains a hidden
`.cedrus/` directory with the SQLite store.

```bash
cedrus --workspace /tmp init --path /tmp/acme
```

Output:

```json
{
  "initialized": "/tmp/acme"
}
```

## `cedrus domain`

```text
cedrus domain add <name>
cedrus domain list
```

`add <name>` creates `<name>/schema.json`, `<name>/requirements/`, and
`<name>/policies/` directories. `list` enumerates the domains present
in the workspace.

```bash
cedrus domain add hr
cedrus domain list
```

## `cedrus requirement`

```text
cedrus requirement add <path> --domain <name>
cedrus requirement list [--domain <name>]
```

`add` copies the Markdown file into the workspace's requirements
directory and registers it in storage. The requirement's identifier
comes from the front matter `id` field, falling back to the filename
stem. `list` shows registered requirements, optionally filtered by
domain.

```bash
cedrus requirement add hr/requirements/HR-042.md --domain hr
cedrus requirement list --domain hr
```

## `cedrus policy`

The `policy` command has three subcommands.

### `policy draft`

```text
cedrus policy draft <requirement-id> --domain <name> [scope flags]
```

Build an in-memory draft policy from the requirement and the supplied
scopes. No LLM is invoked. The draft is not persisted.

```bash
cedrus policy draft HR-042 \
    --domain hr \
    --principal specific --principal-type User --entity-id alice \
    --action named --action-name viewPhoto \
    --resource is_type --resource-type Photo
```

### `policy generate`

```text
cedrus policy generate <requirement-id> --domain <name> [scope flags] [generator flags]
```

Run the configured generator against the requirement and persist the
resulting Cedar draft. The generator is chosen by flags and
environment:

- `--offline` forces the deterministic `Offline`.
- `--model <provider/name>` enables the `Llm`.
- `CEDAR_INTENT_ONLINE=1` enables the `Llm` when no
  `--offline` flag is present.
- `CEDAR_INTENT_MODEL=<provider/name>` supplies the model.

```bash
# Offline, deterministic
cedrus policy generate HR-042 --domain hr \
    --principal specific --principal-type User --entity-id alice \
    --action named --action-name viewPhoto \
    --resource is_type --resource-type Photo \
    --offline

# Online, model-supplied
CEDAR_INTENT_ONLINE=1 CEDAR_INTENT_MODEL=openai/gpt-4o \
cedrus policy generate HR-042 --domain hr \
    --principal specific --principal-type User --entity-id alice \
    --action named --action-name viewPhoto \
    --resource is_type --resource-type Photo
```

### `policy apply`

```text
cedrus policy apply <requirement-id> --domain <name> [scope flags] [--no-scenarios]
```

Validate the most recent draft for `<requirement-id>` against the
schema, optionally run authorization scenarios, and persist the
compiled policy. Fails if:

- No draft exists for the requirement.
- The draft has unresolved items.
- Cedar validation fails.
- Any scenario fails.

```bash
cedrus policy apply HR-042 --domain hr \
    --principal specific --principal-type User --entity-id alice \
    --action named --action-name viewPhoto \
    --resource is_type --resource-type Photo \
    --no-scenarios
```

## `cedrus export`

```text
cedrus export --domain <name> --output <path>
```

Write the compiled Cedar policies for `<domain>` to `<path>` as a
single concatenated file. Validates before writing.

```bash
cedrus export --domain hr --output dist/hr.cedar
```

## `cedrus check`

```text
cedrus check [--domain <name>]
```

Validate every domain in the workspace, or the specified domain.
Useful as a CI gate.

```bash
cedrus --json check
```

## `cedrus verify`

```text
cedrus verify --domain <name> [--strict]
```

Run static verification on the compiled policies for `<domain>`.
Reports shadowing, redundancy, and coverage gaps. With `--strict`,
exits non-zero when any warning is reported.

```bash
cedrus --json verify --domain hr
cedrus verify --domain hr --strict
```

## `cedrus deploy`

```text
cedrus deploy push --domain <name> --target <path-or-url> [--timeout N] [--header Name: Value]...
cedrus deploy bundle --domain <name> --output <directory>
cedrus deploy history [--domain <name>]
```

- `push` writes a bundle and either saves it to a local directory
  (when `--target` is a path) or POSTs it to an HTTP endpoint
  (when `--target` is `http://...` or `https://...`). Each push is
  recorded in the deployment history.
- `bundle` writes the bundle without recording a deployment.
- `history` lists past deployments.

```bash
# Local deployment
cedrus deploy bundle --domain hr --output dist/hr
cedrus deploy push --domain hr --target /opt/policies/hr

# HTTP deployment with custom headers
cedrus deploy push --domain hr \
    --target https://policy-service.example.com/deploy \
    --header "Authorization: Bearer ..." \
    --header "X-Environment: production"

# History
cedrus --json deploy history --domain hr
```

## migrate

```text
cedrus migrate [--apply | --check]
```

Upgrade a workspace created before cedrus 0.6.0 to the current
schema. The 0.6.0 schema adds per-slot scope JSON columns and typed
intent metadata to every policy and draft, so pre-0.6.0 workspaces
refuse to open until the migration has run.

- Default (no flag): print the number of legacy rows and exit 0.
- `--apply`: perform the migration in place.
- `--check`: exit 1 when legacy rows are present (suitable for CI).
- `--json`: emit a JSON envelope with `pending` and (after `--apply`)
  `upgraded`, `pending_before`, `pending_after`.

```bash
# CI gate
cedrus --json migrate --check || echo "workspace needs migration"

# Apply the migration
cedrus migrate --apply
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
| `CEDAR_INTENT_ONLINE`   | When truthy, prefer `Llm` over offline.        |
| `CEDAR_INTENT_MODEL`    | Default LiteLLM model identifier.                          |
