# Deployment guide

`cedrus` produces a self-contained deployment bundle and pushes
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
from cedrus import BundleExporter

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
cedrus deploy push --domain hr --target /opt/policies/hr
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
Idempotency-Key: 7c4e…

{"domain": "hr", "cedar": "...", "bundle_hash": "9c2a…f0", ...}
```

The service should respond with `2xx` for accepted deployments and a
non-2xx for rejected ones. cedrus treats `2xx` as success and
any other status as a `DeploymentError`.

Custom headers can be added per deployment:

```bash
cedrus deploy push \
    --domain hr \
    --target https://policy-service.example.com/deploy \
    --header "Authorization: Bearer ..." \
    --header "X-Environment: production"
```

> **WARNING — header validation.** Every header name and value is
> validated. Names may not be empty, contain CR/LF, or be one of
> the reserved names (`Host`, `Authorization`, `Cookie`,
> `Content-Length`, `Transfer-Encoding`). Values may not contain
> CR/LF and are capped at 8192 bytes. Names are capped at 256 bytes.

> **WARNING — redirect handling.** HTTP redirects are **disabled**
> by default. A `3xx` response is treated as a deployment failure.
> Pass `--follow-redirects` to the deployment client (via the Python
> API) to opt in. The SSRF guard is re-applied on every hop when
> redirects are enabled, but operators should prefer a single direct
> endpoint.

> **WARNING — body capture.** The HTTP response body is never
> embedded in error messages or persisted verbatim in the deployment
> record. Only a SHA-256 of the body is retained. If you need to
> inspect the body, capture it on the server side instead.

> **WARNING — bundle integrity.** The SHA-256 hash in the manifest
> provides **corruption detection only**. An attacker who can replace
> both `bundle.cedar` and `manifest.json` can recompute the digest
> trivially. Add a keyed signature (HMAC-SHA-256 with a shared key,
> or Ed25519 with a published public key) in the deploy metadata when
> you need tamper evidence.

> **WARNING — DNS rebinding.** The SSRF guard pins every HTTP
> connection to the IP address resolved at SSRF-check time. A change
> in authoritative DNS between the guard and the request cannot
> redirect the deployment into a private network.

The HTTP timeout defaults to 30 seconds and is configurable with
`--timeout`. The connection is closed after `--timeout` seconds; a
network error on the remote side raises `DeploymentError` without
retrying unless `--retries` is non-zero.

## Deployment history

Every successful deployment appends a row to the `deployments` table
in SQLite. Use the CLI or the API to inspect the history:

```bash
cedrus --json deploy history --domain hr
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
2. Run `cedrus check`, `cedrus verify --strict`, and
   `cedrus policy apply` in CI before merging.
3. After merge, run `cedrus deploy push` from a tagged release
   commit.
4. Verify the deployment via `deploy history` and by reading back
   the manifest hash.

## Failure handling

| Failure                                  | Behavior                                        |
| ---------------------------------------- | ----------------------------------------------- |
| Local directory unwritable               | `DeploymentError` raised before any write.     |
| HTTP endpoint returns non-2xx            | `DeploymentError` raised; response body captured. |
| HTTP timeout                             | `DeploymentError` raised; underlying `TimeoutError` chained. |
| Cedar schema mismatch (downstream)       | Surfaced by the consuming service; cedrus does not catch this. |

Always inspect the captured response body in `DeploymentRecord.response`
when investigating HTTP deployment failures.
