# Deployment guide

`cedar-intent` produces a self-contained deployment bundle and pushes
it to either a local directory or an HTTP endpoint. This page explains
the bundle format, the integrity model, and the operator workflow.

## Bundle format

Every deployment produces a two-file artifact written to the target:

```text
<target>/
├── bundle.cedar      # concatenated Cedar source for every compiled policy
└── manifest.json     # metadata: domain, hash, policy IDs, timestamp
```

`manifest.json` example:

```json
{
  "bundle_hash": "9c2a…f0",
  "domain": "hr",
  "metadata": {
    "channel": "production"
  },
  "policy_ids": ["hr-hr-001", "hr-hr-042"],
  "created_at": "2026-07-20T12:34:56.789012+00:00"
}
```

The `bundle_hash` is the SHA-256 digest of `bundle.cedar`. The
manifest is committed alongside the bundle so consumers can verify
integrity after transport.

## Integrity verification

Every `DeploymentClient` deployment records a `DeploymentRecord` with
the `bundle_hash`. After a deployment, you can re-read the on-disk
bundle and confirm the hash matches:

```python
from pathlib import Path
from cedar_intent import BundleExporter

exporter = BundleExporter()
manifest = exporter.read_directory(Path("/opt/policies/hr"))
print(manifest.bundle_hash == "<expected hash>")
```

If the hash does not match, the read fails with `DeploymentError` and
a clear message identifying the expected and actual digests.

## Local deployment

Use a local directory target when the embedded Cedar engine reads
policies from a shared filesystem or a mounted volume.

```bash
cedar-intent deploy push --domain hr --target /opt/policies/hr
```

The CLI creates the directory if it does not exist. Existing files in
the directory are not removed; the deployment only writes `bundle.cedar`
and `manifest.json`.

## HTTP deployment

Use an HTTP target when the embedded Cedar engine pulls policies from a
service. The HTTP request is a `POST` with the full manifest as a JSON
body:

```http
POST /deploy HTTP/1.1
Host: policy-service.example.com
Content-Type: application/json
X-Cedar-Bundle-Hash: 9c2a…f0
X-Cedar-Domain: hr

{"domain": "hr", "cedar": "...", "bundle_hash": "9c2a…f0", ...}
```

The service should respond with `2xx` for accepted deployments and a
non-2xx for rejected ones. cedar-intent treats `2xx` as success and
any other status as a `DeploymentError`.

Custom headers can be added per deployment:

```bash
cedar-intent deploy push \
    --domain hr \
    --target https://policy-service.example.com/deploy \
    --header "Authorization: Bearer ..." \
    --header "X-Environment: production"
```

The HTTP timeout defaults to 30 seconds and is configurable with
`--timeout`.

## Deployment history

Every successful deployment appends a row to the `deployments` table
in SQLite. Use the CLI or the API to inspect the history:

```bash
cedar-intent --json deploy history --domain hr
```

```python
records = workspace.list_deployments("hr")
for record in records:
    print(record.id, record.bundle_hash, record.target_kind, record.status)
```

The history is append-only. There is no built-in rollback; remove the
deployed bundle and redeploy an earlier bundle from your backup.

## Recommended workflow

1. Develop the policy set in a workspace under version control.
2. Run `cedar-intent check`, `cedar-intent verify --strict`, and
   `cedar-intent policy apply` in CI before merging.
3. After merge, run `cedar-intent deploy push` from a tagged release
   commit.
4. Verify the deployment via `deploy history` and by reading back
   the manifest hash.

## Failure handling

| Failure                                  | Behavior                                        |
| ---------------------------------------- | ----------------------------------------------- |
| Local directory unwritable               | `DeploymentError` raised before any write.     |
| HTTP endpoint returns non-2xx            | `DeploymentError` raised; response body captured. |
| HTTP timeout                             | `DeploymentError` raised; underlying `TimeoutError` chained. |
| Cedar schema mismatch (downstream)       | Surfaced by the consuming service; cedar-intent does not catch this. |

Always inspect the captured response body in `DeploymentRecord.response`
when investigating HTTP deployment failures.
