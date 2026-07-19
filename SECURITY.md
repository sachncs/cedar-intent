# Security policy

## Supported versions

`cedar-intent` follows semantic versioning. Security updates are
provided for the latest minor release and the previous minor release.

| Version | Supported          |
| ------- | ------------------ |
| 0.5.x   | :white_check_mark: |
| 0.4.x   | :white_check_mark: |
| < 0.4   | :x:                |

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

`cedar-intent` is a developer tool that turns English requirements into
Cedar policies. Its threat model covers:

- **LLM prompt injection** — adversarial inputs in requirements or
  schema fields. The tool's defense is the deterministic compiler
  followed by Cedar schema validation: any Cedar that fails schema
  validation is rejected before deployment.
- **Schema poisoning** — malicious or incorrect schemas supplied to
  the validator. The defense is Cedar's own schema validation plus
  the workspace's deployment history: deployments are bound to a
  SHA-256 hash of the compiled bundle.
- **Workspace tampering** — direct modification of `.cedar-intent/store.db`.
  Defenses include content hashing at deployment time and explicit
  recommendation to review every PR through Git before merging.
- **Bundle substitution** — an attacker replaces a deployed bundle
  on disk with a malicious one. The defense is the bundle hash
  recorded in the deployment history and the manifest's SHA-256.

`cedar-intent` is **not** a runtime authorization engine. It does not
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
- Run `cedar-intent verify --strict --domain <name>` in CI to fail
  builds when verification flags warnings.
- Store the workspace on an encrypted filesystem when policies
  describe sensitive data access.

## Acknowledgments

We thank the security researchers who report vulnerabilities
responsibly. Contributors are credited in the release notes for each
fixed advisory.
