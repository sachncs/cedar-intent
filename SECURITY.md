# Security policy

## Supported versions

`cedrus` follows semantic versioning. Security updates are
provided for the latest minor release and the previous minor release.

| Version | Supported          |
| ------- | ------------------ |
| 0.6.x   | :white_check_mark: |
| 0.5.x   | :white_check_mark: |
| < 0.5   | :x:                |

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub
issues, discussions, or pull requests.**

Send a private report to the maintainers via
[sachncs@gmail.com](mailto:sachncs@gmail.com). Include the following
information:

- A description of the vulnerability and its impact.
- A minimal reproduction, including the policy or schema involved.
- The commit or release tag where the issue was observed.
- Any known mitigations or workarounds.

We will acknowledge receipt within three business days and provide a
timeline for a fix. We will coordinate disclosure timing with you and
credit you in the security advisory unless you prefer to remain
anonymous.

## Threat model

`cedrus` is a developer tool that turns English requirements into
Cedar policies. Its threat model covers:

- **LLM prompt injection** — adversarial inputs in requirements or
  schema fields. As of 0.6.0, every piece of user-controlled content
  in the prompt is wrapped in fenced `<<<...>>>` delimiters and the
  system prompt explicitly forbids the model from following any
  instructions inside the markers. The deterministic compiler and
  Cedar schema validation remain the second line of defense: any
  Cedar that fails schema validation is rejected before deployment.
- **Schema poisoning** — malicious or incorrect schemas supplied to
  the validator. The defense is Cedar's own schema validation plus
  the workspace's deployment history: deployments are bound to a
  SHA-256 hash of the compiled bundle.
- **Workspace tampering** — direct modification of `.cedrus/store.db`.
  Defenses include content hashing at deployment time and explicit
  recommendation to review every PR through Git before merging.
- **Bundle substitution** — an attacker replaces a deployed bundle
  on disk with a malicious one. The defense is the bundle hash
  recorded in the deployment history and the manifest's SHA-256.
  Note: this hash provides **corruption detection**, not authenticated
  integrity. Operators who need tamper evidence should layer an
  HMAC-SHA-256 with a shared key or an Ed25519 signature in the
  deploy metadata on the receiving side.
- **SSRF on `deploy push`** — as of 0.6.0, the SSRF guard resolves
  the deployment target at SSRF-check time and pins every subsequent
  HTTP connection to that exact IP. This closes the DNS-rebinding
  window in which an attacker controlling authoritative DNS returns
  a public IP at guard time and a private IP at request time.
  Redirects are disabled by default. The `Host`, `Authorization`,
  `Cookie`, `Content-Length`, and `Transfer-Encoding` headers cannot
  be set via `--header` (rejected at parse time).
- **Header injection** — the `--header` flag rejects empty header
  names, reserved header names, and CR/LF in either name or value.
  An attacker pasting CRLF into a header value would have been able
  to inject additional HTTP headers or smuggle a request; this is
  now blocked at parse time.
- **Symlink replacement** — `Bundler.write_directory` refuses
  to write through a symlinked target directory. An attacker who
  controls a directory in the deployment path can no longer redirect
  the bundle write to a privileged location.
- **Global-permit fallback** — earlier versions synthesized a
  permissive `permit(any/any/any)` when stored draft intent JSON was
  missing or corrupt. As of 0.6.0, `intent_from_draft` returns `None`
  or raises `Space` instead, so a corrupt stored row can
  no longer ship as a wide-open policy.
- **Verifier silent degradation** — the pre-0.6.0 verifier used a
  regex parser that returned `permit(any/any/any)` when it could not
  parse a policy, suppressing coverage failures and hiding shadowing.
  The 0.6.0 verifier parses via the cedarpy AST and emits a
  `malformed-policy` finding when cedarpy rejects the input.

`cedrus` is **not** a runtime authorization engine. It does not
evaluate authorization requests itself; applications embed the Cedar
policy engine for that. Concerns about runtime request evaluation,
policy evaluation performance, or authorization service availability
belong to the deployed Cedar engine, not to this tool.

## Hardening guidance for operators

- Review every compiled Cedar policy in a pull request before
  deploying. The `deploy history` command lists past deployments
  with their hashes for traceability.
- Pin the LLM model and provider in your workspace configuration.
  Untrusted model responses can introduce subtle mistakes.
- Run `cedrus verify --strict --domain <name>` in CI to fail
  builds when verification flags warnings.
- Store the workspace on an encrypted filesystem when policies
  describe sensitive data access.
- For HTTP deploy targets, run the deployment client behind a CA-pinned
  TLS configuration (`cafile`/`capath`) and treat the deployment
  manifest's SHA-256 hash as corruption detection only. Add a keyed
  signature (HMAC-SHA-256 or Ed25519) in the deploy metadata when you
  need tamper evidence.
- Never enable `--allow-loopback` or `--allow-private-targets` in
  production. They exist for tests that bind to `127.0.0.1` and for
  on-prem deployments to private networks respectively.

## Acknowledgments

We thank the security researchers who report vulnerabilities
responsibly. Contributors are credited in the release notes for each
fixed advisory.
